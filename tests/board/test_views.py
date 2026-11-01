"""Tests for the read-only match page and its polling fragment."""

from unittest import mock

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from board import queries
from core import discord_api, permissions
from games.services import actions, matches
from tests.factories import (make_guild, make_player, play_first,
                             started_match)


def match_url(match):
    """Return the page of ``match``."""
    return reverse('board:match', args=[match.guild.discord_id, match.pk])


def state_url(match):
    """Return the polling fragment of ``match``."""
    return reverse('board:match_state',
                   args=[match.guild.discord_id, match.pk])


def mark_hand(match, position, label):
    """Give a seat a card with a label no other view may show."""
    seat = match.seats.get(position=position)
    seat.private_state = {
        **seat.private_state,
        'hand': [{'id': f'sentinel-{position}', 'label': label, 'value': 1},
                 *seat.private_state['hand']],
    }
    seat.save(update_fields=['private_state'])


class MatchAccessTests(TestCase):
    def setUp(self):
        self.match, self.players = started_match()

    def test_a_visitor_is_sent_to_login(self):
        url = match_url(self.match)

        response = self.client.get(url)

        self.assertRedirects(response,
                             f'{reverse("core:login")}?next={url}')

    def test_a_poll_by_a_visitor_is_refused(self):
        response = self.client.get(state_url(self.match))

        self.assertEqual(response.status_code, 403)

    def test_a_public_server_shows_its_match_to_a_visitor(self):
        self.match.guild.public_display = True
        self.match.guild.save(update_fields=['public_display'])

        response = self.client.get(match_url(self.match))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Public view')

    def test_a_public_server_answers_a_visitor_poll(self):
        self.match.guild.public_display = True
        self.match.guild.save(update_fields=['public_display'])

        response = self.client.get(state_url(self.match))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-version="{self.match.version}"')

    def test_a_public_server_answers_an_up_to_date_visitor(self):
        self.match.guild.public_display = True
        self.match.guild.save(update_fields=['public_display'])

        response = self.client.get(state_url(self.match),
                                   {'since': self.match.version})

        self.assertEqual(response.status_code, 204)

    def test_a_visitor_never_sees_a_hand(self):
        mark_hand(self.match, 0, 'ZEBRA')
        mark_hand(self.match, 1, 'UNICORN')
        self.match.guild.public_display = True
        self.match.guild.save(update_fields=['public_display'])

        page = self.client.get(match_url(self.match))
        fragment = self.client.get(state_url(self.match))

        self.assertNotContains(page, 'ZEBRA')
        self.assertNotContains(page, 'UNICORN')
        self.assertNotContains(fragment, 'ZEBRA')
        self.assertNotContains(fragment, 'UNICORN')

    def test_another_servers_match_is_not_found(self):
        self.client.force_login(self.players[0])
        url = reverse('board:match',
                      args=[self.match.guild.discord_id + 1, self.match.pk])

        self.assertEqual(self.client.get(url).status_code, 404)

    def test_an_unknown_match_is_not_found(self):
        self.client.force_login(self.players[0])
        url = reverse('board:match',
                      args=[self.match.guild.discord_id, self.match.pk + 1])

        self.assertEqual(self.client.get(url).status_code, 404)

    def test_no_post_endpoint_exists(self):
        self.client.force_login(self.players[0])

        self.assertEqual(self.client.post(match_url(self.match)).status_code,
                         405)
        self.assertEqual(self.client.post(state_url(self.match)).status_code,
                         405)


class MatchPageTests(TestCase):
    def setUp(self):
        self.match, self.players = started_match()
        self.spectator = make_player('spectator')
        self.client.force_login(self.players[0])

    def test_the_page_shows_the_status_and_the_seats(self):
        response = self.client.get(match_url(self.match))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, response.context['model'].status)
        self.assertContains(
            response,
            f'<title>{response.context["match_title"]} | BoardGameBot</title>')
        self.assertContains(response, self.players[0].display_name)
        self.assertContains(response, self.players[1].display_name)

    def test_the_page_uses_server_display_names(self):
        seat = self.match.seats.get(position=0)
        seat.display_name = 'Wendy on this server'
        seat.save(update_fields=['display_name'])

        response = self.client.get(match_url(self.match))

        self.assertContains(response, 'Wendy on this server')

    def test_the_page_lists_the_action_log(self):
        match = play_first(self.match, self.players[0])
        text = match.actions.get(seq=1).result['log'][0]['text']

        self.assertContains(self.client.get(match_url(self.match)), text)

    def test_the_page_shows_a_named_match(self):
        self.match.name = 'Friday table'
        self.match.save(update_fields=['name'])

        response = self.client.get(match_url(self.match))

        self.assertContains(response, 'Friday table')
        self.assertContains(
            response,
            f'<title>Card Sample Game: Friday table '
            f'(#{self.match.pk}) | BoardGameBot</title>')

    def test_the_page_shows_final_standings(self):
        matches.close_match(self.match.pk, self.players[0])

        response = self.client.get(match_url(self.match))

        self.assertContains(response, 'Final standings')
        self.assertContains(response, self.players[0].display_name)
        self.assertContains(response, 'Coins')

    def test_the_web_log_limit_is_a_constant(self):
        match = play_first(self.match, self.players[0])
        play_first(match, match.active_seat.player)

        with mock.patch.object(queries, 'WEB_LIMIT', 1):
            response = self.client.get(match_url(match))

        self.assertEqual(len(response.context['log']), 1)

    def test_the_page_does_not_use_em_dashes_or_dots(self):
        response = self.client.get(match_url(self.match))

        self.assertNotContains(response, '—')
        self.assertNotContains(response, '·')

    def test_a_match_in_setup_waits_for_players(self):
        waiting = matches.create_match(
            guild=make_guild(), channel_id=1, slug='card-sample-game',
            player=self.players[0], options={'deck_rounds': 1})

        response = self.client.get(match_url(waiting))

        self.assertContains(response, 'Waiting for players')
        self.assertContains(response, 'Open')

    def test_a_seat_sees_only_its_own_hand(self):
        mark_hand(self.match, 0, 'ZEBRA')
        mark_hand(self.match, 1, 'UNICORN')

        own = self.client.get(match_url(self.match))
        self.assertContains(own, 'ZEBRA')
        self.assertNotContains(own, 'UNICORN')

        self.client.force_login(self.players[1])
        other = self.client.get(match_url(self.match))
        self.assertContains(other, 'UNICORN')
        self.assertNotContains(other, 'ZEBRA')

    def test_a_spectator_sees_no_hand(self):
        mark_hand(self.match, 0, 'ZEBRA')

        self.client.force_login(self.spectator)
        response = self.client.get(match_url(self.match))

        self.assertNotContains(response, 'ZEBRA')
        self.assertNotIn('hand',
                         [zone.kind
                          for zone in response.context['model'].zones])

    def test_a_pending_choice_is_shown_to_its_seat(self):
        seat = self.match.seats.get(position=0)
        seat.private_state = {
            **seat.private_state,
            'hand': [{'id': 'swap', 'label': 'Swap', 'value': 0},
                     *seat.private_state['hand']],
        }
        seat.save(update_fields=['private_state'])
        actions.apply_action(self.match.pk, self.players[0], 'play_card',
                             {'card': 'swap'})

        response = self.client.get(match_url(self.match))
        self.assertContains(response, 'Swap counters with which seat?')

        self.client.force_login(self.players[1])
        other = self.client.get(match_url(self.match))
        self.assertNotContains(other, 'Swap counters with which seat?')


class GridBoardTests(TestCase):
    def test_a_grid_match_renders_its_board(self):
        match, players = started_match(slug='grid-sample-game')
        self.client.force_login(players[0])

        response = self.client.get(match_url(match))

        self.assertContains(response, 'board-grid')
        self.assertContains(response, 'kind-hidden')
        self.assertContains(response, 'Grid Sample Game')

    def test_a_card_match_has_no_grid(self):
        match, players = started_match()
        self.client.force_login(players[0])

        response = self.client.get(match_url(match))

        self.assertNotContains(response, 'board-grid')


class GraphBoardTests(TestCase):
    def test_a_graph_match_renders_its_board(self):
        match, players = started_match(slug='graph-sample-game')
        self.client.force_login(players[0])

        response = self.client.get(match_url(match))

        self.assertContains(response, 'board-graph')
        self.assertContains(response, 'Graph Sample Game')
        self.assertNotContains(response, 'board-grid')


class MatchStateTests(TestCase):
    def setUp(self):
        self.match, self.players = started_match()
        self.spectator = make_player('spectator')
        self.client.force_login(self.players[0])

    def test_a_poll_with_no_change_answers_204(self):
        response = self.client.get(state_url(self.match),
                                   {'since': self.match.version})

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response['X-Match-Version'],
                         str(self.match.version))

    def test_a_poll_after_an_action_carries_the_new_version(self):
        match = play_first(self.match, self.players[0])

        response = self.client.get(state_url(self.match),
                                   {'since': self.match.version})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-version="{match.version}"')
        self.assertContains(response, 'data-state-url')
        self.assertContains(response, f'value="{match.version}"')

    def test_a_poll_without_a_version_renders(self):
        self.assertEqual(
            self.client.get(state_url(self.match)).status_code, 200)

    def test_a_poll_with_a_garbled_version_renders(self):
        response = self.client.get(state_url(self.match), {'since': 'soon'})

        self.assertEqual(response.status_code, 200)

    def test_the_fragment_keeps_the_other_hands_out(self):
        mark_hand(self.match, 0, 'ZEBRA')
        mark_hand(self.match, 1, 'UNICORN')

        own = self.client.get(state_url(self.match))
        self.assertContains(own, 'ZEBRA')
        self.assertNotContains(own, 'UNICORN')

        self.client.force_login(self.players[1])
        other = self.client.get(state_url(self.match))
        self.assertContains(other, 'UNICORN')
        self.assertNotContains(other, 'ZEBRA')

    def test_a_spectator_fragment_has_no_hand(self):
        mark_hand(self.match, 0, 'ZEBRA')

        self.client.force_login(self.spectator)
        response = self.client.get(state_url(self.match))

        self.assertNotContains(response, 'ZEBRA')
        self.assertNotIn('hand',
                         [zone.kind
                          for zone in response.context['model'].zones])

    def test_a_poll_during_setup_always_renders(self):
        guild = make_guild()
        waiting = matches.create_match(
            guild=guild, channel_id=1, slug='card-sample-game',
            player=self.players[0], options={'deck_rounds': 1})
        self.client.force_login(self.players[0])
        url = reverse('board:match_state',
                      args=[guild.discord_id, waiting.pk])

        response = self.client.get(url, {'since': waiting.version})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Waiting for players')
        self.assertNotContains(response, 'id="state-since"')


class QueryCostTests(TestCase):
    def test_the_page_cost_does_not_grow_with_the_seats(self):
        self.assertEqual(self._page_queries(2), self._page_queries(4))

    def _page_queries(self, players):
        match, people = started_match(players=players)
        self.client.force_login(people[0])
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(match_url(match))
        self.assertEqual(response.status_code, 200)
        return len(captured)



class IndexServerTests(TestCase):
    def setUp(self):
        self.guild = make_guild(discord_id=11, name='Alpha')
        self.player = make_player('webuser')
        self.client.force_login(self.player)

    def _session(self, guilds):
        session = self.client.session
        session[discord_api.GUILDS_SESSION_KEY] = guilds
        session.save()

    @override_settings(DISCORD_CLIENT_ID='client-id')
    def test_a_managed_server_gets_an_invite(self):
        self._session([{'id': 11, 'name': 'Alpha',
                        'permissions': discord_api.MANAGE_GUILD}])

        response = self.client.get(reverse('board:index'))

        self.assertContains(response, 'Alpha')
        self.assertContains(response, 'Invite the bot')
        self.assertContains(response, 'guild_id=11')
        self.assertContains(response, str(discord_api.BOT_PERMISSIONS))

    def test_a_server_the_player_does_not_manage_gets_none(self):
        self._session([{'id': 12, 'name': 'Beta', 'permissions': 0}])

        response = self.client.get(reverse('board:index'))

        self.assertNotContains(response, 'guild_id=12')
        self.assertNotContains(response, 'Beta')
        self.assertContains(response, 'You manage no server')

    def test_a_server_the_bot_uses_is_marked(self):
        self._session([{'id': 11, 'name': 'Alpha',
                        'permissions': discord_api.MANAGE_GUILD}])

        response = self.client.get(reverse('board:index'))

        self.assertContains(response, 'Bot added')

    def test_an_old_session_is_told_to_log_in_again(self):
        self._session([])

        response = self.client.get(reverse('board:index'))

        self.assertContains(response, 'Log out and back in')

    @override_settings(DISCORD_CLIENT_ID=None)
    def test_an_unconfigured_bot_shows_no_invite(self):
        self._session([{'id': 11, 'name': 'Alpha',
                        'permissions': discord_api.MANAGE_GUILD}])

        response = self.client.get(reverse('board:index'))

        self.assertNotContains(response, 'oauth2/authorize')
        self.assertContains(response, 'Alpha')

    def test_a_match_row_uses_the_game_name(self):
        matches.create_match(guild=self.guild, channel_id=1,
                             slug='card-sample-game', player=self.player,
                             options={'deck_rounds': 1})

        response = self.client.get(reverse('board:index'))

        self.assertContains(response, 'Card Sample Game')
        self.assertNotContains(response, 'card-sample-game #')

    def test_a_guardian_manager_sees_the_server(self):
        permissions.grant_manager(self.guild, self.player)

        response = self.client.get(reverse('board:index'))

        self.assertContains(response, 'Alpha')
        self.assertContains(response, 'Bot added')
        self.assertNotContains(response, 'Log out and back in')

    def test_a_guardian_manager_does_not_see_another_server(self):
        other = make_guild(discord_id=12, name='Beta')
        permissions.grant_manager(other, self.player)

        response = self.client.get(reverse('board:index'))

        self.assertContains(response, 'Beta')
        self.assertNotContains(response, 'Alpha')

    def test_the_same_server_is_listed_once(self):
        self._session([{'id': 11, 'name': 'Alpha',
                        'permissions': discord_api.MANAGE_GUILD}])
        permissions.grant_manager(self.guild, self.player)

        content = self.client.get(reverse('board:index')).content.decode()

        self.assertEqual(content.count('Alpha'), 1)

    def test_a_superuser_sees_every_known_server(self):
        make_guild(discord_id=12, name='Beta')
        self.player.is_superuser = True
        self.player.save(update_fields=['is_superuser'])

        response = self.client.get(reverse('board:index'))

        self.assertContains(response, 'Alpha')
        self.assertContains(response, 'Beta')

    def test_the_servers_are_sorted_by_name(self):
        self._session([
            {'id': 11, 'name': 'Zulu',
             'permissions': discord_api.MANAGE_GUILD},
            {'id': 12, 'name': 'alpha',
             'permissions': discord_api.MANAGE_GUILD}])

        content = self.client.get(reverse('board:index')).content.decode()

        self.assertLess(content.index('alpha'), content.index('Zulu'))

