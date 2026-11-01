"""Tests for the reveal detection the undo policy relies on."""

from django.test import SimpleTestCase

from bgb_engine.base import Transition
from games.services.reveals import detect


class RevealTests(SimpleTestCase):
    def test_a_card_drawn_counts_as_a_reveal(self):
        before = {'state': {}, 'hidden_state': {'deck': ['c1', 'c2']},
                  'private': {'0': {'hand': []}}}
        transition = Transition(state={}, hidden={'deck': ['c2']},
                                private={0: {'hand': ['c1']}})
        self.assertTrue(detect(before, transition))

    def test_a_card_played_face_up_counts_as_a_reveal(self):
        before = {'state': {}, 'hidden_state': {},
                  'private': {'0': {'hand': ['c1']}}}
        transition = Transition(state={'discard': ['c1']},
                                private={0: {'hand': []}})
        self.assertTrue(detect(before, transition))

    def test_a_card_shown_from_the_deck_counts_as_a_reveal(self):
        before = {'state': {}, 'hidden_state': {'deck': ['c1']},
                  'private': {}}
        transition = Transition(state={'shown': ['c1']},
                                hidden={'deck': []})
        self.assertTrue(detect(before, transition))

    def test_a_silent_action_is_not_a_reveal(self):
        before = {'state': {'coins': [0, 0]}, 'hidden_state': {},
                  'private': {'0': {'hand': ['c1']},
                              '1': {'hand': ['c2']}}}
        transition = Transition(state={'coins': [0, 0]})
        self.assertFalse(detect(before, transition))

