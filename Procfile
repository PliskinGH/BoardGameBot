release: python manage.py migrate --no-input
web: uvicorn config.asgi:application --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --proxy-headers --forwarded-allow-ips="*" --timeout-keep-alive 65 --lifespan off
worker: python manage.py runbot
