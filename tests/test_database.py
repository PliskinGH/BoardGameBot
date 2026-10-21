"""Tests for the database configuration."""

from django.db import connection
from django.test import TestCase


class DatabaseTests(TestCase):
    def test_database_connection_works(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            self.assertEqual(cursor.fetchone(), (1,))
