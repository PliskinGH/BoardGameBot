"""Tests for the Discord login flow."""

from unittest import mock

import requests
from django.test import TestCase, override_settings
from django.urls import reverse

from core import discord_api, permissions
from core.models import Guild, Player
from tests.support import NoNetworkMixin

ACCOUNT = {'id': '42', 'username': 'hostie'}
GUILDS = [{'id': '7', 'name': 'Server Seven',
           'permissions': str(discord_api.MANAGE_GUILD)}]
IDENTITY = {'account': ACCOUNT, 'guilds': GUILDS}

OAUTH_SETTINGS = {
    'DISCORD_CLIENT_ID': 'cid',
    'DISCORD_CLIENT_SECRET': 'secret',
    'DISCORD_REDIRECT_URI': 'https://example.test/discord/callback/',
}


@override_settings(**OAUTH_SETTINGS)
class LoginTests(NoNetworkMixin, TestCase):
    def test_the_login_page_offers_discord(self):
        response = self.client.get(reverse('core:login'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Log in with Discord')
        self.assertContains(response, '<title>Log in | BoardGameBot</title>')

    @override_settings(DISCORD_CLIENT_ID=None)
    def test_the_login_page_says_when_discord_is_unconfigured(self):
        response = self.client.get(reverse('core:login'))

        self.assertContains(response, 'Discord login is not configured')

    def test_connect_redirects_to_discord(self):
        response = self.client.get(reverse('core:discord_connect'))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith(
            discord_api.DISCORD_AUTHORIZE_URL))
        self.assertIn(discord_api.STATE_SESSION_KEY, self.client.session)

    @override_settings(DISCORD_CLIENT_ID=None)
    def test_connect_is_not_found_without_credentials(self):
        response = self.client.get(reverse('core:discord_connect'))

        self.assertEqual(response.status_code, 404)

    def test_connect_keeps_a_safe_next(self):
        self.client.get(reverse('core:discord_connect'),
                        {'next': '/g/7/matches/1/'})

        self.assertEqual(self.client.session[discord_api.NEXT_SESSION_KEY],
                         '/g/7/matches/1/')

    def test_connect_drops_a_next_on_another_site(self):
        self.client.get(reverse('core:discord_connect'),
                        {'next': 'https://evil.test/steal'})

        self.assertNotIn(discord_api.NEXT_SESSION_KEY, self.client.session)


    def test_callback_logs_the_player_in(self):
        self._start('state-1')
        with mock.patch.object(discord_api, 'fetch_discord_identity',
                               return_value=IDENTITY):
            response = self.client.get(reverse('core:discord_callback'),
                                       {'code': 'abc', 'state': 'state-1'})

        self.assertRedirects(response, reverse('board:index'))
        player = Player.objects.get(discord_user_id=42)
        self.assertEqual(player.discord_name, 'hostie')
        self.assertEqual(self.client.session['_auth_user_id'], str(player.pk))
        self.assertEqual(
            self.client.session[discord_api.GUILDS_SESSION_KEY],
            [{'id': 7, 'name': 'Server Seven',
              'permissions': discord_api.MANAGE_GUILD}])

    def test_callback_seeds_the_managers_of_a_known_server(self):
        guild = Guild.objects.create(discord_id=7, name='Server Seven')
        self._start('state-1')
        with mock.patch.object(discord_api, 'fetch_discord_identity',
                               return_value=IDENTITY):
            self.client.get(reverse('core:discord_callback'),
                            {'code': 'abc', 'state': 'state-1'})

        player = Player.objects.get(discord_user_id=42)
        self.assertTrue(permissions.is_guild_manager(guild, player))

    def test_callback_ignores_servers_the_bot_does_not_know(self):
        self._start('state-1')
        with mock.patch.object(discord_api, 'fetch_discord_identity',
                               return_value=IDENTITY):
            response = self.client.get(reverse('core:discord_callback'),
                                       {'code': 'abc', 'state': 'state-1'})

        self.assertRedirects(response, reverse('board:index'))

    def test_callback_returns_to_the_page_the_login_asked_for(self):
        self._start('state-1', next_url='/g/7/matches/1/')
        with mock.patch.object(discord_api, 'fetch_discord_identity',
                               return_value=IDENTITY):
            response = self.client.get(reverse('core:discord_callback'),
                                       {'code': 'abc', 'state': 'state-1'})

        self.assertEqual(response['Location'], '/g/7/matches/1/')

    def test_callback_refuses_a_bad_state(self):
        self._start('state-1')

        response = self.client.get(reverse('core:discord_callback'),
                                   {'code': 'abc', 'state': 'other'}, follow=True)

        self._refused(response, 'Discord login failed')

    def test_callback_reports_a_cancelled_login(self):
        response = self.client.get(reverse('core:discord_callback'),
                                   {'error': 'access_denied'}, follow=True)

        self._refused(response, 'Discord login was cancelled')

    def test_callback_reports_an_unreachable_discord(self):
        self._start('state-1')
        with mock.patch.object(
                discord_api, 'fetch_discord_identity',
                side_effect=requests.RequestException('down')):
            response = self.client.get(reverse('core:discord_callback'),
                                       {'code': 'abc', 'state': 'state-1'},
                                       follow=True)

        self._refused(response, 'Discord login failed')

    @override_settings(DISCORD_CLIENT_ID=None)
    def test_callback_is_not_found_without_credentials(self):
        response = self.client.get(reverse('core:discord_callback'))

        self.assertEqual(response.status_code, 404)

    def test_logout_ends_the_session(self):
        player = Player.objects.create_user(username='wendy',
                                            email='wendy@example.com',
                                            password='secret')
        self.client.force_login(player)

        response = self.client.post(reverse('core:logout'))

        self.assertRedirects(response, reverse('core:login'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_logout_needs_a_post(self):
        self.assertEqual(self.client.get(reverse('core:logout')).status_code,
                         405)

    def _start(self, state, next_url=None):
        """Put the flow's state, and an optional next page, in the session."""
        session = self.client.session
        session[discord_api.STATE_SESSION_KEY] = state
        if next_url:
            session[discord_api.NEXT_SESSION_KEY] = next_url
        session.save()

    def _refused(self, response, text):
        """Assert the flow ended back on the login page saying ``text``."""
        self.assertEqual(response.redirect_chain[-1][0],
                         reverse('core:login'))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertContains(response, text)

