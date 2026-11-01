# BoardGameBot Engine

An engine for asynchronous, turn-based board games played through Discord.

It has no Django, Discord or web dependency.

## Features

- A game contract for setup, actions, transitions, rendering, scoring and rules upgrades.
- Turn-based play with pending choices and out-of-turn reactions.
- Public, hidden and per-seat private state.
- Deterministic seeded replay.
- Cards, zones, counters and turn order.
- Grid boards.
- Graph boards.
- Installable game plugins.
- Card, Grid and Graph reference games.

## Install

```sh
pip install bgb-engine
```

## Use

```python
from bgb_engine import GameDefinition, RenderModel
```

The reference games live in `bgb_engine.examples`:

```python
from bgb_engine.examples import (CardSampleGame, GraphSampleGame,
                                GridSampleGame)
```

They are also installed as plugins for BoardGameBot through the
`boardgamebot.games` entry-point group.

## Reference games

- `CardSampleGame`: card hands, hidden state, counters and pending choices.
- `GridSampleGame`: a grid board with hidden cells and scoring.
- `GraphSampleGame`: a graph board with paths, tokens and a finish condition.

The rules for the reference games are in the main project documentation. A
complete authoring guide is in the repository at `docs/writing-a-game.md`.

## Write a game

Implement the `GameDefinition` protocol and declare an entry point in your
package:

```toml
[project.entry-points."boardgamebot.games"]
my-game = "my_game:MyGame"
```

The entry point may return a definition instance, a class with a zero-argument
constructor, or a zero-argument factory. The host validates the result and
refuses duplicate slugs.

A non-active seat may act only while it holds an open pending choice. Return
that seat's legal actions from `legal_actions` and open the choice with a
`PendingSpec` in a transition. While a choice is open, the host treats only its
seat as needed for board replacement, pings and private panels; otherwise the
active seat is needed.

## License

BoardGameBot Engine is released under the MIT License.
