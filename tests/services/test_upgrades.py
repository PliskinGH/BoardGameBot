"""Tests for moving a match to a new rules version."""

from unittest import mock

from django.test import TestCase

from games.engine.base import Setup
from games.engine.card_sample.definition import CardSampleGame
from games.models import MatchStatus
from core import permissions
from games.services import actions, matches, undo, upgrades
from games.services.errors import (NotHost, RulesUpgradeUnavailable,
                                   StaleRules,
                                   UndoForbidden)
from tests.factories import (make_guild, make_player, play_first,
                             started_match)


class UpgradableCardSampleGame(CardSampleGame):
    version = 2

    def upgrade(self, from_version, state, hidden, private, seats, options,
                seed):
        return Setup(state={**state, 'upgraded': True}, hidden=hidden,
                     private=private)


class UpgradeTests(TestCase):
    def setUp(self):
        self.match, self.players = started_match()

    def test_an_action_under_other_rules_is_refused(self):
        self.match.rules_version = 0
        self.match.save(update_fields=['rules_version'])
        with self.assertRaises(StaleRules):
            play_first(self.match, self.players[0])

    def test_a_match_before_start_is_rebuilt(self):
        host = make_player('host')
        match = matches.create_match(guild=make_guild(), channel_id=3,
                                     slug='card-sample-game', player=host, seed=9)
        match.rules_version = 0
        match.state = {'tampered': True}
        match.save(update_fields=['rules_version', 'state'])
        match = upgrades.upgrade_match(match.pk, host)
        self.assertEqual(match.rules_version, CardSampleGame.version)
        self.assertNotIn('tampered', match.state)
        self.assertEqual(match.actions.get(seq=match.version).type,
                         'rules_upgrade')

    def test_an_in_flight_match_needs_an_upgradable_definition(self):
        match = play_first(self.match, self.players[0])
        match.rules_version = 0
        match.save(update_fields=['rules_version'])
        with self.assertRaises(RulesUpgradeUnavailable):
            upgrades.upgrade_match(match.pk, self.players[0])

    def test_an_upgradable_definition_can_migrate_the_state(self):
        match = play_first(self.match, self.players[0])
        match.rules_version = 0
        match.save(update_fields=['rules_version'])
        with mock.patch('games.services.upgrades.definition_for',
                        return_value=UpgradableCardSampleGame()):
            match = upgrades.upgrade_match(match.pk, self.players[0])
        self.assertEqual(match.rules_version, 2)
        self.assertTrue(match.state['upgraded'])
        record = match.actions.get(seq=match.version)
        self.assertEqual(record.payload, {'from': 0, 'to': 2})

    def test_a_guest_cannot_upgrade(self):
        self.match.rules_version = 0
        self.match.save(update_fields=['rules_version'])

        with self.assertRaises(NotHost):
            upgrades.upgrade_match(self.match.pk, self.players[1])

    def test_a_server_manager_can_upgrade(self):
        host = make_player('host')
        guild = make_guild()
        match = matches.create_match(guild=guild, channel_id=3, slug='card-sample-game',
                                     player=host, seed=9)
        match.rules_version = 0
        match.save(update_fields=['rules_version'])
        manager = make_player('manager')
        permissions.grant_manager(guild, manager)

        match = upgrades.upgrade_match(match.pk, manager)

        self.assertEqual(match.rules_version, CardSampleGame.version)

    def test_an_upgrade_cannot_be_undone(self):
        match = play_first(self.match, self.players[0])
        match.rules_version = 0
        match.save(update_fields=['rules_version'])
        with mock.patch('games.services.upgrades.definition_for',
                        return_value=UpgradableCardSampleGame()):
            match = upgrades.upgrade_match(match.pk, self.players[0])
        with self.assertRaises(UndoForbidden) as caught:
            undo.undo_last_action(match.pk, self.players[0], force=True)
        self.assertEqual(caught.exception.reason, 'upgrade')

    def test_open_choices_block_an_upgrade(self):
        seat = self.match.seats.get(position=0)
        seat.private_state = {
            **seat.private_state,
            'hand': [{'id': 'swap', 'label': 'Swap', 'value': 0},
                     *seat.private_state['hand']]}
        seat.save(update_fields=['private_state'])
        match = actions.apply_action(self.match.pk, self.players[0],
                                     'play_card', {'card': 'swap'})
        match.rules_version = 0
        match.save(update_fields=['rules_version'])
        with mock.patch('games.services.upgrades.definition_for',
                        return_value=UpgradableCardSampleGame()):
            with self.assertRaises(RulesUpgradeUnavailable):
                upgrades.upgrade_match(match.pk, self.players[0])

    def test_the_same_rules_need_no_upgrade(self):
        match = upgrades.upgrade_match(self.match.pk, self.players[0])
        self.assertEqual(match.rules_version, CardSampleGame.version)
        self.assertEqual(match.version, self.match.version)



