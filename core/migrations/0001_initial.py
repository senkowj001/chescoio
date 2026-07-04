# Hand-written to match the Sprint 3/4 migration convention (this session edits
# the Windows filesystem directly and can't run `manage.py makemigrations`).
# Creates the Sprint 5 core content models: StaticPage (markdown CMS pages),
# EmailSignup (new-release list), ContactMessage (contact-form audit log).
# All three are brand-scoped. Run `python manage.py makemigrations --check`
# after pulling to confirm the model state and this migration agree, then
# `migrate`.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('brands', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='StaticPage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.SlugField(help_text='URL slug. Canonical pages: about, privacy, terms, returns, shipping, size-guide. Others resolve at /p/<slug>/.', max_length=100)),
                ('title', models.CharField(max_length=200)),
                ('content', models.TextField(blank=True, help_text='Markdown. Rendered to HTML on the page. Authored by staff, so raw HTML in the markdown is allowed (trusted source).')),
                ('meta_description', models.CharField(blank=True, help_text='Optional. Used for the <meta name="description"> / OpenGraph description on this page. Falls back to the page title.', max_length=300)),
                ('is_published', models.BooleanField(default=True, help_text='Unpublished pages 404 for the public but are previewable by logged-in staff.')),
                ('needs_review', models.BooleanField(default=True, help_text='Admin checklist flag: content is a draft awaiting sign-off. Does not affect what visitors see \u2014 uncheck once approved.')),
                ('sort_order', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('brand', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='static_pages', to='brands.brand')),
            ],
            options={
                'ordering': ['sort_order', 'title'],
            },
        ),
        migrations.CreateModel(
            name='EmailSignup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(max_length=254)),
                ('source', models.CharField(choices=[('footer', 'Footer'), ('homepage', 'Homepage'), ('popup', 'Popup'), ('other', 'Other')], default='footer', max_length=20)),
                ('is_confirmed', models.BooleanField(default=False, help_text='Reserved for a future double opt-in flow (2.0). False for v1.')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('brand', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='email_signups', to='brands.brand')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ContactMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120)),
                ('email', models.EmailField(max_length=254)),
                ('message', models.TextField()),
                ('is_handled', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('brand', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='contact_messages', to='brands.brand')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='staticpage',
            unique_together={('brand', 'slug')},
        ),
        migrations.AlterUniqueTogether(
            name='emailsignup',
            unique_together={('brand', 'email')},
        ),
    ]
