"""Tests for the grid sample, played in memory."""

import json
from dataclasses import asdict

from django.test import SimpleTestCase

from games.engine.base import GridView, IllegalAction
from games.engine.grid_sample.definition import GridSampleGame
from tests.support import Table, seats


def make_table():
    return Table(GridSampleGame(), seats(2), seed=5)


def arrange(table, *, meeples, caches=(), objectives=None, contents=None):
    """Put a controlled board in place, with seat 0 active."""
    table.state['meeples'] = meeples
    table.state['contents'] = dict(contents or {})
    table.hidden['caches'] = list(caches)
    table.hidden['objectives'] = dict(objectives or {})
    table.active = 0


class GridSampleSetupTests(SimpleTestCase):
    def setUp(self):
        self.definition = GridSampleGame()

    def test_the_setup_is_reproducible_and_serialisable(self):
        first = self.definition.setup({}, seats(2), seed=7)
        second = self.definition.setup({}, seats(2), seed=7)

        self.assertEqual(first.state, second.state)
        self.assertEqual(first.hidden, second.hidden)
        self.assertEqual(first.private, second.private)
        json.dumps(asdict(first))
        self.assertEqual(set(first.private), {0, 1})

    def test_every_seat_starts_on_a_distinct_unrevealed_cell(self):
        setup = self.definition.setup({}, seats(3), seed=7)

        starts = list(setup.state['meeples'].values())
        self.assertEqual(len(set(starts)), 3)
        self.assertEqual(set(setup.state['contents']), set())
        self.assertEqual(set(setup.hidden['objectives'].values()), set(starts))
        self.assertEqual(len(setup.hidden['caches']), 6)
        self.assertFalse(set(starts) & set(setup.hidden['caches']))

    def test_the_board_is_seven_by_seven(self):
        table = make_table()

        board = self.definition.view(table.context(), None).board

        self.assertIsInstance(board, GridView)
        self.assertEqual((board.columns, board.rows), (7, 7))
        self.assertEqual(len(board.cells), 49)

    def test_an_impossible_setup_is_refused(self):
        with self.assertRaises(ValueError):
            self.definition.validate_setup({}, seats(5))
        with self.assertRaises(ValueError):
            self.definition.validate_setup({'caches': 99}, seats(2))
        with self.assertRaises(ValueError):
            self.definition.validate_setup({'rounds': 0}, seats(2))


class GridSamplePlayTests(SimpleTestCase):
    def setUp(self):
        self.definition = GridSampleGame()

    def test_a_move_reveals_a_cache_and_scores_it(self):
        table = make_table()
        arrange(table, meeples={'0': '0,0', '1': '6,6'},
                caches=['1,0'], objectives={'0': '0,5', '1': '6,6'})

        transition = table.apply('move', {'cell': '1,0'})

        self.assertTrue(transition.reveals)
        self.assertEqual(table.state['contents']['1,0'],
                         {'kind': 'cache', 'seat': None})
        self.assertEqual(table.state['counters']['explored'], [1, 0])
        self.assertEqual(table.state['counters']['supply'], [2, 0])
        self.assertNotIn('1,0', table.hidden['caches'])
        self.assertEqual(table.state['meeples']['0'], '1,0')
        self.assertEqual(table.active, 1)

    def test_move_and_scout_options_have_coordinate_labels(self):
        table = make_table()
        table.state['meeples'] = {'0': '0,0', '1': '6,6'}
        table.active = 0

        move = next(option for option in table.legal_actions()
                    if option.id == 'move')
        scout = next(option for option in table.legal_actions()
                     if option.id == 'scout')

        self.assertEqual(move.params[0].labels[0], 'Column: 2, Row: 1')
        self.assertEqual(scout.params[0].labels[0], 'Column: 2, Row: 1')

    def test_a_move_reveals_an_empty_cell(self):
        table = make_table()
        arrange(table, meeples={'0': '0,0', '1': '6,6'},
                objectives={'0': '0,5', '1': '6,6'})

        table.apply('move', {'cell': '0,1'})

        self.assertEqual(table.state['contents']['0,1'],
                         {'kind': 'empty', 'seat': None})
        self.assertEqual(table.state['counters']['explored'], [1, 0])

    def test_revealing_an_objective_scores_its_owner(self):
        table = make_table()
        arrange(table, meeples={'0': '0,0', '1': '6,6'},
                objectives={'0': '0,1', '1': '6,6'})

        table.apply('move', {'cell': '0,1'})

        self.assertEqual(table.state['contents']['0,1'],
                         {'kind': 'objective', 'seat': 0})
        scores = self.definition.scores(table.context())
        self.assertEqual(next(row for row in scores if row['position'] == 0)
                         ['objective'], 3)

    def test_an_opponent_can_reveal_an_objective_for_its_owner(self):
        table = make_table()
        arrange(table, meeples={'0': '5,5', '1': '0,0'},
                objectives={'0': '1,0', '1': '6,6'})
        table.active = 1

        table.apply('move', {'cell': '1,0'})

        self.assertEqual(table.state['contents']['1,0']['seat'], 0)
        scores = self.definition.scores(table.context())
        self.assertEqual(next(row for row in scores if row['position'] == 0)
                         ['objective'], 3)
        self.assertEqual(next(row for row in scores if row['position'] == 1)
                         ['explored'], 1)

    def test_occupied_cells_are_not_move_targets(self):
        table = make_table()
        arrange(table, meeples={'0': '0,0', '1': '1,0'},
                objectives={'0': '0,5', '1': '6,6'})

        option = next(option for option in table.legal_actions()
                      if option.id == 'move')

        self.assertNotIn('1,0', option.params[0].options)
        with self.assertRaises(IllegalAction):
            table.apply('move', {'cell': '1,0'})

    def test_an_already_revealed_cell_gives_nothing(self):
        table = make_table()
        arrange(table, meeples={'0': '0,0', '1': '6,6'},
                objectives={'0': '0,5', '1': '6,6'},
                contents={'0,1': {'kind': 'empty', 'seat': None}})

        transition = table.apply('move', {'cell': '0,1'})

        self.assertFalse(transition.reveals)
        self.assertEqual(table.state['counters']['explored'], [0, 0])

    def test_scout_hides_what_was_there(self):
        table = make_table()
        arrange(table, meeples={'0': '0,0', '1': '6,6'},
                objectives={'0': '0,5', '1': '6,6'})

        transition = table.apply('scout', {'cell': '0,1'})

        self.assertFalse(transition.reveals)
        self.assertIn('0,1', table.hidden['caches'])
        self.assertNotIn('0,1', table.state['contents'])
        self.assertEqual(table.active, 1)

    def test_scout_excludes_occupied_and_revealed_cells(self):
        table = make_table()
        arrange(table, meeples={'0': '0,0', '1': '6,6'},
                objectives={'0': '0,5', '1': '6,6'},
                contents={'1,0': {'kind': 'empty', 'seat': None}})

        option = next(option for option in table.legal_actions()
                      if option.id == 'scout')

        self.assertEqual(option.params[0].options, ('0,1',))

    def test_scouting_a_start_destroys_its_objective(self):
        table = make_table()
        arrange(table, meeples={'0': '0,0', '1': '6,6'},
                objectives={'0': '0,1', '1': '6,6'})

        table.apply('scout', {'cell': '0,1'})
        table.active = 0
        table.apply('move', {'cell': '0,1'})

        self.assertEqual(table.state['contents']['0,1'],
                         {'kind': 'cache', 'seat': None})
        scores = self.definition.scores(table.context())
        self.assertEqual(next(row for row in scores if row['position'] == 0)
                         ['objective'], 0)

    def test_a_start_is_unmarked_once_the_meeple_leaves(self):
        table = make_table()
        spectator = self.definition.view(table.context(), None)
        self.assertTrue(all(cell.kind == 'hidden'
                            for cell in spectator.board.cells))
        self.assertEqual(sum(len(cell.tokens)
                             for cell in spectator.board.cells), 2)

        start = table.state['meeples']['0']
        move = next(option for option in table.legal_actions()
                    if option.id == 'move')
        table.apply('move', {'cell': move.params[0].options[0]})
        spectator = self.definition.view(table.context(), None)
        cell = next(cell for cell in spectator.board.cells
                    if f'{cell.column},{cell.row}' == start)

        self.assertEqual(cell.kind, 'hidden')
        self.assertEqual(cell.tokens, ())

    def test_the_round_limit_ends_the_game(self):
        table = make_table()
        table.state['rounds'] = 14

        transition = table.apply('pass')

        self.assertTrue(transition.over)
        self.assertTrue(table.over())
        self.assertEqual(transition.outbox[0].kind, 'match_over')

    def test_revealing_the_last_cell_ends_the_game(self):
        table = make_table()
        contents = {f'{column},{row}': {'kind': 'empty', 'seat': None}
                    for row in range(7) for column in range(7)
                    if f'{column},{row}' != '0,1'}
        arrange(table, meeples={'0': '0,0', '1': '6,6'},
                objectives={'0': '0,5', '1': '6,6'}, contents=contents)

        transition = table.apply('move', {'cell': '0,1'})

        self.assertTrue(transition.over)
        self.assertEqual(len(table.state['contents']), 49)

    def test_unknown_and_out_of_turn_actions_are_refused(self):
        table = make_table()
        with self.assertRaises(IllegalAction):
            table.apply('fly')
        with self.assertRaises(IllegalAction):
            table.apply('pass', actor=1)
