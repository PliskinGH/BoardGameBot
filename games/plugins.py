"""Discover game definitions from installed entry points."""

from importlib import metadata
from typing import Any

from bgb_engine.base import GameDefinition

from .registry import register

ENTRY_POINT_GROUP = 'boardgamebot.games'

_installed = False


class PluginError(Exception):
    """A plugin could not be loaded or does not satisfy the contract."""


def _definition(entry_point: Any) -> GameDefinition:
    """Return the definition one entry point provides."""
    try:
        loaded = entry_point.load()
    except Exception as error:  # noqa: BLE001 - plugin errors name their source
        raise PluginError(
            f'Could not import plugin {entry_point.name!r}: {error}') from error

    if isinstance(loaded, type):
        try:
            loaded = loaded()
        except Exception as error:  # noqa: BLE001 - plugin errors name their source
            raise PluginError(
                f'Could not construct plugin {entry_point.name!r}: '
                f'{error}') from error
    elif not isinstance(loaded, GameDefinition) and callable(loaded):
        try:
            loaded = loaded()
        except Exception as error:  # noqa: BLE001 - plugin errors name their source
            raise PluginError(
                f'Could not build plugin {entry_point.name!r}: '
                f'{error}') from error

    if not isinstance(loaded, GameDefinition):
        raise PluginError(
            f'Plugin {entry_point.name!r} did not provide a game definition.')
    return loaded


def entry_points() -> tuple[Any, ...]:
    """Return the installed game entry points in a stable order."""
    return tuple(sorted(metadata.entry_points(group=ENTRY_POINT_GROUP),
                        key=lambda entry_point: entry_point.name))


def install_plugins() -> None:
    """Register every installed game plugin once per process."""
    global _installed
    if _installed:
        return
    for entry_point in entry_points():
        definition = _definition(entry_point)
        try:
            register(definition)
        except ValueError as error:
            raise PluginError(
                f'Plugin {entry_point.name!r}: {error}') from error
    _installed = True
