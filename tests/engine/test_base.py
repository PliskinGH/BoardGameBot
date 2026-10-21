"""Tests for the engine's plain-value contract."""

import json
from dataclasses import asdict

from django.test import SimpleTestCase

from games.engine.base import (Action, ActionOption, IllegalAction, LogEntry,
                               OutboxItem, Param, PendingRef, PendingSpec,
                               RenderModel, Setup, Transition)


class ContractTests(SimpleTestCase):
    def test_an_illegal_action_is_an_exception(self):
        self.assertTrue(issubclass(IllegalAction, Exception))

    def test_a_transition_defaults_to_no_patches(self):
        transition = Transition(state={})
        self.assertEqual(transition.hidden, {})
        self.assertEqual(transition.private, {})
        self.assertEqual(transition.pending, ())
        self.assertFalse(transition.over)

    def test_an_action_carries_its_parameters(self):
        action = Action(actor=1, id='play_card', params={'card': 'c01'})
        self.assertEqual(action.params['card'], 'c01')

    def test_a_pending_spec_can_close_a_choice(self):
        spec = PendingSpec(seat=2, kind='pick', close=True)
        self.assertTrue(spec.close)
        self.assertEqual(PendingRef(seat=2, kind='pick').options, ())

    def test_the_log_and_outbox_items_are_plain_values(self):
        payload = json.dumps({'log': [asdict(LogEntry(text='hello'))],
                              'outbox': [asdict(OutboxItem(kind='match_over',
                                                          payload={'a': 1}))]})
        self.assertIn('match_over', payload)

    def test_a_render_model_is_json_serializable(self):
        model = RenderModel(
            actions=(ActionOption(
                id='pass', label='Pass',
                params=(Param('seat', 'Seat', kind='seat', options=(1, 2)),)),),
            status='P1 to act.')
        payload = json.dumps(asdict(model))
        self.assertIn('pass', payload)
        self.assertIn('P1 to act.', payload)

    def test_a_setup_round_trips_through_json(self):
        setup = Setup(state={'deck_count': 2}, hidden={'deck': [1, 2]},
                      private={0: {'hand': []}})
        self.assertEqual(json.loads(json.dumps(asdict(setup))),
                         {'state': {'deck_count': 2},
                          'hidden': {'deck': [1, 2]},
                          'private': {'0': {'hand': []}}})
