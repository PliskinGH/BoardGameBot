"""Tests that the admin surfaces load and list their rows."""

from django.contrib import admin
from django.test import TestCase

from core.models import Guild, Player
from games.models import Action, Match, OutboxMessage


class AdminTests(TestCase):
    def test_the_models_are_registered(self):
        for model in (Player, Guild, Match, Action, OutboxMessage):
            self.assertTrue(admin.site.is_registered(model))

    def test_the_guild_admin_lists_servers(self):
        root = Player.objects.create_superuser(
            username='root', email='root@example.com', password='secret')
        Guild.objects.create(discord_id=1, name='Server')
        self.client.force_login(root)

        response = self.client.get('/admin/core/guild/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Server')

    def test_the_admin_lists_players_and_matches(self):
        root = Player.objects.create_superuser(
            username='root', email='root@example.com', password='secret')
        self.client.force_login(root)

        self.assertEqual(self.client.get('/admin/core/player/').status_code,
                         200)
        self.assertEqual(self.client.get('/admin/games/match/').status_code,
                         200)
