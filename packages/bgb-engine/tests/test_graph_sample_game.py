"""Smoke tests for the graph reference game without the host application."""

import json
from dataclasses import asdict
from unittest import TestCase

from bgb_engine import Action, Context, GraphView, SeatRef
from bgb_engine.examples import GraphSampleGame


def seats(count):
    """Return named seats in play order."""
    return tuple(SeatRef(position=index, name=f'P{index + 1}')
                 for index in range(count))


def context(game, setup, seat_refs, active, state=None, phase=None):
    """Build the plain context a definition reads."""
    return Context(
        slug=game.slug, seed=1, options={}, state=setup.state
        if state is None else state,
        hidden=setup.hidden, private=setup.private, seats=seat_refs,
        phase=game.initial_phase() if phase is None else phase,
        active=active)


class GraphSampleTests(TestCase):
    def setUp(self):
        self.game = GraphSampleGame()
        self.seat_refs = seats(2)
        self.setup = self.game.setup({}, self.seat_refs, seed=1)

    def test_setup_is_reproducible_and_json_serialisable(self):
        second = self.game.setup({}, self.seat_refs, seed=1)
        self.assertEqual(self.setup.state, second.state)
        self.assertEqual(self.setup.private, second.private)
        json.dumps(asdict(self.setup))

    def test_the_view_contains_nodes_edges_and_tokens(self):
        model = self.game.view(
            context(self.game, self.setup, self.seat_refs, 0), 0)

        self.assertIsInstance(model.board, GraphView)
        self.assertEqual(len(model.board.nodes), 5)
        self.assertEqual(len(model.board.edges), 4)
        self.assertEqual(len(model.board.tokens), 2)
        self.assertEqual([option.id for option in model.actions],
                         ['advance'])

    def test_a_token_advances_toward_the_finish(self):
        ctx = context(self.game, self.setup, self.seat_refs, 0)
        option = self.game.legal_actions(ctx, 0)[0]
        transition = self.game.apply(ctx, Action(
            actor=0, id=option.id,
            params={param.key: param.options[0]
                    for param in option.params}))

        self.assertEqual(transition.state['positions']['0'], 'mid-0')
        self.assertEqual(transition.active, 1)
        self.assertFalse(transition.over)

    def test_the_game_ends_when_a_token_reaches_the_finish(self):
        state = self.setup.state
        active = 0
        phase = self.game.initial_phase()
        over = False
        for _ in range(5):
            ctx = context(self.game, self.setup, self.seat_refs, active,
                          state, phase)
            option = self.game.legal_actions(ctx, active)[0]
            transition = self.game.apply(ctx, Action(
                actor=active, id=option.id,
                params={param.key: param.options[0]
                        for param in option.params}))
            state, active = transition.state, transition.active
            phase = transition.phase or phase
            over = transition.over
            if over:
                break
        self.assertTrue(over)
        self.assertEqual(state['winner'], 0)
        ctx = context(self.game, self.setup, self.seat_refs, None, state)
        self.assertEqual(len(self.game.scores(ctx)), 2)
