# Writing a Game

This guide is for a game package that plugs into BoardGameBot through
`bgb-engine`. The host owns storage, Discord, the web display and undo; your
package owns the rules.

## Package layout

An installable game package needs a normal Python project and one entry point:

```text
my-game/
  pyproject.toml
  my_game/
    __init__.py
    definition.py
  tests/
```

`pyproject.toml`:

```toml
[project]
name = "my-game"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = ["bgb-engine>=0.1,<0.2"]

[project.entry-points."boardgamebot.games"]
my-game = "my_game:MyGame"
```

BoardGameBot discovers the entry point and registers the definition. A plugin
may expose a definition instance, a class with a zero-argument constructor, or
a zero-argument factory. Slugs must be unique.

Do not import Django, Discord or the host application from `my_game`.

## The contract

Implement `bgb_engine.GameDefinition`:

```python
from typing import Any

from bgb_engine import (Action, ActionOption, Context, RenderModel, SeatRef,
                        Setup, Transition)


class MyGame:
    slug = 'my-game'
    name = 'My Game'
    version = 1
    min_players = 2
    max_players = 4
    capabilities = frozenset()

    def validate_setup(self, options: dict[str, Any],
                       seats: tuple[SeatRef, ...]) -> None:
        ...

    def setup(self, options: dict[str, Any], seats: tuple[SeatRef, ...],
              seed: int) -> Setup:
        ...

    def initial_phase(self) -> str:
        return 'play'

    def legal_actions(self, ctx: Context,
                      actor: int) -> tuple[ActionOption, ...]:
        ...

    def apply(self, ctx: Context, action: Action) -> Transition:
        ...

    def view(self, ctx: Context, position: int | None) -> RenderModel:
        ...

    def summary(self, ctx: Context,
                position: int | None) -> dict[str, Any]:
        ...

    def is_over(self, ctx: Context) -> bool:
        ...

    def scores(self, ctx: Context) -> list[dict[str, Any]]:
        ...
```

`capabilities` is a set of display capabilities such as `private`, `hands`,
`counters`, `pending`, `grid` or `graph`. It is advisory; the render model is
the source of truth for what a front end shows.

### Lifecycle

1. `validate_setup` checks options and seat counts. Raise `ValueError` for an
   invalid table.
2. `setup` deals the initial state. It must be reproducible from the match
   seed.
3. `legal_actions` returns the actions `actor` may take now. It must not mutate
   `ctx`.
4. `apply` validates one `Action` and returns a `Transition`. Raise
   `IllegalAction` when the action is not legal.
5. `view` returns what one viewer may see. A spectator has `position=None`.
6. `summary` and `scores` produce plain data for a finished match.
7. `is_over` answers whether the match has ended.

The host calls these methods; a definition never reads the database.

## State and visibility

A match has three kinds of state:

- `Match.state`: public state, readable by every viewer.
- `Match.hidden_state`: shared secret state, never shown directly to a viewer.
- `Seat.private_state`: one dictionary per seat.

`Setup` and `Transition` use the same split:

```python
from bgb_engine import Setup, Transition

setup = Setup(
    state={'round': 0, 'scores': [0, 0]},
    hidden={'deck': [4, 2, 7]},
    private={0: {'hand': ['a']}, 1: {'hand': ['b']}},
)

transition = Transition(
    state={'round': 1, 'scores': [0, 0]},
    hidden={'deck': [4, 2]},
    private={0: {'hand': ['b']}},
)
```

`Transition.state` replaces the public state. `Transition.hidden` and
`Transition.private` are patches merged into their stored dictionaries.

At a seat's view, include only that seat's private information. At a
spectator's view, include no private information. Do not put hidden cards,
deck order or another seat's hand into public state or a public view.

## Actions and parameters

`ActionOption` describes a legal move:

```python
from bgb_engine import ActionOption, Param

option = ActionOption(
    id='play_card',
    label='Play a card',
    params=(
        Param('card', 'Card', options=('card-1', 'card-2')),
    ),
)
```

The host presents the action and sends back an `Action` whose `params` contain
the stored values. Validate both the action id and every parameter in `apply`:

```python
from bgb_engine import Action, Context, IllegalAction, Transition


def apply(self, ctx: Context, action: Action) -> Transition:
    if action.id != 'play_card':
        raise IllegalAction('That action is not supported.')
    if action.actor != ctx.active:
        raise IllegalAction('It is not your turn.')
    card = action.params.get('card')
    if card not in ctx.private[action.actor].get('hand', []):
        raise IllegalAction('That card is not in your hand.')
    ...
```

Keep action ids stable. The host stores them in the action log and uses them to
render panels and replay the match.

## Pending choices and out-of-turn actions

A non-active seat may act only while it has an open pending choice. Open a
choice from a transition:

```python
from bgb_engine import PendingSpec, Transition


def apply(self, ctx: Context, action: Action) -> Transition:
    ...
    return Transition(
        state=ctx.state,
        active=action.actor,
        pending=(
            PendingSpec(
                seat=1,
                kind='react',
                label='React to the play',
                options=('accept', 'decline'),
            ),
        ),
    )
```

The pending seat receives the choice through `ctx.pending`. `legal_actions`
must return that seat's available actions:

```python
from bgb_engine import ActionOption, Param
from bgb_engine.primitives.pending import for_seat


def legal_actions(self, ctx: Context,
                  actor: int) -> tuple[ActionOption, ...]:
    choice = for_seat(ctx.pending, actor)
    if choice is not None:
        return (ActionOption(
            id='react',
            label='React',
            params=(Param('answer', 'Answer', options=choice.options),),
        ),)
    if actor != ctx.active:
        return ()
    return self.legal_actions_for_active_seat(ctx, actor)
```

Close the choice in the resolving transition:

```python
from bgb_engine import PendingSpec, Transition

return Transition(
    state=ctx.state,
    active=1,
    pending=(
        PendingSpec(
            seat=1,
            kind='react',
            close=True,
        ),
    ),
)
```

Include the viewer's pending choice in `RenderModel.pending`:

```python
from bgb_engine import PendingView

pending = None
for choice in ctx.pending:
    if choice.seat == position:
        pending = PendingView(
            kind=choice.kind,
            label=choice.label,
            options=choice.options,
        )
        break
```

While a choice is open, the host treats only its seat as needed for board
replacement and pings. Without a pending choice, the active seat is needed.

## Views and boards

`RenderModel` is the single structure the host renders:

```python
from bgb_engine import RenderModel

return RenderModel(
    board=...,
    zones=...,
    seats=...,
    counters=...,
    actions=...,
    pending=pending,
    log=...,
    status='Choose an action.',
)
```

Use `ZoneView` and `CardView` for hands and other card piles. `SeatView` carries
public seat labels, active state and counters. `CounterView` carries a named
counter across seats.

### Grid boards

Use `GridView` and `CellView` for square or hex boards. Each cell has a column,
row, kind, optional label and optional tokens. The host has a grid renderer for
the web page.

### Graph boards

Use `GraphView`, `GraphNodeView`, `GraphEdgeView` and `TokenView` for a graph:

```python
from bgb_engine import (GraphEdgeView, GraphNodeView, GraphView, TokenView)

board = GraphView(
    nodes=(
        GraphNodeView('start', 'Start', x=0, y=0, kind='start'),
        GraphNodeView('finish', 'Finish', x=10, y=0, kind='finish'),
    ),
    edges=(
        GraphEdgeView('start', 'finish', kind='path', label='Road'),
    ),
    tokens=(TokenView('start', '1', owner=0),),
)
```

Node coordinates are layout units; the web renderer normalizes them. Edges
accept an optional label and owner seats. The engine does not render a graph;
the host decides how the board is displayed. The current web display renders
graph boards, while the Discord board shows status, seats and the action log.

## Determinism

A match is replayable from its seed. Use the engine helpers instead of the
global random module:

```python
from bgb_engine import rng_for, shuffled

rng = rng_for(seed, 'deal')
deck = shuffled(cards, seed=seed, salt='deck')
```

Do not use wall-clock time, network calls, database access or unseeded
randomness in a definition. Keep public state and views JSON serialisable.
Iterate over ordered data where order affects state.

## Rules versions and upgrades

`version` identifies the rules used to create a match. A match refuses actions
under different installed rules.

If a game can migrate an in-progress match, implement `UpgradableRules`:

```python
from bgb_engine import Setup, UpgradableRules


class MyGame(UpgradableRules):
    def upgrade(self, from_version, state, hidden, private, seats, options,
                seed) -> Setup | None:
        ...
```

Return a new `Setup` or `None`. A rules upgrade is never undoable. New games
usually do not need in-flight upgrades.

## Testing

Test a definition without the host:

```python
import json
from dataclasses import asdict
from unittest import TestCase

from bgb_engine import Action, Context, SeatRef
from my_game import MyGame


class MyGameTests(TestCase):
    def test_setup_is_reproducible_and_serialisable(self):
        game = MyGame()
        seats = (SeatRef(position=0, name='P1'),
                 SeatRef(position=1, name='P2'))
        first = game.setup({}, seats, seed=7)
        second = game.setup({}, seats, seed=7)
        self.assertEqual(first.state, second.state)
        json.dumps(asdict(first))

    def test_an_action_changes_the_state(self):
        game = MyGame()
        seats = (SeatRef(position=0, name='P1'),
                 SeatRef(position=1, name='P2'))
        setup = game.setup({}, seats, seed=7)
        ctx = Context(
            slug=game.slug, seed=7, options={}, state=setup.state,
            hidden=setup.hidden, private=setup.private, seats=seats,
            phase=game.initial_phase(), active=0)
        option = game.legal_actions(ctx, 0)[0]
        params = {param.key: param.options[0] for param in option.params}
        transition = game.apply(
            ctx, Action(actor=0, id=option.id, params=params))
        self.assertIsNotNone(transition)
```

Also test:

- legal and illegal actions;
- pending choices and out-of-turn actions;
- that another seat's private information never appears in a view;
- deterministic replay;
- a full game reaching `is_over`;
- scores and summary for the final state.

Run the package tests with `python -m unittest` or your configured test runner.

## Reference games

The repository includes three original reference games:

- [Card Sample Game](sample-games.md#card-sample-game) — hands, a hidden deck,
  counters and a pending choice.
- [Grid Sample Game](sample-games.md#grid-sample-game) — a grid board with
  hidden cells and scoring.
- [Graph Sample Game](sample-games.md#graph-sample-game) — a graph board with
  paths, tokens and a finish condition.

Read their definitions in `bgb_engine.examples` for working implementations.

## Release checklist

- The package depends on `bgb-engine` and has no host imports.
- The entry point declares one unique slug.
- Setup is deterministic and JSON serialisable.
- Every legal action is validated again in `apply`.
- Private and hidden information is never leaked to public views.
- Pending seats expose their actions and close their choices.
- A full game reaches an end state and produces scores.
- The package tests pass against the installed engine version.
