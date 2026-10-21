"""Tests for undoing actions and rewinding to a step."""

from unittest import mock

from django.test import TestCase

from games.models import (Action, MatchStatus, OutboxMessage, OutboxStatus,
                          UndoPolicy)
from core import permissions
from games.services import actions, undo
from games.services.errors import (NotHost, NothingToUndo, NotYourAction,
                                   RewindTooLong,
                                   StaleMatch, UndoForbidden, UnknownStep)
from tests.factories import play_first, started_match


class UndoTests(TestCase):
    def setUp(self):
        self.match, self.players = started_match()

    def test_undoing_a_reveal_needs_permission(self):
        match = play_first(self.match, self.players[0])
        with self.assertRaises(UndoForbidden) as caught:
            undo.undo_last_action(match.pk, self.players[0])
        self.assertEqual(caught.exception.reason, 'revealed')
        match.refresh_from_db()
        self.assertEqual(match.version, 1)

    def test_a_forced_undo_restores_the_state(self):
        before_state = self.match.state
        match = play_first(self.match, self.players[0])
        match = undo.undo_last_action(match.pk, self.players[0], force=True)
        self.assertEqual(match.version, 2)
        self.assertEqual(match.position, 0)
        self.assertEqual(match.state, before_state)
        record = match.actions.get(seq=2)
        self.assertEqual(record.type, 'undo')
        self.assertEqual(record.payload, {'undoes': 1})

    def test_a_pass_can_be_undone_without_permission(self):
        seat = self.match.seats.get(position=0)
        seat.private_state = {**seat.private_state, 'hand': []}
        seat.save(update_fields=['private_state'])
        match = play_first(self.match, self.players[0])
        self.assertEqual(match.actions.get(seq=1).type, 'pass')
        match = undo.undo_last_action(match.pk, self.players[0])
        self.assertEqual(match.position, 0)

    def test_a_random_action_needs_permission(self):
        match = play_first(self.match, self.players[0])
        match.actions.filter(seq=1).update(revealed=False, random=True)
        with self.assertRaises(UndoForbidden) as caught:
            undo.undo_last_action(match.pk, self.players[0])
        self.assertEqual(caught.exception.reason, 'random')

    def test_another_players_action_cannot_be_undone(self):
        match = play_first(self.match, self.players[0])
        with self.assertRaises(NotYourAction):
            undo.undo_last_action(match.pk, self.players[1])

    def test_a_guest_cannot_force_an_undo(self):
        match = play_first(self.match, self.players[0])

        with self.assertRaises(NotHost):
            undo.undo_last_action(match.pk, self.players[1], force=True)

    def test_a_forced_undo_records_its_reason(self):
        match = play_first(self.match, self.players[0])

        match = undo.undo_last_action(match.pk, self.players[0], force=True,
                                      reason='oops')

        self.assertEqual(match.actions.get(seq=2).result,
                         {'forced': True, 'reason': 'oops'})

    def test_a_server_manager_can_force_an_undo(self):
        permissions.grant_manager(self.match.guild, self.players[1])
        match = play_first(self.match, self.players[0])

        match = undo.undo_last_action(match.pk, self.players[1], force=True,
                                      reason='a manager fixed it')

        self.assertEqual(match.actions.get(seq=2).result,
                         {'forced': True, 'reason': 'a manager fixed it'})

    def test_a_match_without_actions_has_nothing_to_undo(self):
        with self.assertRaises(NothingToUndo):
            undo.undo_last_action(self.match.pk, self.players[0])

    def test_an_undo_cannot_pass_the_setup(self):
        match = play_first(self.match, self.players[0])
        match = undo.undo_last_action(match.pk, self.players[0], force=True)
        with self.assertRaises(NothingToUndo):
            undo.undo_last_action(match.pk, self.players[0], force=True)

    def test_the_all_policy_lets_a_player_undo_a_reveal(self):
        match, players = started_match(undo_policy=UndoPolicy.ALL)
        match = play_first(match, players[0])
        match = undo.undo_last_action(match.pk, players[0])
        self.assertEqual(match.position, 0)

    def test_a_stale_version_is_refused(self):
        match = play_first(self.match, self.players[0])
        with self.assertRaises(StaleMatch):
            undo.undo_last_action(match.pk, self.players[0],
                                  expected_version=0, force=True)

    def test_undoing_the_answer_reopens_the_choice(self):
        seat = self.match.seats.get(position=0)
        seat.private_state = {
            **seat.private_state,
            'hand': [{'id': 'swap', 'label': 'Swap', 'value': 0},
                     *seat.private_state['hand']]}
        seat.save(update_fields=['private_state'])
        match = actions.apply_action(self.match.pk, self.players[0],
                                     'play_card', {'card': 'swap'})
        self.assertEqual(match.pending_choices.filter(
            resolved_at__isnull=True).count(), 1)
        match = actions.apply_action(self.match.pk, self.players[0],
                                     'resolve_choice', {'target': 1})
        self.assertEqual(match.pending_choices.filter(
            resolved_at__isnull=True).count(), 0)
        match = undo.undo_last_action(match.pk, self.players[0], force=True)
        self.assertEqual(match.pending_choices.filter(
            resolved_at__isnull=True).count(), 1)

    def test_an_undo_supersedes_queued_messages(self):
        match = play_first(self.match, self.players[0])
        queued = OutboxMessage.objects.filter(
            match=match, status=OutboxStatus.PENDING).count()
        self.assertGreaterEqual(queued, 1)
        match = undo.undo_last_action(match.pk, self.players[0], force=True)
        self.assertEqual(OutboxMessage.objects.filter(
            match=match, status=OutboxStatus.SUPERSEDED).count(), queued)
        self.assertTrue(OutboxMessage.objects.filter(
            match=match, status=OutboxStatus.PENDING).exists())

    def test_undoing_after_the_end_reopens_the_match(self):
        match = self.match
        for _ in range(200):
            if match.status == MatchStatus.FINISHED:
                break
            match = play_first(match, match.active_seat.player)
        else:
            self.fail('The match did not finish.')
        match = undo.undo_last_action(match.pk, self.players[0], force=True)
        self.assertEqual(match.status, MatchStatus.ACTIVE)
        self.assertIsNone(match.finished_at)
        self.assertIsNotNone(match.active_seat_id)


class RewindTests(TestCase):
    def setUp(self):
        self.match, self.players = started_match()

    def take_turns(self, count):
        match = self.match
        for _ in range(count):
            match = play_first(match, match.active_seat.player)
        return match

    def test_rewinding_restores_an_earlier_step(self):
        match = self.take_turns(3)
        expected = Action.objects.get(match=match, seq=2).snapshot.data
        match = undo.rewind_to(match.pk, 1, self.players[0], force=True)
        self.assertEqual(match.position, 1)
        self.assertEqual(match.version, 5)
        self.assertEqual(match.state, expected['state'])
        self.assertEqual(match.hidden_state, expected['hidden_state'])
        self.assertEqual(match.seats.get(position=0).private_state,
                         expected['private']['0'])
        self.assertEqual(match.actions.count(), 5)

    def test_a_forced_rewind_records_every_step(self):
        match = self.take_turns(2)

        match = undo.rewind_to(match.pk, 0, self.players[0], force=True,
                               reason='mistake')

        results = [action.result for action in
                   match.actions.filter(type='undo').order_by('seq')]
        self.assertEqual(results, [{'forced': True, 'reason': 'mistake'},
                                   {'forced': True, 'reason': 'mistake'}])

    def test_a_guest_cannot_force_a_rewind(self):
        match = self.take_turns(1)

        with self.assertRaises(NotHost):
            undo.rewind_to(match.pk, 0, self.players[1], force=True)

    def test_rewinding_refuses_a_blocked_step(self):
        match = play_first(self.match, self.players[0])
        with self.assertRaises(UndoForbidden):
            undo.rewind_to(match.pk, 0, self.players[0])
        match.refresh_from_db()
        self.assertEqual(match.version, 1)
        self.assertFalse(match.actions.filter(type='undo').exists())

    def test_rewinding_refuses_another_players_action(self):
        match = self.take_turns(2)
        last = match.actions.order_by('-seq').first()
        other = next(seat.player for seat in match.seats.all()
                     if seat.player_id != last.actor_id)
        with self.assertRaises(NotYourAction):
            undo.rewind_to(match.pk, 0, other)
        self.assertEqual(match.actions.filter(type='undo').count(), 0)

    def test_rewinding_is_bounded(self):
        match = self.take_turns(3)
        with self.assertRaises(RewindTooLong):
            undo.rewind_to(match.pk, 0, self.players[0], force=True, limit=1)
        match.refresh_from_db()
        self.assertEqual(match.version, 3)

    def test_a_target_outside_the_log_is_refused(self):
        match = self.take_turns(1)
        with self.assertRaises(UnknownStep):
            undo.rewind_to(match.pk, 5, self.players[0], force=True)

    def test_rewinding_notifies_once(self):
        match = self.take_turns(2)
        with mock.patch('games.services.undo.notifier.game_changed') as changed:
            with self.captureOnCommitCallbacks(execute=True):
                undo.rewind_to(match.pk, 0, self.players[0], force=True)
        changed.assert_called_once_with(match.pk, 4)

