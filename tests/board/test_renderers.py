"""Tests for the template rows built from a render model."""

from unittest import mock

from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.utils import translation

from board.renderers import grid, seats, standings, zones
from games.services import log
from games.engine.base import (CardView, CellView, GridView, RenderModel,
                               SeatView, TokenView, ZoneView)
from games.services import undo
from games.services.matches import close_match
from tests.factories import play_first, started_match


class GridRowTests(SimpleTestCase):
    def test_a_model_without_a_grid_has_no_rows(self):
        self.assertIsNone(grid.rows(RenderModel()))

    def test_a_grid_keeps_each_cell_and_token(self):
        model = RenderModel(board=GridView(columns=2, rows=2, cells=(
            CellView(column=0, row=0, kind='hidden',
                     tokens=(TokenView(node='0,0', label='1', owner=0),)),
            CellView(column=1, row=0, kind='cache'),
            CellView(column=0, row=1, kind='objective', label='Wendy'),
        )))

        rows = grid.rows(model)

        self.assertEqual(rows['columns'], 2)
        self.assertEqual(len(rows['cells']), 2)
        self.assertEqual(rows['cells'][0][0]['kind'], 'hidden')
        self.assertEqual(rows['cells'][0][0]['tokens'][0]['label'], '1')
        self.assertEqual(rows['cells'][0][1]['kind'], 'cache')
        self.assertEqual(rows['cells'][1][0]['kind'], 'objective')
        self.assertEqual(rows['cells'][1][1]['kind'], 'hidden')

    def test_a_grid_exposes_numbered_headers(self):
        model = RenderModel(board=GridView(columns=2, rows=1, cells=(
            CellView(column=0, row=0, kind='hidden'),)))

        rows = grid.rows(model)

        self.assertEqual(rows['column_numbers'], [1, 2])
        self.assertEqual(rows['cells'][0][0]['column_number'], 1)
        self.assertEqual(rows['cells'][0][0]['row_number'], 1)

    def test_the_state_includes_a_grid_only_when_there_is_one(self):
        model = RenderModel(
            board=GridView(columns=1, rows=1, cells=(
                CellView(column=0, row=0, kind='hidden'),)),
            status='Playing.')
        html = render_to_string('board/_state.html', {
            'model': model, 'version': 1, 'state_url': '/state/',
            'seats': [], 'zones': [], 'log': [], 'is_setup': False,
            'grid': grid.rows(model)})

        self.assertIn('board-grid', html)

        html = render_to_string('board/_state.html', {
            'model': RenderModel(status='Playing.'), 'version': 1,
            'state_url': '/state/', 'seats': [], 'zones': [], 'log': [],
            'is_setup': False, 'grid': None})
        self.assertNotIn('board-grid', html)

    def test_the_grid_template_marks_each_kind_and_meeple(self):
        rows = {
            'columns': 2, 'rows': 1, 'hexes': False,
            'column_numbers': [1, 2],
            'cells': [[
                {'column': 0, 'row': 0, 'label': '',
                 'kind': 'hidden',
                 'tokens': [{'node': '0,0', 'label': '1', 'owner': 0}]},
                {'column': 1, 'row': 0, 'label': 'Wendy',
                 'kind': 'objective', 'tokens': []},
                {'column': 2, 'row': 0, 'label': '', 'kind': 'cache',
                 'tokens': []},
            ]],
        }

        html = render_to_string('board/_grid.html', {'grid': rows})

        self.assertIn('kind-hidden', html)
        self.assertIn('kind-objective', html)
        self.assertIn('kind-cache', html)
        self.assertIn('board-token', html)
        self.assertIn('token-owner-0', html)


class StandingsRowTests(SimpleTestCase):
    def test_scores_become_named_details(self):
        rows = standings.rows({'scores': [
            {'position': 0, 'name': 'Wendy', 'coins': 3, 'total': 5},
            {'position': 1, 'name': 'Guest', 'coins': 2, 'total': 4},
        ]})

        self.assertEqual(rows[0]['name'], 'Wendy')
        self.assertEqual(rows[0]['details'], [('Coins', 3), ('Total', 5)])

    def test_the_standings_template_lists_the_scores(self):
        html = render_to_string('board/_standings.html', {
            'standings': standings.rows({'scores': [
                {'name': 'Wendy', 'coins': 3}]})})

        self.assertIn('Final standings', html)
        self.assertIn('Wendy', html)
        self.assertIn('Coins: 3', html)


class ZoneRowTests(SimpleTestCase):
    def test_a_zone_keeps_its_cards_and_hidden_count(self):
        model = RenderModel(zones=(ZoneView(
            kind='hand', label='Your hand',
            cards=(CardView(id='c1', label='3', value=3),)),))

        self.assertEqual(zones.rows(model), [{
            'kind': 'hand', 'label': 'Your hand',
            'cards': [{'id': 'c1', 'label': '3', 'value': 3}],
            'hidden_count': None}])

    def test_a_model_with_nothing_renders_an_empty_state(self):
        html = render_to_string('board/_state.html', {
            'model': RenderModel(status='Nothing yet.'), 'version': 0,
            'state_url': '/state/', 'seats': [], 'zones': [], 'log': [],
            'is_setup': False})

        self.assertIn('Nothing yet.', html)
        self.assertIn('id="state-since"', html)


class SeatRowTests(SimpleTestCase):
    def test_a_seat_keeps_its_counters(self):
        model = RenderModel(seats=(SeatView(
            position=0, label='Wendy', is_active=True,
            counters={'coins': 3}, hidden_cards=2),))

        self.assertEqual(seats.rows(model), [{
            'position': 0, 'label': 'Wendy', 'is_active': True,
            'eliminated': False, 'counters': {'coins': 3},
            'hidden_cards': 2}])


class LogTests(TestCase):
    def setUp(self):
        self.match, self.players = started_match()

    def test_engine_lines_are_kept_oldest_first(self):
        match = play_first(self.match, self.players[0])

        lines = log.entries(match)

        self.assertEqual(lines[0]['seq'], 1)
        self.assertTrue(lines[0]['text'].endswith('.'))
        self.assertEqual(lines[0]['actor'], self.players[0].display_name)

    def test_an_undo_is_described(self):
        match = play_first(self.match, self.players[0])
        match = undo.undo_last_action(match.pk, self.players[0], force=True)

        self.assertEqual(log.entries(match)[-1]['text'], 'Undid step 1.')

    def test_the_fallbacks_go_through_the_translation_layer(self):
        match = close_match(self.match.pk, self.players[0])
        with mock.patch.object(log, '_',
                               side_effect=lambda text: f'[{text}]'):
            lines = log.entries(match)

        self.assertEqual(str(lines[-1]['text']), '[Closed the match.]')

    def test_an_undo_passes_its_step_to_the_translation(self):
        match = play_first(self.match, self.players[0])
        match = undo.undo_last_action(match.pk, self.players[0], force=True)
        with mock.patch.object(log, '_', side_effect=lambda text: text):
            lines = log.entries(match)

        self.assertEqual(lines[-1]['text'], 'Undid step 1.')

    def test_a_close_is_described(self):
        match = close_match(self.match.pk, self.players[0])

        self.assertEqual(log.entries(match)[-1]['text'], 'Closed the match.')

    def test_only_the_latest_actions_are_kept(self):
        match = play_first(self.match, self.players[0])

        self.assertEqual(len(log.entries(match, limit=1)), 1)


class TranslatedFragmentTests(SimpleTestCase):
    def test_the_fragment_renders_in_another_language(self):
        with translation.override('fr'):
            html = render_to_string('board/_state.html', {
                'model': RenderModel(status='Rien à faire.'),
                'version': 0, 'state_url': '/state/',
                'seats': [], 'zones': [], 'log': [], 'is_setup': False})

        self.assertIn('Rien à faire.', html)

    def test_the_setup_list_numbers_its_seats(self):
        html = render_to_string('board/_state.html', {
            'model': RenderModel(status=''), 'version': 0,
            'state_url': '/state/', 'seats': [], 'zones': [], 'log': [],
            'is_setup': True,
            'setup_seats': [{'number': 1, 'player': ''},
                            {'number': 2, 'player': 'Wendy'}]})

        self.assertIn('Seat 1', html)
        self.assertIn('Open', html)
        self.assertIn('Wendy', html)
