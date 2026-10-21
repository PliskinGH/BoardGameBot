# BoardGameBot — developer guide

BoardGameBot runs turn-based board games in a Discord channel and shows each table on a Django web page. The README covers playing and hosting; this guide covers the code.

## What exists

- A generic game engine with a contract every registered game satisfies: setup, legal actions, transitions, rendering, scoring and upgrades.
- Match persistence: seats, an append-only action log, per-action snapshots, pending choices, undo and rewind, and per-seat private state.
- Discord commands for opening, seating, starting and playing a match; persistent board buttons for join, leave, start, close, turns, undo and private information; a live board message edited in place and replaced when a new player needs to act; a recap at the end; a transactional outbox with retries.
- A web display with Discord login: the player's matches and managed servers, a live match page with match names and final standings, and a public display mode for servers that opt in.
- Per-match hosts (the player who opens a table) and per-server managers (guardian object permissions), including force-undo audit and manager grants.
- Snapshot retention (`prune_snapshots`) and Django admin pages for servers, players, matches, actions and queued posts.
- `CardSampleGame`, the original numbered-card sample, registered in `games/builtin.py`.
- `GridSampleGame`, the 7×7 exploration sample with a web-only board, registered in `games/builtin.py`.

## What remains

- **Real-time push** over Channels instead of polling. Validate Channels compatibility with the installed Django/Python first; polling remains the fallback.
- **Optional web play**: POST endpoints for act, undo and rewind, with CSRF, the same visibility rules, and service-error mapping.

## Stack

- Python 3.14, Django 6.1, PostgreSQL, uvicorn (ASGI, `--lifespan off`), discord.py, django-guardian, WhiteNoise.
- Dependencies and the virtual environment are managed with [uv](https://docs.astral.sh/uv/); `pyproject.toml` and `uv.lock` are the source of truth. The dev group contains mypy, django-stubs and debugpy.

## Local setup

```sh
uv sync --locked
cp .env.example .env
# Create the PostgreSQL database named in DATABASE_URL.
uv run --no-sync python manage.py migrate
uv run --no-sync python manage.py createsuperuser
```

Run the web process and the bot:

```sh
uv run --no-sync python -m uvicorn config.asgi:application --reload --lifespan off
uv run --no-sync python manage.py runbot
```

## Gates

```sh
uv run --no-sync mypy
uv run --no-sync python manage.py check
uv run --no-sync python manage.py makemigrations --check --dry-run
uv run --no-sync python manage.py test --noinput
```

The test runner builds and drops a test database from the migration files. `tests.support.NoNetworkMixin` blocks HTTP and `NoDiscordMixin` blocks Discord; the latter also closes the ORM thread connection at teardown.

## Layout

| app | contents |
| --- | --- |
| `config` | settings, URLs, ASGI application |
| `core` | `Player`, `Guild`, Discord OAuth, guardian helpers, admin, templates |
| `games` | models, engine and primitives, services, registry, `prune_snapshots` |
| `board` | read-only display: queries, renderers, views, templates |
| `discordbot` | bot, cogs, panels/views, embeds, outbox worker, `runbot` |
| `tests` | engine, services, board, core, discordbot, factories, support |

## Architecture

- Services own writes: views and the bot call `games.services.*`; engine transitions are never applied outside the service.
- `Match.state` is public, `Match.hidden_state` is shared hidden data, and `Seat.private_state` is per seat. A render model receives public state and only the viewer's own private state.
- `Match.version` counts actions and only grows; `Match.position` is the live action sequence, with `0` for setup. Seating does not bump the version, so SETUP polls render fully.
- Undo is snapshot-based. `SAFE` blocks undoing a reveal or a random action; the host or a server manager may force it, with a reason stored in `Action.result`. A rules upgrade is never undoable.
- Every write queues a `board_update` outbox row. `claim_batch` uses skip-locked rows and backoff; the worker compares the needed seats with `Match.last_needed_seats`, edits in place when no player is newly needed, and replaces the board and pings the new players otherwise. It reposts a deleted board and marks terminal failures after five attempts.
- `games.services.notifier.game_changed` runs on commit; it is a no-op until real-time push exists.
- Discord custom ids are length-proof: board `match:<pk>:act|hand|private|join|leave|start|close|undo`; panels `match:<pk>:<12-hex token>:do:<i>|pick:<i>:<j>|form:<i>`. Panel tokens fingerprint `(version, seat, action/param shape and labels)`; clicks re-render and stale panels are refused; select values are indices. Panels are `LayoutView` messages with text labels above selects; modals use `Label` components for multi-parameter actions.
- `Match.host` is the creator. Guild managers are guardian `core.manage_matches` object permissions on `Guild`; `get_objects_for_user` lists managed servers for the home page. Superusers are implicit managers.
- `Match.name` is chosen by the host at creation; `Seat.display_name` stores the server display name and falls back to `Player.display_name`. `Match.last_needed_seats` drives board replacement and pings.
- Games advertise `private` and mark their private `ZoneView`s; `board/queries` renders final standings from `summary` on a finished match. `Param.labels` supplies display labels while stored values stay unchanged.
- `Match.host`, `Seat.player` and `Action.actor` are `SET_NULL`; deleting a player keeps the seat and the log.
- Localization: `gettext_lazy as _` in Python and `{% translate %}`/`{% blocktranslate %}` in templates. Engine content and service error messages stay English.

## Database and migrations

- Project migrations are `core/0001_initial.py`, `games/0001_initial.py` and `games/0002_match_last_needed_seats_match_name_seat_display_name.py`; guardian ships its own package migrations. There are no data migrations.
- The test runner applies the migration files to a fresh test database, which is how migration changes are exercised.
- Model changes are captured with `makemigrations`; migrations to a shared database are applied by its operator.

## Games and engine

- A game implements `games.engine.base.GameDefinition` and returns a `Transition` from `apply`. Primitives live in `games.engine.primitives`: phases, zones and cards, graph, grid, counters, turn order, pending lookups, seeded randomness and projection.
- `tests/games/test_contract.py` runs every registered game through setup reproducibility, JSON shapes, legal actions, visibility and deterministic replay.
- A match stores the rules version it was created with; actions refuse to run under other rules, and `upgrade_match` rebuilds a match before start or asks an `UpgradableRules` definition to migrate it in flight.
- Add a game under `games/engine/<slug>/definition.py` and register it in `games/builtin.py`; its data is JSON, so no model migration is needed.
- `games/engine/card_sample/` is `CardSampleGame`: hands, a hidden deck, counters, phases, a pending choice and a reveal/undo path.
- `games/engine/grid_sample/` is `GridSampleGame`: a 7×7 board, secret caches, unmarked objective starts, and the grid renderer it feeds on the web.

## Deployment

- Two processes: the web ASGI process (`uvicorn config.asgi:application --lifespan off`) and the bot (`python manage.py runbot`, which also runs the outbox worker).
- `Procfile` declares `web`, `worker`, and a release `migrate`; `collectstatic` belongs in the build; WhiteNoise serves `staticfiles/`.
- `SECRET_KEY` is required when `DEBUG` is off; `ALLOWED_HOSTS`, `DATABASE_URL`, the OAuth variables and `WEB_BASE_URL` configure the instance.
- CI (`.github/workflows/django.yml`) installs uv, runs `uv sync --locked`, mypy, check, the migrations check and tests against PostgreSQL 17.
