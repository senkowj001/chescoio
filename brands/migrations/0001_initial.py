from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='Brand',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('domain', models.CharField(help_text='Bare apex domain, e.g. "chesco.io". www is stripped before lookup.', max_length=255, unique=True)),
                ('name', models.CharField(max_length=100)),
                ('tagline', models.CharField(blank=True, max_length=200)),
                ('description', models.TextField(blank=True)),
                ('printify_shop_id', models.CharField(blank=True, max_length=50)),
                ('primary_color', models.CharField(default='#000000', max_length=7)),
                ('accent_color', models.CharField(default='#FF6B35', max_length=7)),
                ('logo_url', models.URLField(blank=True)),
                ('font_family', models.CharField(default='Inter', max_length=100)),
                ('meta_pixel_id', models.CharField(blank=True, max_length=50)),
                ('plausible_domain', models.CharField(blank=True, max_length=255)),
                ('from_email', models.EmailField(max_length=254)),
                ('support_email', models.EmailField(max_length=254)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
    ]
