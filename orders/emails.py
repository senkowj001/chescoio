"""
Transactional email senders for the orders app.

Sprint 4 adds three emails:
  - send_order_confirmation(order)   — fired right after Order creation
  - send_order_shipped(order)        — fired on order:shipment:created
  - send_admin_order_failed(order, error) — internal alert on Printify
    submission failure

All customer-facing emails go through django-mailer's send_html_mail(),
which queues to the DB (EMAIL_BACKEND = 'mailer.backend.DbBackend' in
settings/base.py) rather than sending directly. The queue is drained by
`python manage.py send_mail` + `retry_deferred`, run via Heroku Scheduler
every 10 minutes (see sprintplans delivery notes for the wiring).

Brand-aware throughout: every template receives `brand` (order.brand) and
reads name / colors / support_email from it. Never hardcode "Chesco" or
any brand-specific string here or in the templates — Sprint 5 may add a
second brand front on the same backend.

Idempotency: WebhookEvent's (source, event_id) uniqueness is the primary
defense against a webhook redelivery re-triggering a handler. Each sender
here additionally gates on an Order timestamp field (confirmation_sent_at /
shipped_email_sent_at) as a second, independent guard — see the Order model
docstring note for the rationale mirrored from the Sprint 3 webhook-filter
pattern.
"""

from __future__ import annotations

import logging

import mailer
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from .models import Order

logger = logging.getLogger(__name__)


def send_order_confirmation(order: Order) -> None:
    """
    Send the order confirmation email. Called right after Order creation in
    orders/views.py::_handle_checkout_completed, before Printify submission
    is attempted — the customer paid, so they get a receipt regardless of
    what happens next in the fulfillment pipeline.
    """
    if order.confirmation_sent_at is not None:
        logger.info('Order #%d: confirmation already sent; skipping.', order.pk)
        return
    if not order.email:
        logger.warning('Order #%d has no email address; cannot send confirmation.', order.pk)
        return

    brand = order.brand
    ctx = {'order': order, 'brand': brand}
    subject = f'Your {brand.name} order #{order.pk} is confirmed'

    try:
        text_body = render_to_string('emails/order_confirmation.txt', ctx)
        html_body = render_to_string('emails/order_confirmation.html', ctx)
        mailer.send_html_mail(
            subject=subject,
            message=text_body,
            message_html=html_body,
            from_email=brand.from_email or settings.DEFAULT_FROM_EMAIL,
            recipient_list=[order.email],
        )
    except Exception:
        logger.exception('Order #%d: failed to queue confirmation email.', order.pk)
        return

    order.confirmation_sent_at = timezone.now()
    order.save(update_fields=['confirmation_sent_at'])
    logger.info('Order #%d: confirmation email queued to %s.', order.pk, order.email)


def send_order_shipped(order: Order) -> None:
    """
    Send the shipped notification email, including tracking info. Called
    from the order:shipment:created Printify webhook handler after the
    Order's tracking fields have been populated.
    """
    if order.shipped_email_sent_at is not None:
        logger.info('Order #%d: shipped email already sent; skipping.', order.pk)
        return
    if not order.email:
        logger.warning('Order #%d has no email address; cannot send shipped notice.', order.pk)
        return

    brand = order.brand
    ctx = {'order': order, 'brand': brand}
    subject = f'Your {brand.name} order #{order.pk} has shipped'

    try:
        text_body = render_to_string('emails/order_shipped.txt', ctx)
        html_body = render_to_string('emails/order_shipped.html', ctx)
        mailer.send_html_mail(
            subject=subject,
            message=text_body,
            message_html=html_body,
            from_email=brand.from_email or settings.DEFAULT_FROM_EMAIL,
            recipient_list=[order.email],
        )
    except Exception:
        logger.exception('Order #%d: failed to queue shipped email.', order.pk)
        return

    order.shipped_email_sent_at = timezone.now()
    order.save(update_fields=['shipped_email_sent_at'])
    logger.info('Order #%d: shipped email queued to %s.', order.pk, order.email)


def send_admin_order_failed(order: Order, error) -> None:
    """
    Internal alert to the brand's support_email when Printify rejects an
    order submission. No dedupe guard here on purpose — if submission is
    retried and fails again, the admin should hear about it again.
    """
    brand = order.brand
    support_email = brand.support_email or settings.DEFAULT_FROM_EMAIL
    ctx = {'order': order, 'brand': brand, 'error': str(error)}
    subject = f'[ACTION REQUIRED] Order #{order.pk} failed Printify submission ({brand.name})'

    try:
        text_body = render_to_string('emails/admin_order_failed.txt', ctx)
        mailer.send_mail(
            subject=subject,
            message=text_body,
            from_email=brand.from_email or settings.DEFAULT_FROM_EMAIL,
            recipient_list=[support_email],
        )
    except Exception:
        logger.exception('Order #%d: failed to queue admin failure alert.', order.pk)
        return

    logger.info('Order #%d: submission-failure alert queued to %s.', order.pk, support_email)
