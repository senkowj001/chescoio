"""
Orders views.

Sprint 2 lands the Printify webhook receiver as an idempotent logging stub:
verifies the request is JSON, records a WebhookEvent row, returns 200. Full
event handling (status transitions, email notifications) lands in Sprint 4.

Stripe webhook + cart views arrive in Sprint 3.
"""

import json
import logging

from django.http import HttpResponse, HttpResponseBadRequest
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import WebhookEvent

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def printify_webhook(request):
    """
    POST /webhooks/printify/

    Sprint 2 stub: parses JSON, dedupes on (source=printify, event_id),
    persists the payload to WebhookEvent, returns 200. No business logic
    is applied yet — Sprint 4 wires this up to update Order status and fire
    customer notifications.

    TODO (Sprint 4):
      - Verify HMAC signature using settings.PRINTIFY_WEBHOOK_SECRET
        (header: X-Printify-Signature)
      - Dispatch to event-type-specific handlers
      - Flip processed_at when the handler completes
    """
    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        logger.warning('Printify webhook: invalid JSON body (len=%d)', len(request.body or b''))
        return HttpResponseBadRequest('Invalid JSON')

    # Printify event payloads carry an id at the top level; fall back to a
    # synthetic id if it's somehow missing so we still record the event.
    raw_id = payload.get('id')
    event_id = str(raw_id) if raw_id is not None else f'no-id-{timezone.now().timestamp()}'
    event_type = str(payload.get('type', ''))[:100]

    obj, created = WebhookEvent.objects.get_or_create(
        source=WebhookEvent.SOURCE_PRINTIFY,
        event_id=event_id,
        defaults={
            'event_type': event_type,
            'payload': payload,
        },
    )

    if created:
        logger.info('Printify webhook recorded: type=%s id=%s', event_type, event_id)
    else:
        logger.info('Printify webhook duplicate ignored: type=%s id=%s', event_type, event_id)

    return HttpResponse(status=200)
