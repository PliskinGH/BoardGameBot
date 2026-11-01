"""Tests for the engine primitives, none of which touch the database."""

from unittest import TestCase

from bgb_engine.base import PendingRef
from bgb_engine.primitives.counters import Counters
from bgb_engine.primitives.graph import BoardGraph
from bgb_engine.primitives.grid import BoardGrid
from bgb_engine.primitives.pending import for_seat, is_legal
from bgb_engine.primitives.phases import PhaseMachine
from bgb_engine.primitives.projection import hand_view
from bgb_engine.primitives.rng import rng_for
from bgb_engine.primitives.turn import TurnOrder
from bgb_engine.primitives.zones import (Card, extract, find, shuffled,
                                           take)


class RngTests(TestCase):
    def test_the_same_seed_draws_the_same_numbers(self):
        first, second = rng_for(3, 'deal'), rng_for(3, 'deal')
        self.assertEqual([first.random() for _ in range(3)],
                         [second.random() for _ in range(3)])

    def test_a_different_salt_draws_different_numbers(self):
        self.assertNotEqual(rng_for(3, 'deal').random(),
                            rng_for(3, 'other').random())


class PhaseTests(TestCase):
    def test_the_machine_walks_its_phases(self):
        machine = PhaseMachine(('play', 'finished'))
        self.assertEqual(machine.first, 'play')
        self.assertEqual(machine.next('play'), 'finished')
        self.assertIsNone(machine.next('finished'))
        self.assertTrue(machine.is_last('finished'))

    def test_a_machine_needs_unique_phases(self):
        with self.assertRaises(ValueError):
            PhaseMachine(())
        with self.assertRaises(ValueError):
            PhaseMachine(('play', 'play'))

    def test_an_unknown_phase_has_no_successor(self):
        with self.assertRaises(ValueError):
            PhaseMachine(('play',)).next('nope')


class ZoneTests(TestCase):
    def setUp(self):
        self.cards = [Card(id=f'c{index}', value=index) for index in range(6)]

    def test_shuffling_is_reproducible(self):
        self.assertEqual(shuffled(self.cards, seed=1),
                         shuffled(self.cards, seed=1))
        self.assertNotEqual(shuffled(self.cards, seed=1),
                            shuffled(self.cards, seed=2))

    def test_a_card_round_trips_through_a_dict(self):
        card = Card(id='c1', label='one', value=1)
        self.assertEqual(Card.from_dict(card.to_dict()), card)

    def test_taking_splits_the_pile(self):
        drawn, rest = take(self.cards, 2)
        self.assertEqual(len(drawn), 2)
        self.assertEqual(len(rest), 4)
        with self.assertRaises(ValueError):
            take(self.cards, -1)

    def test_finding_and_extracting_a_card(self):
        self.assertEqual(find(self.cards, 'c3'), self.cards[3])
        self.assertIsNone(find(self.cards, 'nope'))
        card, rest = extract(self.cards, 'c2')
        self.assertEqual(card.id, 'c2')
        self.assertNotIn(card, rest)
        with self.assertRaises(KeyError):
            extract(self.cards, 'nope')


class GraphTests(TestCase):
    def setUp(self):
        self.graph = BoardGraph(nodes=('a', 'b', 'c', 'd'),
                                edges=(('a', 'b'), ('b', 'c')))

    def test_neighbours_are_undirected(self):
        self.assertEqual(self.graph.neighbours('b'), ('a', 'c'))
        self.assertEqual(self.graph.neighbours('d'), ())

    def test_distance_counts_edges(self):
        self.assertEqual(self.graph.distance('a', 'c'), 2)
        self.assertEqual(self.graph.distance('a', 'a'), 0)
        self.assertIsNone(self.graph.distance('a', 'd'))
        self.assertFalse(self.graph.connected('a', 'd'))

    def test_an_unknown_node_is_refused(self):
        with self.assertRaises(ValueError):
            BoardGraph(nodes=('a',), edges=(('a', 'b'),))
        with self.assertRaises(ValueError):
            BoardGraph(nodes=('a', 'a'))


class GridTests(TestCase):
    def test_a_square_grid_has_four_neighbours(self):
        grid = BoardGrid(columns=3, rows=3)
        self.assertEqual(set(grid.neighbours(1, 1)),
                         {(0, 1), (2, 1), (1, 0), (1, 2)})
        self.assertEqual(grid.neighbours(0, 0), ((1, 0), (0, 1)))

    def test_a_hex_grid_has_six_neighbours(self):
        grid = BoardGrid(columns=5, rows=5, hexes=True)
        self.assertEqual(len(grid.neighbours(2, 2)), 6)
        self.assertEqual(len(grid.neighbours(2, 3)), 6)

    def test_edges_have_fewer_neighbours(self):
        grid = BoardGrid(columns=1, rows=1)
        self.assertEqual(grid.neighbours(0, 0), ())

    def test_a_grid_needs_cells(self):
        with self.assertRaises(ValueError):
            BoardGrid(columns=0, rows=1)


class CounterTests(TestCase):
    def setUp(self):
        self.counters = Counters({'coins': (1, 2)})

    def test_adding_and_taking_return_new_counters(self):
        raised = self.counters.with_add('coins', 0, 4)
        self.assertEqual(raised.get('coins', 0), 5)
        self.assertEqual(self.counters.get('coins', 0), 1)
        self.assertEqual(self.counters.with_take('coins', 0, 5).get('coins', 0),
                         0)

    def test_swapping_exchanges_two_seats(self):
        self.assertEqual(self.counters.with_swap('coins', 0, 1).values,
                         {'coins': (2, 1)})

    def test_a_negative_counter_is_refused(self):
        with self.assertRaises(ValueError):
            Counters({'coins': (-1,)})
        with self.assertRaises(ValueError):
            self.counters.with_add('coins', 0, -1)
        with self.assertRaises(ValueError):
            self.counters.with_take('coins', 0, -1)

    def test_counters_round_trip_through_a_dict(self):
        self.assertEqual(Counters.from_dict(self.counters.as_dict()),
                         self.counters)

    def test_an_unknown_counter_is_refused(self):
        with self.assertRaises(KeyError):
            self.counters.get('gems', 0)


class TurnTests(TestCase):
    def test_turns_wrap_around(self):
        self.assertEqual(TurnOrder((1, 2, 3)).after(3), 1)

    def test_skipped_seats_are_passed_over(self):
        order = TurnOrder((0, 1, 2))
        self.assertEqual(order.after(0, frozenset({1})), 2)
        with self.assertRaises(ValueError):
            order.after(0, frozenset({0, 1, 2}))

    def test_a_seat_outside_the_order_is_refused(self):
        with self.assertRaises(ValueError):
            TurnOrder((0, 1)).after(5)


class PendingTests(TestCase):
    def setUp(self):
        self.choice = PendingRef(seat=1, kind='pick', options=(1, 2))

    def test_a_choice_is_found_by_seat(self):
        self.assertEqual(for_seat((self.choice,), 1), self.choice)
        self.assertIsNone(for_seat((self.choice,), 0))

    def test_only_offered_answers_are_legal(self):
        self.assertTrue(is_legal(self.choice, 2))
        self.assertFalse(is_legal(self.choice, 3))


class ProjectionTests(TestCase):
    def setUp(self):
        self.cards = (Card(id='c1'), Card(id='c2'))

    def test_an_owned_hand_is_visible(self):
        visible, hidden = hand_view(self.cards, owned=True)
        self.assertEqual(visible, self.cards)
        self.assertIsNone(hidden)

    def test_another_hand_is_only_a_count(self):
        visible, hidden = hand_view(self.cards, owned=False)
        self.assertEqual(visible, ())
        self.assertEqual(hidden, 2)

