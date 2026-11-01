"""The contract every game definition implements.

Nothing here imports Django: a definition is played in memory, and the
persistence layer adapts its rows to these plain values.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class IllegalAction(Exception):
    """The actor may not take this action in the current context."""


@dataclass(frozen=True)
class SeatRef:
    """A seat as the engine sees it; no Django model crosses this boundary."""

    position: int
    role: str = ''
    player_id: int | None = None
    name: str = ''


@dataclass(frozen=True)
class Param:
    """One argument an action needs, with the values the UI may offer."""

    key: str
    label: str
    kind: str = 'option'
    options: tuple[Any, ...] = ()
    labels: tuple[str, ...] = ()



@dataclass(frozen=True)
class ActionOption:
    """A legal action, rendered as a button, a form or a select."""

    id: str
    label: str
    params: tuple[Param, ...] = ()
    group: str = ''
    enabled: bool = True
    cost: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Action:
    """What an actor asks to do; ``id`` must be one of the legal options."""

    actor: int
    id: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PendingRef:
    """A choice still waiting for an answer."""

    seat: int
    kind: str
    label: str = ''
    options: tuple[Any, ...] = ()


@dataclass(frozen=True)
class PendingSpec:
    """A choice to open, or to close when ``close`` is set."""

    seat: int
    kind: str
    label: str = ''
    options: tuple[Any, ...] = ()
    context: dict[str, Any] = field(default_factory=dict)
    close: bool = False


@dataclass(frozen=True)
class LogEntry:
    text: str
    kind: str = 'info'


@dataclass(frozen=True)
class OutboxItem:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Setup:
    """The initial deal: public state, shared hidden state, per-seat state."""

    state: dict[str, Any]
    hidden: dict[str, Any] = field(default_factory=dict)
    private: dict[int, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class Transition:
    """What one legal action produced.

    ``state`` replaces the public state; ``hidden`` and ``private`` are
    patches merged into the stored dictionaries.
    """

    state: dict[str, Any]
    hidden: dict[str, Any] = field(default_factory=dict)
    private: dict[int, dict[str, Any]] = field(default_factory=dict)
    pending: tuple[PendingSpec, ...] = ()
    log: tuple[LogEntry, ...] = ()
    outbox: tuple[OutboxItem, ...] = ()
    active: int | None = None
    phase: str | None = None
    over: bool = False
    random: bool = False
    reveals: bool | None = None


@dataclass(frozen=True)
class Context:
    """Everything a definition may read while computing a view or an action."""

    slug: str
    seed: int
    options: dict[str, Any]
    state: dict[str, Any]
    hidden: dict[str, Any]
    private: dict[int, dict[str, Any]]
    seats: tuple[SeatRef, ...]
    phase: str
    active: int | None
    pending: tuple[PendingRef, ...] = ()

    def seat(self, position: int) -> SeatRef:
        """Return the seat at ``position``; raise ``KeyError`` when absent."""
        for seat in self.seats:
            if seat.position == position:
                return seat
        raise KeyError(f'No seat at position {position}.')


@dataclass(frozen=True)
class CardView:
    """A card a front end may render."""

    id: str
    label: str = ''
    value: int = 0


@dataclass(frozen=True)
class ZoneView:
    """A pile of cards, hidden ones replaced by their count."""

    kind: str
    label: str
    private: bool = False

    cards: tuple[CardView, ...] = ()
    hidden_count: int | None = None


@dataclass(frozen=True)
class SeatView:
    """A seat in the standings, with its public counters."""

    position: int
    label: str
    is_active: bool = False
    eliminated: bool = False
    counters: dict[str, int] = field(default_factory=dict)
    hidden_cards: int = 0


@dataclass(frozen=True)
class CounterView:
    """One named counter across every seat."""

    key: str
    label: str
    values: dict[int, int] = field(default_factory=dict)


@dataclass(frozen=True)
class PendingView:
    """The choice this seat has to answer, if any."""

    kind: str
    label: str
    options: tuple[Any, ...] = ()
    deadline: str | None = None


@dataclass(frozen=True)
class GraphNodeView:
    id: str
    label: str = ''
    x: float = 0.0
    y: float = 0.0
    kind: str = ''


@dataclass(frozen=True)
class GraphEdgeView:
    source: str
    target: str
    kind: str = ''


@dataclass(frozen=True)
class TokenView:
    node: str
    label: str = ''
    owner: int | None = None


@dataclass(frozen=True)
class GraphView:
    """A board of nodes and edges, with tokens on nodes."""

    nodes: tuple[GraphNodeView, ...] = ()
    edges: tuple[GraphEdgeView, ...] = ()
    tokens: tuple[TokenView, ...] = ()


@dataclass(frozen=True)
class CellView:
    column: int
    row: int
    label: str = ''
    kind: str = ''
    tokens: tuple[TokenView, ...] = ()


@dataclass(frozen=True)
class GridView:
    """A board of squares or hexes."""

    columns: int
    rows: int
    hexes: bool = False
    cells: tuple[CellView, ...] = ()


@dataclass(frozen=True)
class LogEntryView:
    text: str
    kind: str = 'info'


@dataclass(frozen=True)
class RenderModel:
    """One structure both front ends consume."""

    board: GraphView | GridView | None = None
    zones: tuple[ZoneView, ...] = ()
    seats: tuple[SeatView, ...] = ()
    counters: tuple[CounterView, ...] = ()
    actions: tuple[ActionOption, ...] = ()
    pending: PendingView | None = None
    log: tuple[LogEntryView, ...] = ()
    status: str = ''


@runtime_checkable
class GameDefinition(Protocol):
    """The rules of one game, registered under a slug."""

    slug: str
    name: str
    version: int
    min_players: int
    max_players: int
    capabilities: frozenset[str]

    def validate_setup(self, options: dict[str, Any],
                       seats: tuple[SeatRef, ...]) -> None: ...

    def setup(self, options: dict[str, Any], seats: tuple[SeatRef, ...],
              seed: int) -> Setup: ...

    def initial_phase(self) -> str: ...

    def legal_actions(self, ctx: Context,
                      actor: int) -> tuple[ActionOption, ...]: ...

    def apply(self, ctx: Context, action: Action) -> Transition: ...

    def view(self, ctx: Context, position: int | None) -> RenderModel: ...

    def summary(self, ctx: Context,
                position: int | None) -> dict[str, Any]: ...

    def is_over(self, ctx: Context) -> bool: ...

    def scores(self, ctx: Context) -> list[dict[str, Any]]: ...



@runtime_checkable
class UpgradableRules(Protocol):
    """A definition that can carry a running match to newer rules."""

    def upgrade(self, from_version: int, state: dict[str, Any],
                hidden: dict[str, Any],
                private: dict[int, dict[str, Any]],
                seats: tuple[SeatRef, ...], options: dict[str, Any],
                seed: int) -> Setup | None: ...
