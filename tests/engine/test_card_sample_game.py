"""Tests for the sample game, played in memory."""

import json
from dataclasses import asdict

from django.test import SimpleTestCase

from bgb_engine.base import IllegalAction
from bgb_engine.examples.card_sample.definition import CardSampleGame
from tests.support import Table, seats


class CardSampleGameSetupTests(SimpleTestCase):
    def setUp(self):
        self.definition = CardSampleGame()

    def test_the_deal_is_reproducible_from_the_seed(self):
        first = self.definition.setup({}, seats(2), seed=11)
        second = self.definition.setup({}, seats(2), seed=11)
        other = self.definition.setup({}, seats(2), seed=12)
        self.assertEqual(first.state, second.state)
        self.assertEqual(first.hidden, second.hidden)
        self.assertEqual(first.private, second.private)
        self.assertNotEqual(first.private, other.private)

    def test_each_seat_is_dealt_the_starting_hand(self):
        setup = self.definition.setup({'starting_cards': 2}, seats(3), seed=3)
        lengths = [len(values['hand']) for values in setup.private.values()]
        self.assertEqual(lengths, [2, 2, 2])
        self.assertEqual(setup.state['deck_count'], 30)

    def test_an_invalid_setup_is_refused(self):
        with self.assertRaises(ValueError):
            self.definition.validate_setup({'starting_cards': 99}, seats(2))
        with self.assertRaises(ValueError):
            self.definition.validate_setup({}, seats(5))


class CardSampleGamePlayTests(SimpleTestCase):
    def setUp(self):
        self.definition = CardSampleGame()
        self.table = Table(self.definition, seats(2), seed=5)

    def test_playing_a_card_scores_its_value(self):
        hand = self.table.private[0]['hand']
        card = next(entry for entry in hand if entry['value'] > 0)
        self.table.apply('play_card', {'card': card['id']})
        self.assertEqual(self.table.state['counters']['coins'][0],
                         card['value'])
        self.assertEqual(self.table.active, 1)

    def test_a_played_card_leaves_the_hand_for_the_discard(self):
        card = self.table.private[0]['hand'][0]
        self.table.apply('play_card', {'card': card['id']})
        hand = [entry['id'] for entry in self.table.private[0]['hand']]
        discard = [entry['id'] for entry in self.table.state['discard']]
        self.assertNotIn(card['id'], hand)
        self.assertIn(card['id'], discard)

    def test_playing_out_of_turn_is_illegal(self):
        card = self.table.private[1]['hand'][0]
        with self.assertRaises(IllegalAction):
            self.table.apply('play_card', {'card': card['id']}, actor=1)

    def test_playing_a_card_that_is_not_in_hand_is_illegal(self):
        with self.assertRaises(IllegalAction):
            self.table.apply('play_card', {'card': 'nope'})

    def test_an_unknown_action_is_illegal(self):
        with self.assertRaises(IllegalAction):
            self.table.apply('fly')

    def test_a_seat_without_cards_can_only_pass(self):
        self.table.private[0]['hand'] = []
        self.table.state['deck_count'] = 0
        self.table.hidden['deck'] = []
        option = self.table.legal_actions()[0]
        self.assertEqual(option.id, 'pass')

    def test_the_swap_card_opens_a_choice_and_trades_counters(self):
        self.table.state['counters']['coins'] = [4, 1]
        self.table.private[0]['hand'] = [
            {'id': 'swap', 'label': 'Swap', 'value': 0},
            *self.table.private[0]['hand']]
        self.table.apply('play_card', {'card': 'swap'})
        self.assertEqual([choice.kind for choice in self.table.pending],
                         ['swap_target'])
        self.assertEqual(self.table.active, 0)
        option = self.table.legal_actions()[0]
        self.assertEqual(option.id, 'resolve_choice')
        self.table.apply('resolve_choice', {'target': 1})
        self.assertEqual(self.table.state['counters']['coins'], [1, 4])
        self.assertEqual(self.table.pending, ())
        self.assertEqual(self.table.active, 1)

    def test_a_full_game_finishes_with_every_card_scored(self):
        for _ in range(500):
            if self.table.over():
                break
            option = self.table.legal_actions()[0]
            if option.id == 'play_card':
                self.table.apply('play_card',
                                 {'card': option.params[0].options[0]})
            elif option.id == 'resolve_choice':
                self.table.apply('resolve_choice',
                                 {'target': option.params[0].options[0]})
            else:
                self.table.apply('pass')
        else:
            self.fail('The game did not finish in 500 turns.')

        self.assertTrue(self.table.over())
        scores = self.definition.scores(self.table.context())
        self.assertEqual(len(scores), 2)
        self.assertEqual(sum(row['coins'] for row in scores),
                         sum(card.value
                             for card in self.definition.deck(2)))


class CardSampleGameVisibilityTests(SimpleTestCase):
    def setUp(self):
        self.definition = CardSampleGame()
        self.table = Table(self.definition, seats(2), seed=9)

    def test_a_seat_view_never_shows_another_hand(self):
        opponent = self.table.private[1]['hand'][0]['id']
        own = self.table.private[0]['hand'][0]['id']
        view = self.definition.view(self.table.context(), 0)
        payload = json.dumps(asdict(view))
        self.assertNotIn(opponent, payload)
        self.assertIn(own, payload)

    def test_a_spectator_view_shows_no_hand(self):
        view = self.definition.view(self.table.context(), None)
        payload = json.dumps(asdict(view))
        hands = (self.table.private[0]['hand']
                 + self.table.private[1]['hand'])
        for card in hands:
            self.assertNotIn(card['id'], payload)

    def test_public_state_holds_neither_hands_nor_the_deck_order(self):
        payload = json.dumps(self.table.state)
        cards = (self.table.private[0]['hand']
                 + self.table.private[1]['hand']
                 + self.table.hidden['deck'])
        for card in cards:
            self.assertNotIn(card['id'], payload)

    def test_a_pending_choice_is_visible_to_its_seat_only(self):
        self.table.private[0]['hand'] = [
            {'id': 'swap', 'label': 'Swap', 'value': 0},
            *self.table.private[0]['hand']]
        self.table.apply('play_card', {'card': 'swap'})
        own = self.definition.view(self.table.context(), 0)
        other = self.definition.view(self.table.context(), 1)
        self.assertEqual(own.pending.kind, 'swap_target')
        self.assertIsNone(other.pending)
