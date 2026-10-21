"""Tests for playing GridSampleGame through the services."""

from django.test import TestCase

from games.models import MatchStatus, OutboxMessage
from games.services import actions, undo, upgrades
from games.services.errors import (RulesUpgradeUnavailable, StaleRules,
                                   UndoForbidden)
from games.services.projections import render_model
from tests.factories import play_first, started_match


def option_for(match, player, action_id):
    """Return the rendered action of that id for the player."""
    return next(option for option in render_model(match, player).actions
                if option.id == action_id)


class GridSampleServiceTests(TestCase):
    def setUp(self):
        self.match, self.players = started_match(slug='grid-sample-game')

    def test_a_move_reveals_a_cell_and_can_be_forced_back(self):
        option = option_for(self.match, self.players[0], 'move')
        cell = option.params[0].options[0]

        match = actions.apply_action(self.match.pk, self.players[0], 'move',
                                     {'cell': cell}, self.match.version)

        self.assertIn(cell, match.state['contents'])
        with self.assertRaises(UndoForbidden) as caught:
            undo.undo_last_action(match.pk, self.players[0])
        self.assertEqual(caught.exception.reason, 'revealed')

        match = undo.undo_last_action(match.pk, self.players[0], force=True)
        self.assertEqual(match.position, 0)
        self.assertNotIn(cell, match.state['contents'])

    def test_a_scout_can_be_undone_without_force(self):
        option = option_for(self.match, self.players[0], 'scout')
        cell = option.params[0].options[0]

        match = actions.apply_action(self.match.pk, self.players[0], 'scout',
                                     {'cell': cell}, self.match.version)

        self.assertIn(cell, match.hidden_state['caches'])
        match = undo.undo_last_action(match.pk, self.players[0])
        self.assertNotIn(cell, match.hidden_state['caches'])

    def test_older_rules_refuse_an_action(self):
        self.match.rules_version = 0
        self.match.save(update_fields=['rules_version'])
        cell = option_for(self.match, self.players[0],
                          'move').params[0].options[0]

        with self.assertRaises(StaleRules):
            actions.apply_action(self.match.pk, self.players[0], 'move',
                                 {'cell': cell})

    def test_an_active_match_cannot_be_upgraded(self):
        self.match.rules_version = 0
        self.match.save(update_fields=['rules_version'])

        with self.assertRaises(RulesUpgradeUnavailable):
            upgrades.upgrade_match(self.match.pk, self.players[0])

    def test_the_game_ends_and_queues_a_recap(self):
        match = self.match
        for _ in range(100):
            if match.status == MatchStatus.FINISHED:
                break
            match = play_first(match, match.active_seat.player)
        else:
            self.fail('The grid game did not finish.')

        self.assertTrue(OutboxMessage.objects.filter(
            match=match, kind='match_over').exists())
