"""Tests for the Discord OAuth seam and the players it creates."""

from unittest import mock
from urllib.parse import parse_qs, urlparse

import requests
from django.test import (RequestFactory, SimpleTestCase, TestCase,
                         override_settings)

from core import discord_api
from core.models import DiscordAccount, Player
from tests.support import NetworkAccessDenied, NoNetworkMixin

ACCOUNT = {'id': '42', 'username': 'hostie'}
GUILDS = [{'id': '7', 'name': 'Server Seven',
           'permissions': str(discord_api.MANAGE_GUILD)}]
IDENTITY = {'account': ACCOUNT, 'guilds': GUILDS}

OAUTH_SETTINGS = {
    'DISCORD_CLIENT_ID': 'cid',
    'DISCORD_CLIENT_SECRET': 'secret',
    'DISCORD_REDIRECT_URI': 'https://example.test/discord/callback/',
}


def answer(payload, *, error=None):
    """Return a requests response stand-in that answers with ``payload``."""
    response = mock.Mock()
    response.json.return_value = payload
    if error is not None:
        response.raise_for_status.side_effect = error
    return response


@override_settings(**OAUTH_SETTINGS)
class AuthorizeUrlTests(NoNetworkMixin, SimpleTestCase):
    def test_the_url_names_the_application_and_the_state(self):
        request = RequestFactory().get('/login/')
        url = urlparse(discord_api.authorize_url(request, 'state-1'))
        params = parse_qs(url.query)

        self.assertEqual(f'{url.scheme}://{url.netloc}{url.path}',
                         discord_api.DISCORD_AUTHORIZE_URL)
        self.assertEqual(params['client_id'], ['cid'])
        self.assertEqual(params['redirect_uri'],
                         [OAUTH_SETTINGS['DISCORD_REDIRECT_URI']])
        self.assertEqual(params['response_type'], ['code'])
        self.assertEqual(params['scope'], ['identify guilds'])
        self.assertEqual(params['state'], ['state-1'])

    @override_settings(DISCORD_REDIRECT_URI=None)
    def test_the_callback_url_is_used_when_none_is_configured(self):
        request = RequestFactory().get('/login/')

        self.assertEqual(discord_api.discord_redirect_uri(request),
                         'http://testserver/discord/callback/')

    def test_the_login_is_unconfigured_without_credentials(self):
        with override_settings(DISCORD_CLIENT_SECRET=None):
            self.assertFalse(discord_api.discord_oauth_configured())

    def test_the_network_guard_catches_a_forgotten_mock(self):
        with self.assertRaises(NetworkAccessDenied):
            requests.get('https://discord.com/api/v10/users/@me')


@override_settings(**OAUTH_SETTINGS)
class IdentityTests(NoNetworkMixin, SimpleTestCase):
    def test_the_code_is_exchanged_and_the_identity_read(self):
        request = RequestFactory().get('/discord/callback/')
        with mock.patch.object(
                discord_api.requests, 'post',
                return_value=answer({'access_token': 'token-1'})) as post, \
                mock.patch.object(
                    discord_api.requests, 'get',
                    side_effect=[answer(ACCOUNT), answer(GUILDS)]) as get:
            identity = discord_api.fetch_discord_identity(request, 'code-1')

        self.assertEqual(identity, IDENTITY)
        sent = post.call_args.kwargs['data']
        self.assertEqual(sent['grant_type'], 'authorization_code')
        self.assertEqual(sent['code'], 'code-1')
        self.assertEqual(sent['redirect_uri'],
                         OAUTH_SETTINGS['DISCORD_REDIRECT_URI'])
        self.assertEqual(get.call_args_list[0].kwargs['headers'],
                         {'Authorization': 'Bearer token-1'})
        self.assertEqual(get.call_args_list[1].args[0],
                         f'{discord_api.DISCORD_API_BASE_URL}/users/@me/guilds')

    def test_a_refused_exchange_raises(self):
        request = RequestFactory().get('/discord/callback/')
        with mock.patch.object(
                discord_api.requests, 'post',
                return_value=answer({}, error=requests.HTTPError('400'))):
            with self.assertRaises(requests.HTTPError):
                discord_api.fetch_discord_identity(request, 'code-1')

    def test_an_account_is_read_from_the_identity(self):
        self.assertEqual(discord_api.account_of(IDENTITY),
                         DiscordAccount(id=42, name='hostie'))


@override_settings(**OAUTH_SETTINGS)
class SessionIdentityTests(SimpleTestCase):
    def test_the_session_keeps_the_guilds_and_their_permissions(self):
        session = {}

        discord_api.store_identity(session, IDENTITY)

        self.assertEqual(session[discord_api.USER_SESSION_KEY],
                         {'id': 42, 'username': 'hostie'})
        self.assertEqual(session[discord_api.GUILDS_SESSION_KEY],
                         [{'id': 7, 'name': 'Server Seven',
                           'permissions': discord_api.MANAGE_GUILD}])
        self.assertEqual(discord_api.session_guilds(session),
                         session[discord_api.GUILDS_SESSION_KEY])



class PlayerManagerTests(TestCase):
    def test_an_account_creates_a_player_without_a_password(self):
        player = Player.objects.from_discord(
            DiscordAccount(id=42, name='hostie'))

        self.assertEqual(player.discord_user_id, 42)
        self.assertEqual(player.username, 'hostie')
        self.assertEqual(player.discord_name, 'hostie')
        self.assertFalse(player.has_usable_password())

    def test_the_same_account_keeps_its_row(self):
        first = Player.objects.from_discord(DiscordAccount(id=42,
                                                           name='hostie'))
        second = Player.objects.from_discord(DiscordAccount(id=42,
                                                            name='hostie'))

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Player.objects.count(), 1)

    def test_a_renamed_account_follows_the_new_name(self):
        Player.objects.from_discord(DiscordAccount(id=42, name='hostie'))

        player = Player.objects.from_discord(DiscordAccount(id=42,
                                                            name='new-name'))

        self.assertEqual(player.discord_name, 'new-name')
        self.assertEqual(player.username, 'new-name')
        self.assertEqual(Player.objects.count(), 1)

    def test_a_taken_username_falls_back_to_the_id(self):
        Player.objects.create_user(username='hostie',
                                   email='hostie@example.com',
                                   password='secret')

        player = Player.objects.from_discord(DiscordAccount(id=42,
                                                            name='hostie'))

        self.assertEqual(player.username, 'discord_42')
        self.assertEqual(player.discord_name, 'hostie')

    def test_a_name_reported_by_discord_moves_to_its_owner(self):
        stale = Player.objects.from_discord(DiscordAccount(id=1,
                                                           name='hostie'))

        player = Player.objects.from_discord(DiscordAccount(id=2,
                                                            name='hostie'))

        stale.refresh_from_db()
        self.assertIsNone(stale.discord_name)
        self.assertEqual(stale.username, 'discord_1')
        self.assertEqual(player.discord_name, 'hostie')



@override_settings(**OAUTH_SETTINGS)
class InviteTests(NoNetworkMixin, SimpleTestCase):
    def test_the_invite_names_the_application_and_the_server(self):
        url = urlparse(discord_api.invite_url(7))
        params = parse_qs(url.query)

        self.assertEqual(f'{url.scheme}://{url.netloc}{url.path}',
                         discord_api.DISCORD_AUTHORIZE_URL)
        self.assertEqual(params['client_id'], ['cid'])
        self.assertEqual(params['scope'], [discord_api.BOT_SCOPES])
        self.assertEqual(params['permissions'],
                         [str(discord_api.BOT_PERMISSIONS)])
        self.assertEqual(params['guild_id'], ['7'])
        self.assertEqual(params['disable_guild_select'], ['true'])

    def test_the_permissions_cover_the_board(self):
        for bit in (discord_api.VIEW_CHANNELS,
                    discord_api.SEND_MESSAGES,
                    discord_api.EMBED_LINKS,
                    discord_api.READ_MESSAGE_HISTORY,
                    discord_api.SEND_MESSAGES_IN_THREADS):
            with self.subTest(bit=bit):
                self.assertTrue(discord_api.BOT_PERMISSIONS & bit)

    @override_settings(DISCORD_CLIENT_ID=None)
    def test_an_unconfigured_application_has_no_invite(self):
        self.assertEqual(discord_api.invite_url(7), '')

    def test_management_is_read_from_the_session_permissions(self):
        self.assertTrue(discord_api.manages_guild(
            {'permissions': discord_api.MANAGE_GUILD}))
        self.assertFalse(discord_api.manages_guild({'permissions': 0}))
        self.assertFalse(discord_api.manages_guild({}))

