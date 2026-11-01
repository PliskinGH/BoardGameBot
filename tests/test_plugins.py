"""Tests for entry-point plugin discovery."""

from unittest import mock

from django.test import SimpleTestCase

from bgb_engine.examples import CardSampleGame, GridSampleGame
from games import plugins


class FakeEntryPoint:
    def __init__(self, name, loaded):
        self.name = name
        self.loaded = loaded

    def load(self):
        if isinstance(self.loaded, Exception):
            raise self.loaded
        return self.loaded


class LoaderTests(SimpleTestCase):
    def test_an_instance_entry_point_is_returned(self):
        game = CardSampleGame()
        definition = plugins._definition(FakeEntryPoint('card', game))
        self.assertIs(definition, game)

    def test_a_class_entry_point_is_constructed(self):
        definition = plugins._definition(
            FakeEntryPoint('grid', GridSampleGame))
        self.assertIsInstance(definition, GridSampleGame)

    def test_a_factory_entry_point_is_called(self):
        definition = plugins._definition(
            FakeEntryPoint('factory', lambda: CardSampleGame()))
        self.assertIsInstance(definition, CardSampleGame)

    def test_an_invalid_entry_point_is_refused(self):
        with self.assertRaises(plugins.PluginError):
            plugins._definition(FakeEntryPoint('bad', object()))

    def test_a_broken_import_is_named(self):
        with self.assertRaises(plugins.PluginError) as caught:
            plugins._definition(FakeEntryPoint(
                'broken', ImportError('missing dependency')))
        self.assertIn('broken', str(caught.exception))

    def test_installing_twice_registers_once(self):
        entry_point = FakeEntryPoint('card', CardSampleGame)
        with mock.patch.object(plugins, '_installed', False), \
                mock.patch.object(plugins, 'entry_points',
                                  return_value=(entry_point,)), \
                mock.patch.object(plugins, 'register') as register:
            plugins.install_plugins()
            plugins.install_plugins()

        register.assert_called_once()

    def test_a_duplicate_slug_is_reported_as_a_plugin_error(self):
        entry_point = FakeEntryPoint('card', CardSampleGame)
        with mock.patch.object(plugins, '_installed', False), \
                mock.patch.object(plugins, 'entry_points',
                                  return_value=(entry_point,)), \
                mock.patch.object(plugins, 'register',
                                  side_effect=ValueError('duplicate')):
            with self.assertRaises(plugins.PluginError) as caught:
                plugins.install_plugins()

        self.assertIn('card', str(caught.exception))

    def test_the_engine_samples_are_installed_as_entry_points(self):
        names = {entry_point.name for entry_point in plugins.entry_points()}
        self.assertIn('card-sample', names)
        self.assertIn('grid-sample', names)
        self.assertIn('graph-sample', names)
