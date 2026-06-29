"""
Orders URL routes.

Sprint 3 wires cart, checkout, and the Stripe webhook. The Printify webhook
stub from Sprint 2 stays at the same URL; Sprint 4 will replace its
implementation in views.py without breaking the URL contract.
"""

from django.urls import path

from . import views

app_name = 'orders'

urlpatterns = [
    # -------- Cart --------
    path('cart/', views.cart_page, name='cart_page'),
    path('cart/add/', views.cart_add, name='cart_add'),
    path('cart/items/<int:item_pk>/update/', views.cart_update_item, name='cart_update_item'),
    path('cart/items/<int:item_pk>/remove/', views.cart_remove_item, name='cart_remove_item'),
    path('cart/mini/', views.mini_cart, name='mini_cart'),
    path('cart/shipping-quote/', views.cart_shipping_quote, name='cart_shipping_quote'),

    # -------- Checkout --------
    path('checkout/', views.checkout_start, name='checkout_start'),
    path('checkout/success/', views.checkout_success, name='checkout_success'),

    # -------- Webhooks --------
    path('webhooks/stripe/', views.stripe_webhook, name='stripe_webhook'),
    path('webhooks/printify/', views.printify_webhook, name='printify_webhook'),
]
