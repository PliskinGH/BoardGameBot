"""Tests for the game registry."""

from django.test import SimpleTestCase

from games import builtin, registry
from games.engine.card_sample.definition import CardSampleGame
from games.engine.grid_sample.definition import GridSampleGame


class RegistryTests(SimpleTestCase):
    def test_the_sample_game_is_registered(self):
        self.assertIsInstance(registry.get('card-sample-game'), CardSampleGame)

    def test_the_grid_sample_is_registered(self):
        self.assertIsInstance(registry.get('grid-sample-game'),
                              GridSampleGame)

    def test_the_registry_lists_the_builtin_games(self):
        self.assertEqual(list(registry.available()),
                         ['card-sample-game', 'grid-sample-game'])

    def test_an_unknown_slug_is_refused(self):
        with self.assertRaises(LookupError):
            registry.get('nope')

    def test_a_duplicate_slug_is_refused(self):
        with self.assertRaises(ValueError):
            registry.register(CardSampleGame())

    def test_installing_the_builtins_twice_is_harmless(self):
        builtin.install()
        builtin.install()
        self.assertIsInstance(registry.get('card-sample-game'), CardSampleGame)

