"""Tests for game entry-point discovery and the registry."""

from django.test import SimpleTestCase

from bgb_engine.examples import CardSampleGame, GridSampleGame
from games import plugins, registry


class RegistryTests(SimpleTestCase):
    def test_the_sample_game_is_registered(self):
        self.assertIsInstance(registry.get('card-sample-game'), CardSampleGame)

    def test_the_grid_sample_is_registered(self):
        self.assertIsInstance(registry.get('grid-sample-game'),
                              GridSampleGame)

    def test_the_registry_lists_the_installed_games(self):
        available = registry.available()
        self.assertIn('card-sample-game', available)
        self.assertIn('grid-sample-game', available)

    def test_an_unknown_slug_is_refused(self):
        with self.assertRaises(LookupError):
            registry.get('nope')

    def test_a_duplicate_slug_is_refused(self):
        with self.assertRaises(ValueError):
            registry.register(CardSampleGame())

    def test_installing_the_plugins_twice_is_harmless(self):
        plugins.install_plugins()
        plugins.install_plugins()
        self.assertIsInstance(registry.get('card-sample-game'), CardSampleGame)

