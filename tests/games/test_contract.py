"""The contract every registered game must satisfy."""

import json
from dataclasses import asdict

from django.test import SimpleTestCase

from games import registry
from bgb_engine.base import GameDefinition, IllegalAction, Transition
from games.services.reveals import tokens
from tests.games.pending_game import PendingReactionGame
from tests.support import Table, seats


class GameContractTests(SimpleTestCase):
    def games(self):
        return {**registry.available(),
                PendingReactionGame.slug: PendingReactionGame()}

    def test_every_definition_satisfies_the_protocol(self):
        self.assertTrue(self.games())
        for slug, definition in self.games().items():
            with self.subTest(game=slug):
                self.assertIsInstance(definition, GameDefinition)
                for name in ('validate_setup', 'setup', 'initial_phase',
                             'legal_actions', 'apply', 'view', 'summary',
                             'is_over', 'scores'):
                    self.assertTrue(callable(getattr(definition, name, None)))
                self.assertEqual(definition.slug, slug)
                self.assertIsInstance(definition.version, int)
                self.assertLessEqual(definition.min_players,
                                     definition.max_players)

    def test_setup_is_reproducible_and_serialisable(self):
        for slug, definition in self.games().items():
            with self.subTest(game=slug):
                table_seats = seats(definition.min_players)
                first = definition.setup({}, table_seats, 7)
                second = definition.setup({}, table_seats, 7)
                self.assertEqual(first.state, second.state)
                self.assertEqual(first.hidden, second.hidden)
                self.assertEqual(first.private, second.private)
                json.dumps(asdict(first))
                self.assertEqual(set(first.private),
                                 {seat.position for seat in table_seats})
                self.assertIsInstance(definition.initial_phase(), str)

    def test_setup_refuses_an_impossible_table(self):
        for slug, definition in self.games().items():
            with self.subTest(game=slug):
                with self.assertRaises(ValueError):
                    definition.validate_setup(
                        {}, seats(definition.max_players + 1))

    def test_a_game_plays_to_an_end(self):
        for slug, definition in self.games().items():
            with self.subTest(game=slug):
                table = Table(definition, seats(definition.min_players),
                              seed=11)
                self.assertFalse(definition.is_over(table.context()))
                for _ in range(500):
                    if table.over():
                        break
                    actor = table.next_actor()
                    self.assertIsNotNone(actor)
                    option = table.legal_actions(actor)[0]
                    params = {param.key: param.options[0]
                              for param in option.params if param.options}
                    transition = table.apply(option.id, params, actor=actor)
                    self.assertIsInstance(transition, Transition)
                    json.dumps(transition.state)
                else:
                    self.fail('The game did not finish in 500 actions.')
                self.assertTrue(table.over())
                scores = definition.scores(table.context())
                self.assertEqual(len(scores), definition.min_players)

    def test_an_unknown_action_is_refused(self):
        for slug, definition in self.games().items():
            with self.subTest(game=slug):
                table = Table(definition, seats(definition.min_players),
                              seed=3)
                with self.assertRaises(IllegalAction):
                    table.apply('__nope__')

    def test_views_keep_other_seats_private(self):
        for slug, definition in self.games().items():
            with self.subTest(game=slug):
                table = Table(definition, seats(definition.min_players),
                              seed=3)
                public = tokens(table.state)
                private = {position: tokens(values)
                           for position, values in table.private.items()}
                unknown = set().union(*private.values()) - public
                spectator = tokens(asdict(
                    definition.view(table.context(), None)))
                self.assertFalse(unknown & spectator)
                for seat in table.seats:
                    others = set().union(
                        *(values for position, values in private.items()
                          if position != seat.position)) - public
                    payload = tokens(asdict(
                        definition.view(table.context(), seat.position)))
                    self.assertFalse(others & payload)

    def test_the_summary_is_a_plain_dict(self):
        for slug, definition in self.games().items():
            with self.subTest(game=slug):
                table = Table(definition, seats(definition.min_players),
                              seed=3)
                for viewer in (None, table.active):
                    json.dumps(definition.summary(table.context(), viewer))

    def test_replay_is_deterministic(self):
        for slug, definition in self.games().items():
            with self.subTest(game=slug):
                first = self._script(definition)
                second = self._script(definition)
                self.assertEqual(first.state, second.state)
                self.assertEqual(first.private, second.private)

    def test_a_pending_non_active_seat_can_act(self):
        table = Table(PendingReactionGame(), seats(2), seed=5)
        table.apply('open')

        self.assertEqual(table.pending[0].seat, 1)
        self.assertIn(1, table.needed_seats)
        self.assertEqual(table.next_actor(), 1)
        self.assertEqual(table.legal_actions(1)[0].id, 'react')

        table.apply('react', {'answer': 'accept'}, actor=1)
        self.assertEqual(table.pending, ())
        self.assertEqual(table.active, 0)

    def _script(self, definition):
        table = Table(definition, seats(definition.min_players), seed=5)
        for _ in range(50):
            if table.over():
                break
            actor = table.next_actor()
            option = table.legal_actions(actor)[0]
            params = {param.key: param.options[0]
                      for param in option.params if param.options}
            table.apply(option.id, params, actor=actor)
        return table
