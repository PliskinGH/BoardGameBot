"""Tests for the infrastructure settings."""

from django.conf import settings
from django.test import SimpleTestCase


class SettingsTests(SimpleTestCase):
    def test_asgi_application_is_configured(self):
        self.assertEqual(settings.ASGI_APPLICATION, 'config.asgi.application')

    def test_asgi_application_is_callable(self):
        from config.asgi import application

        self.assertTrue(callable(application))

    def test_whitenoise_follows_security_middleware(self):
        middleware = list(settings.MIDDLEWARE)
        position = middleware.index(
            'django.middleware.security.SecurityMiddleware')

        self.assertEqual(middleware[position + 1],
                         'whitenoise.middleware.WhiteNoiseMiddleware')

    def test_static_files_are_compressed(self):
        self.assertEqual(
            settings.STORAGES['staticfiles']['BACKEND'],
            'whitenoise.storage.CompressedStaticFilesStorage')

    def test_the_login_routes_are_named_urls(self):
        self.assertEqual(settings.LOGIN_URL, 'core:login')
        self.assertEqual(settings.LOGIN_REDIRECT_URL, 'board:index')
        self.assertEqual(settings.LOGOUT_REDIRECT_URL, 'core:login')

