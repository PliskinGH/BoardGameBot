# BoardGameBot

A Discord bot for turn-based board games, with a web page that shows each table and lets a server share a match outside Discord.

## What it does

- Opens a table in a Discord channel and seats players.
- Posts the live board message for each match, with buttons to join, leave, start, close, take a turn, undo and open private information; a new active player is pinged when the board is replaced.
- Keeps an action log, undo, and a final recap.
- Shows the table on the web; a server can make its matches public for visitors.
- Includes Card Sample Game and Grid Sample Game as examples.

## Discord commands

| Command | Effect |
| --- | --- |
| `/match new game:<game> [seats] [policy] [name]` | Opens a match in the channel, seats the caller, and posts its board. The caller is the host. |
| `/match join` / `/match leave` | Takes or frees a seat before the start. |
| `/match start` | Starts the table once every seat is taken (host or manager). |
| `/match act` | Opens the caller's private move panel. |
| `/match private` | Shows the private information of the caller's seat. |
| `/match hand` | Compatibility alias for `/match private`. |
| `/match undo [force] [reason]` | Undoes the live action; a host or manager may force a reveal or a random action, with a reason. |
| `/match close` | Ends the match early as an undoable action (host or manager). |
| `/match upgrade` | Moves the match to the installed rules (host or manager). |
| `/match board` | Reposts or refreshes the public board. |
| `/match status` | Shows the table state privately. |
| `/manager add @user` / `/manager remove @user` | Gives or withdraws the server's manager permission (managers only). |

Game and match options accept either the value or the label autocomplete showed. `policy` is `SAFE` by default, which stops a player undoing a reveal or a random action; `ALL` lets them. A match belongs to the channel it was opened in. The board is a live message per match. It is edited in place while no new player needs to act, and replaced when a new
player becomes active; a natural ending posts a recap.

## Hosts and managers

The player who opens a table is its host. The host may start, close, upgrade, and force-undo that match.

A server manager may do the same for every match of that server. Managers are the people Discord allows to manage the server, plus anyone an existing manager adds with `/manager add`. The permission is granted automatically the first time a Discord server manager uses a match command or logs in to the web page.

A manager who is still a Discord server administrator keeps the permission: remove their Discord permission first, then `/manager remove`, for that to stick. Superusers of the web admin manage every server.

## The web page

Log in with Discord to see:

- the matches you hold a seat in;
- the servers you manage, with a button that invites the bot to each one.

A match page shows the match name, status, seats, zones, pending prompt, final standings and action log. A seated player also sees their own private information; nobody sees another seat's private state. The page refreshes by itself while it is open.

A server can make its matches public. Set **public display** on the server in the Django admin (`/admin/`); visitors who are not logged in then see the public state only, never a hand. Without it, a match page asks for a Discord login.

## Running your own instance

### Requirements

- Python 3.14
- PostgreSQL
- [uv](https://docs.astral.sh/uv/) for the dependencies and the virtual environment
- A Discord application (bot token, and OAuth2 credentials for the web page)

### Install

```sh
uv sync --locked --no-dev
cp .env.example .env
```

Create the PostgreSQL database named in `DATABASE_URL`, then:

```sh
uv run --no-sync python manage.py migrate
uv run --no-sync python manage.py collectstatic --no-input
uv run --no-sync python manage.py createsuperuser
```

`createsuperuser` creates the account for the Django admin; it is separate from the Discord login.

### Environment variables

| Variable | Required | Description |
| --- | --- | --- |
| `SECRET_KEY` | Yes | Django secret key. Required as soon as `DEBUG` is off. |
| `DEBUG` | Yes | `True` in development, `False` in production. |
| `ALLOWED_HOSTS` | Yes | Space-separated host names the site answers for. |
| `DATABASE_URL` | Yes | PostgreSQL URL, e.g. `postgres://user:password@host:5432/boardgamebot`. |
| `DISCORD_TOKEN` | Yes (bot) | Bot token of the Discord application. |
| `DISCORD_CLIENT_ID` | Web page only | Application ID, for the Discord login. |
| `DISCORD_CLIENT_SECRET` | Web page only | Application client secret. |
| `DISCORD_REDIRECT_URI` | No | OAuth2 redirect; defaults to `/discord/callback/` on the running site. |
| `WEB_BASE_URL` | No | Public base URL of the web page; the bot puts it in its links. |
| `TEST_GUILD_ID` | No | Space-separated server IDs where slash commands are registered immediately instead of after Discord's global propagation. |

Without the OAuth variables, the bot still plays; the web page cannot log anyone in.

### Discord application

1. Create an application at <https://discord.com/developers/applications>, add a bot, and copy its token into `DISCORD_TOKEN`.
2. Add the web page callback (`<WEB_BASE_URL>/discord/callback/`) to the application's OAuth2 redirects if you want the web login.
3. Invite the bot with the `bot` and `applications.commands` scopes. The invite button on the home page carries the permissions the board needs: view channels, send messages, embed links, read message history, and send messages in threads.
4. No privileged intents are needed: the bot requests only the guilds intent.

### Start the processes

The instance is two long-running processes. Activate the virtual environment first, or prefix each command with `uv run --no-sync`.

```sh
# web page
python -m uvicorn config.asgi:application --lifespan off

# Discord bot and its message queue
python manage.py runbot
```

Keep both running with whatever process manager your host provides. If your platform reads a `Procfile`, it declares a `web` process for the first command, a `worker` process for the second, and a release `migrate`. `collectstatic` belongs in the build step, and `migrate` before the web process starts.

`GET /healthz` answers without querying the database and can be used as a health check. The web process serves the static files through WhiteNoise, so no separate static server is required.

### First steps

1. Open `/admin/` with the superuser account and set **public display** on a server if its matches should be visible to visitors.
2. Invite the bot to a server, from the home page or with the application's invite URL.
3. Run `/match new` in a channel, invite players with `/match join`, and start with `/match start`.
4. Add managers with `/manager add`, or rely on Discord's **Manage Server** permission.

### Updating

```sh
uv sync --locked --no-dev
uv run --no-sync python manage.py migrate
uv run --no-sync python manage.py collectstatic --no-input
```

Restart both processes afterwards.

### Maintenance

- Back up the PostgreSQL database; it holds every match, player, and server.
- `python manage.py prune_snapshots --keep 50` deletes old action snapshots, keeping undo for the latest 50 actions of each match. Pruned steps can no longer be undone.
- The Django admin lists servers, players, matches, actions, and pending posts for inspection.

## Sample Games

The release ships two example games.

### Card Sample Game

- 2 to 4 players, three cards each, a deck of numbers 0–5 and one Swap card per cycle.
- On your turn, play a card: a number adds its value to your coins; Swap exchanges your coin total with another seat.
- Draw one card; the highest total when the deck and hands are empty wins.

It is an original sample written to exercise the bot, not an adaptation of a published game.

### Grid Sample Game

- Exploration game on 7x7 grid for 2 to 4 players.
- Each player has one meeple, starting on their own objective cell.
- On your turn, move one orthogonal step into a free cell, Scout, or Pass.
- Moving into a face-down cell reveals it: nothing, a cache (+2 supply), or an objective (its owner scores +3 at the end, whoever reveals it). Every newly revealed cell gives the mover +1 explored; moving into an already revealed cell gives nothing.
- Scout an adjacent, unrevealed, free cell to place a cache there, face down, without looking at what was there. It may have been nothing, a cache, or an objective; a scouted objective is destroyed.
- The game ends after 14 rounds or when every cell is revealed. Score = explored + supply + objective bonuses.
- The grid is shown on the web page; Discord shows the counters and offers the move choices.

It is also an original sample, not an adaptation of a published game.

## License

Released under the [MIT License](LICENSE).
