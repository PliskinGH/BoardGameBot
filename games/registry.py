"""The game definitions available to a match, keyed by slug."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bgb_engine.base import GameDefinition

_DEFINITIONS: dict[str, 'GameDefinition'] = {}


def register(definition: 'GameDefinition') -> 'GameDefinition':
    """Add a definition, refusing to replace one under the same slug."""
    if definition.slug in _DEFINITIONS:
        raise ValueError(f'A game is already registered as {definition.slug!r}.')
    _DEFINITIONS[definition.slug] = definition
    return definition


def get(slug: str) -> 'GameDefinition':
    """Return the definition registered as ``slug``."""
    try:
        return _DEFINITIONS[slug]
    except KeyError:
        raise LookupError(f'No game is registered as {slug!r}.') from None


def available() -> dict[str, 'GameDefinition']:
    """Return the registered definitions, keyed by slug."""
    return dict(_DEFINITIONS)

