"""Tests for the health endpoint."""

from django.test import SimpleTestCase
from django.urls import reverse


class HealthzTests(SimpleTestCase):
    def test_healthz_reports_ok(self):
        response = self.client.get(reverse('healthz'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})
        self.assertEqual(response['Content-Type'], 'application/json')

    def test_unknown_path_is_not_found(self):
        self.assertEqual(self.client.get('/no-such-path').status_code, 404)
