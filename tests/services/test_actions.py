"""Tests for the action write path."""

from unittest import mock

from django.test import TestCase

from bgb_engine.base import IllegalAction
from games.models import Action, MatchStatus, OutboxMessage, PendingChoice
from games.services import actions, matches
from games.services.errors import MatchClosed, NotASeat, StaleMatch
from tests.factories import make_guild, make_player, play_first, started_match


class ApplyActionTests(TestCase):
    def setUp(self):
        self.match, self.players = started_match()

    def hand(self, position=0):
        return self.match.seats.get(
            position=position).private_state['hand']

    def test_an_action_bumps_the_version_and_stores_everything(self):
        match = self.match
        before_state = match.state
        deck_before = len(match.hidden_state['deck'])
        card = next(row for row in self.hand() if row['value'] > 0)
        actions.apply_action(match.pk, self.players[0], 'play_card',
                             {'card': card['id']})
        match.refresh_from_db()
        self.assertEqual(match.version, 1)
        self.assertEqual(match.position, 1)
        record = match.actions.get(seq=1)
        self.assertEqual(record.type, 'play_card')
        self.assertTrue(record.revealed)
        self.assertFalse(record.random)
        self.assertEqual(record.snapshot.data['position'], 0)
        self.assertEqual(record.snapshot.data['state'], before_state)
        hand = match.seats.get(position=0).private_state['hand']
        self.assertNotIn(card['id'], [row['id'] for row in hand])
        self.assertEqual(len(match.hidden_state['deck']), deck_before - 1)
        self.assertTrue(OutboxMessage.objects.filter(
            match=match, kind='board_update').exists())

    def test_a_stale_version_is_refused(self):
        card = self.hand()[0]
        with self.assertRaises(StaleMatch):
            actions.apply_action(self.match.pk, self.players[0], 'play_card',
                                 {'card': card['id']}, expected_version=99)
        self.assertEqual(Action.objects.filter(match=self.match).count(), 0)

    def test_an_actor_without_a_seat_is_refused(self):
        outsider = make_player('outsider')
        with self.assertRaises(NotASeat):
            actions.apply_action(self.match.pk, outsider, 'play_card',
                                 {'card': self.hand()[0]['id']})
        self.assertEqual(Action.objects.filter(match=self.match).count(), 0)

    def test_an_illegal_action_changes_nothing(self):
        with self.assertRaises(IllegalAction):
            actions.apply_action(self.match.pk, self.players[0], 'fly')
        self.match.refresh_from_db()
        self.assertEqual(self.match.version, 0)
        self.assertEqual(Action.objects.filter(match=self.match).count(), 0)

    def test_a_match_that_has_not_started_refuses_actions(self):
        guild = make_guild(discord_id=2, name='Other')
        match = matches.create_match(guild=guild, channel_id=2, slug='card-sample-game',
                                     player=self.players[0], seed=3)
        with self.assertRaises(MatchClosed):
            actions.apply_action(match.pk, self.players[0], 'pass')

    def test_a_pending_choice_is_opened_and_answered(self):
        seat = self.match.seats.get(position=0)
        seat.private_state = {
            **seat.private_state,
            'hand': [{'id': 'swap', 'label': 'Swap', 'value': 0},
                     *seat.private_state['hand']]}
        seat.save(update_fields=['private_state'])
        actions.apply_action(self.match.pk, self.players[0], 'play_card',
                             {'card': 'swap'})
        choice = PendingChoice.objects.get(match=self.match,
                                           resolved_at__isnull=True)
        self.assertEqual(choice.kind, 'swap_target')
        self.assertEqual(choice.seat.position, 0)
        self.assertTrue(choice.label)
        actions.apply_action(self.match.pk, self.players[0], 'resolve_choice',
                             {'target': 1})
        choice.refresh_from_db()
        self.assertIsNotNone(choice.resolved_at)
        self.assertEqual(choice.response['action'], 'resolve_choice')

    def test_the_notifier_runs_once_per_committed_action(self):
        card = next(row for row in self.hand() if row['value'] > 0)
        with mock.patch('games.services.actions.notifier.game_changed') as changed:
            with self.captureOnCommitCallbacks(execute=True):
                actions.apply_action(self.match.pk, self.players[0],
                                     'play_card', {'card': card['id']})
        changed.assert_called_once_with(self.match.pk, 1)

    def test_a_failed_write_leaves_no_trace(self):
        card = self.hand()[0]
        with mock.patch('games.services.actions.enqueue',
                        side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                with self.captureOnCommitCallbacks(execute=True) as callbacks:
                    actions.apply_action(self.match.pk, self.players[0],
                                         'play_card', {'card': card['id']})
        self.assertEqual(callbacks, [])
        self.match.refresh_from_db()
        self.assertEqual(self.match.version, 0)
        self.assertEqual(Action.objects.filter(match=self.match).count(), 0)

    def test_a_full_match_finishes(self):
        match = self.match
        for _ in range(200):
            if match.status == MatchStatus.FINISHED:
                break
            match = play_first(match, match.active_seat.player)
        else:
            self.fail('The match did not finish.')
        self.assertIsNone(match.active_seat_id)
        self.assertTrue(match.outbox.filter(kind='match_over').exists())
