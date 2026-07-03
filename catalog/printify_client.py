"""
Printify REST API client.

Thin wrapper over Printify's v1 REST API. The client handles:
  - Bearer-token auth from settings.PRINTIFY_ACCESS_TOKEN
  - Retry-with-backoff on 429 (Too Many Requests) and transient 5xx
  - Request logging with timing
  - Sensible 30s timeouts

Rate limits (per Printify docs, October 2024):
  - 600 req/min global
  - 200 req / 30s on catalog endpoints
The sync command paginates list_products with limit=50 to stay well under both.

API reference: https://developers.printify.com/

Mirrors Apeirum's FMP client pattern (myticker/scanner/services/fmp_client.py)
for retry semantics and session reuse.
"""

import logging
import time
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class PrintifyError(Exception):
    """Raised for unrecoverable Printify API errors."""

    def __init__(self, message: str, status_code: int | None = None, response_body: str = ''):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class PrintifyClient:
    BASE_URL = 'https://api.printify.com/v1'
    DEFAULT_TIMEOUT = 30  # seconds
    MAX_RETRIES = 3

    def __init__(self, access_token: str | None = None):
        self.token = access_token or getattr(settings, 'PRINTIFY_ACCESS_TOKEN', '')
        if not self.token:
            raise PrintifyError(
                'PRINTIFY_ACCESS_TOKEN is not configured. Set it in environment '
                '(local: .env, Heroku: heroku config:set).'
            )
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json',
            'User-Agent': 'chescoio/1.0 (+https://chesco.io)',
        })

    # ------------------------------------------------------------------
    # Internal: request with retry-with-backoff on 429 / transient 5xx
    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f'{self.BASE_URL}{path}'
        kwargs.setdefault('timeout', self.DEFAULT_TIMEOUT)

        last_exception: Exception | None = None
        for attempt in range(self.MAX_RETRIES):
            start = time.monotonic()
            try:
                resp = self.session.request(method, url, **kwargs)
            except requests.RequestException as e:
                last_exception = e
                logger.warning(
                    'Printify %s %s network error (attempt %d/%d): %s',
                    method, path, attempt + 1, self.MAX_RETRIES, e,
                )
                time.sleep(2 ** attempt)
                continue

            elapsed_ms = int((time.monotonic() - start) * 1000)

            # 429 — back off and retry
            if resp.status_code == 429:
                retry_after = int(resp.headers.get('Retry-After', 2 ** attempt))
                logger.warning(
                    'Printify %s %s rate-limited (429). Sleeping %ds.',
                    method, path, retry_after,
                )
                time.sleep(retry_after)
                continue

            # Transient 5xx — back off and retry
            if 500 <= resp.status_code < 600:
                logger.warning(
                    'Printify %s %s returned %d (attempt %d/%d) in %dms',
                    method, path, resp.status_code, attempt + 1, self.MAX_RETRIES, elapsed_ms,
                )
                time.sleep(2 ** attempt)
                continue

            # 4xx other than 429 — surface immediately (no retry)
            if resp.status_code >= 400:
                logger.error(
                    'Printify %s %s failed: %d %s',
                    method, path, resp.status_code, resp.text[:500],
                )
                raise PrintifyError(
                    f'Printify {method} {path} returned {resp.status_code}',
                    status_code=resp.status_code,
                    response_body=resp.text,
                )

            logger.debug('Printify %s %s OK (%dms)', method, path, elapsed_ms)
            # DELETE and some POST callbacks (webhooks, publishing_succeeded)
            # return 204/empty bodies. resp.json() would raise on those.
            if resp.status_code == 204 or not resp.content:
                return None
            return resp.json()

        # Out of retries
        raise PrintifyError(
            f'Printify {method} {path} exhausted {self.MAX_RETRIES} retries: {last_exception}'
        )

    # ------------------------------------------------------------------
    # Shops
    # ------------------------------------------------------------------

    def list_shops(self) -> list[dict]:
        """GET /shops.json — every shop connected to this account."""
        return self._request('GET', '/shops.json')

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------

    def list_products(self, shop_id: str, page: int = 1, limit: int = 50) -> dict:
        """
        GET /shops/{shop_id}/products.json — paginated product list.

        Returns the full Laravel-style pagination envelope:
            {
              "current_page": 1, "data": [...products...],
              "next_page_url": "..." | null, "last_page": N, ...
            }

        Each product in `data` includes its variants and images, so a separate
        call to get_product() is only needed for product details we don't get
        in the list response.
        """
        return self._request(
            'GET',
            f'/shops/{shop_id}/products.json',
            params={'page': page, 'limit': limit},
        )

    def get_product(self, shop_id: str, product_id: str) -> dict:
        """GET /shops/{shop_id}/products/{product_id}.json — full product detail."""
        return self._request('GET', f'/shops/{shop_id}/products/{product_id}.json')

    # ------------------------------------------------------------------
    # Catalog (blueprints / print providers)
    # ------------------------------------------------------------------

    def get_blueprint(self, blueprint_id: int) -> dict:
        """GET /catalog/blueprints/{blueprint_id}.json — blueprint metadata."""
        return self._request('GET', f'/catalog/blueprints/{blueprint_id}.json')

    # ------------------------------------------------------------------
    # Orders (used in Sprint 4)
    # ------------------------------------------------------------------

    def calculate_shipping(self, shop_id: str, address: dict, line_items: list[dict]) -> dict:
        """POST /shops/{shop_id}/orders/shipping.json — quote shipping for a cart."""
        return self._request(
            'POST',
            f'/shops/{shop_id}/orders/shipping.json',
            json={'address_to': address, 'line_items': line_items},
        )

    def create_order(self, shop_id: str, payload: dict) -> dict:
        """POST /shops/{shop_id}/orders.json — submit an order for fulfillment."""
        return self._request('POST', f'/shops/{shop_id}/orders.json', json=payload)

    def get_order(self, shop_id: str, order_id: str) -> dict:
        """GET /shops/{shop_id}/orders/{order_id}.json — order detail incl. status."""
        return self._request('GET', f'/shops/{shop_id}/orders/{order_id}.json')

    # ------------------------------------------------------------------
    # Publishing callbacks (Sprint 4)
    #
    # After product:publish:started fires, Printify locks the product card
    # in their UI until we call one of these. publishing_succeeded unlocks
    # it; publishing_failed unlocks it and surfaces `reason` to the merchant.
    # ------------------------------------------------------------------

    def publishing_succeeded(self, shop_id: str, product_id: str) -> Any:
        """POST /shops/{shop_id}/products/{product_id}/publishing_succeeded.json"""
        return self._request(
            'POST',
            f'/shops/{shop_id}/products/{product_id}/publishing_succeeded.json',
            json={},
        )

    def publishing_failed(self, shop_id: str, product_id: str, reason: str) -> Any:
        """POST /shops/{shop_id}/products/{product_id}/publishing_failed.json"""
        return self._request(
            'POST',
            f'/shops/{shop_id}/products/{product_id}/publishing_failed.json',
            json={'reason': reason},
        )

    # ------------------------------------------------------------------
    # Webhooks (Sprint 4)
    #
    # Printify has no dashboard UI for webhook subscriptions — registration
    # is API-only. Used by the register_printify_webhooks management command.
    # ------------------------------------------------------------------

    def list_webhooks(self, shop_id: str) -> Any:
        """GET /shops/{shop_id}/webhooks.json — every webhook subscription on this shop."""
        return self._request('GET', f'/shops/{shop_id}/webhooks.json')

    def create_webhook(self, shop_id: str, topic: str, url: str, secret: str) -> Any:
        """POST /shops/{shop_id}/webhooks.json — subscribe to a topic."""
        return self._request(
            'POST',
            f'/shops/{shop_id}/webhooks.json',
            json={'topic': topic, 'url': url, 'secret': secret},
        )

    def update_webhook(self, shop_id: str, webhook_id: str, *, url: str, secret: str) -> Any:
        """PUT /shops/{shop_id}/webhooks/{webhook_id}.json — repoint an existing subscription."""
        return self._request(
            'PUT',
            f'/shops/{shop_id}/webhooks/{webhook_id}.json',
            json={'url': url, 'secret': secret},
        )

    def delete_webhook(self, shop_id: str, webhook_id: str) -> Any:
        """DELETE /shops/{shop_id}/webhooks/{webhook_id}.json"""
        return self._request('DELETE', f'/shops/{shop_id}/webhooks/{webhook_id}.json')
