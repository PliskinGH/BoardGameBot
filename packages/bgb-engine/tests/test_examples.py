"""Smoke tests for the reference games without the host application."""

import json
from dataclasses import asdict
from unittest import TestCase

from bgb_engine import Context, GridView, RenderModel, SeatRef
from bgb_engine.examples import CardSampleGame, GridSampleGame


def seats(count):
    """Return named seats in play order."""
    return tuple(SeatRef(position=index, name=f'P{index + 1}')
                 for index in range(count))


def context(game, setup, seat_refs, seed):
    """Build the plain context a definition reads."""
    return Context(
        slug=game.slug, seed=seed, options={}, state=setup.state,
        hidden=setup.hidden, private=setup.private, seats=seat_refs,
        phase=game.initial_phase(),
        active=seat_refs[0].position if seat_refs else None)


class CardSampleTests(TestCase):
    def setUp(self):
        self.game = CardSampleGame()
        self.seat_refs = seats(2)
        self.setup = self.game.setup({}, self.seat_refs, seed=11)

    def test_setup_is_reproducible_and_json_serialisable(self):
        second = self.game.setup({}, self.seat_refs, seed=11)
        other = self.game.setup({}, self.seat_refs, seed=12)

        self.assertEqual(self.setup.state, second.state)
        self.assertEqual(self.setup.hidden, second.hidden)
        self.assertEqual(self.setup.private, second.private)
        self.assertNotEqual(self.setup.private, other.private)
        json.dumps(asdict(self.setup))

    def test_a_view_is_plain_data(self):
        model = self.game.view(
            context(self.game, self.setup, self.seat_refs, 11), 0)
        self.assertIsInstance(model, RenderModel)
        json.dumps(asdict(model))


class GridSampleTests(TestCase):
    def setUp(self):
        self.game = GridSampleGame()
        self.seat_refs = seats(2)
        self.setup = self.game.setup({}, self.seat_refs, seed=7)

    def test_setup_is_reproducible_and_has_a_grid(self):
        second = self.game.setup({}, self.seat_refs, seed=7)
        self.assertEqual(self.setup.state, second.state)
        self.assertEqual(self.setup.hidden, second.hidden)
        self.assertEqual(set(self.setup.private), {0, 1})

        model = self.game.view(
            context(self.game, self.setup, self.seat_refs, 7), None)
        self.assertIsInstance(model.board, GridView)
        self.assertEqual((model.board.columns, model.board.rows), (7, 7))
        self.assertEqual(len(model.board.cells), 49)

    def test_the_reference_grid_is_seven_by_seven(self):
        self.assertEqual((GridView(columns=7, rows=7).columns,
                          GridView(columns=7, rows=7).rows), (7, 7))
