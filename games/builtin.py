"""The game definitions that ship with the framework."""

from .engine.card_sample.definition import CardSampleGame
from .engine.grid_sample.definition import GridSampleGame
from .registry import register

_installed = False


def install() -> None:
    """Register the built-in definitions once per process."""
    global _installed
    if _installed:
        return
    register(CardSampleGame())
    register(GridSampleGame())
    _installed = True
