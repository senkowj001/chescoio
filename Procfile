web: gunicorn chescoio.wsgi --workers 2 --threads 2 --worker-class gthread --timeout 120 --preload --log-file -
release: python manage.py migrate --noinput && python manage.py collectstatic --noinput
