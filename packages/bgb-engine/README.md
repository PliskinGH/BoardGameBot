# BoardGameBot Engine

An engine for asynchronous, turn-based board games played through Discord.

It provides the game contract, board and card primitives, deterministic
randomness, pending-choice lookups and reference games. It has no Django,
Discord or web dependency.

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
from bgb_engine.examples import CardSampleGame, GridSampleGame
```

They are also installed as plugins for BoardGameBot through the
`boardgamebot.games` entry-point group.

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
