# Generated for Sprint 4 — email dedupe guard fields on Order.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0002_cart_cartitem_order_orderitem_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='confirmation_sent_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='order',
            name='shipped_email_sent_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
