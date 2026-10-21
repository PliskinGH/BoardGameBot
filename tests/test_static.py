"""Tests for the static files configuration."""

from django.contrib.staticfiles import finders
from django.test import SimpleTestCase


class StaticFilesTests(SimpleTestCase):
    def test_project_static_file_is_discoverable(self):
        self.assertIsNotNone(finders.find('css/site.css'))
