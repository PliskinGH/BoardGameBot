"""An exploration game on a 7x7 grid, written to exercise the grid primitives."""

import copy
from typing import Any

from ...base import (Action, ActionOption, CellView, Context, GridView,
                     IllegalAction, LogEntry, OutboxItem, Param, RenderModel,
                     SeatRef, SeatView, Setup, TokenView, Transition)
from ...primitives.grid import BoardGrid
from ...primitives.rng import rng_for
from ...primitives.turn import TurnOrder

COLUMNS = 7
ROWS = 7
CACHE_COUNT = 6
MIN_CACHES = 0
ROUND_LIMIT = 14
PHASE = 'move'
FINISHED = 'finished'
EXPLORED = 'explored'
SUPPLY = 'supply'
CACHE_SUPPLY = 2
OBJECTIVE_BONUS = 3
MIN_PLAYERS = 2
MAX_PLAYERS = 4
MIN_ROUNDS = 1
MAX_ROUNDS = 50
VERSION = 1


class GridSampleGame:
    """Explore a grid, reveal objectives and collect secret caches."""

    slug = 'grid-sample-game'
    name = 'Grid Sample Game'
    version = VERSION
    min_players = MIN_PLAYERS
    max_players = MAX_PLAYERS
    capabilities = frozenset({'grid'})

    def validate_setup(self, options: dict[str, Any],
                       seats: tuple[SeatRef, ...]) -> None:
        if not self.min_players <= len(seats) <= self.max_players:
            raise ValueError(f'{self.name} seats {self.min_players} to '
                             f'{self.max_players} players.')
        if len({seat.position for seat in seats}) != len(seats):
            raise ValueError('Seat positions must be unique.')
        caches = options.get('caches', CACHE_COUNT)
        remaining = COLUMNS * ROWS - len(seats)
        if not isinstance(caches, int) or not (
                MIN_CACHES <= caches <= remaining):
            raise ValueError(
                f'caches must be an integer from {MIN_CACHES} to {remaining}.')
        rounds = options.get('rounds', ROUND_LIMIT)
        if not isinstance(rounds, int) or not (
                MIN_ROUNDS <= rounds <= MAX_ROUNDS):
            raise ValueError(
                f'rounds must be an integer from '
                f'{MIN_ROUNDS} to {MAX_ROUNDS}.')

    def setup(self, options: dict[str, Any], seats: tuple[SeatRef, ...],
              seed: int) -> Setup:
        self.validate_setup(options, seats)
        cells = [self._key(column, row)
                 for row in range(ROWS) for column in range(COLUMNS)]
        rng = rng_for(seed, 'grid-sample')
        starts = rng.sample(cells, len(seats))
        remaining = [cell for cell in cells if cell not in starts]
        caches = rng.sample(remaining, options.get('caches', CACHE_COUNT))
        state = {
            'meeples': {str(seat.position): start
                        for seat, start in zip(seats, starts)},
            'contents': {},
            'counters': {EXPLORED: [0] * len(seats),
                         SUPPLY: [0] * len(seats)},
            'rounds': 0,
            'over': False,
        }
        hidden = {
            'caches': caches,
            'objectives': {str(seat.position): start
                           for seat, start in zip(seats, starts)},
        }
        private: dict[int, dict[str, Any]] = {seat.position: {}
                                              for seat in seats}
        return Setup(state=state, hidden=hidden, private=private)

    def initial_phase(self) -> str:
        return PHASE

    def _key(self, column: int, row: int) -> str:
        return f'{column},{row}'

    def _cell_label(self, cell: str) -> str:
        column, row = (int(part) for part in cell.split(','))
        return f'Column: {column + 1}, Row: {row + 1}'

    def _name(self, ctx: Context, position: int) -> str:
        return ctx.seat(position).name or f'Seat {position + 1}'

    def _adjacent(self, cell: str) -> tuple[str, ...]:
        column, row = (int(part) for part in cell.split(','))
        return tuple(self._key(column, row)
                     for column, row in BoardGrid(COLUMNS, ROWS).neighbours(
                         column, row))

    def _ordered(self, cells: list[str]) -> tuple[str, ...]:
        return tuple(sorted(cells,
                            key=lambda cell: (int(cell.split(',')[1]),
                                              int(cell.split(',')[0]))))

    def _occupied(self, state: dict[str, Any]) -> set[str]:
        return set(state['meeples'].values())

    def _meeple(self, state: dict[str, Any], position: int) -> str:
        return str(state['meeples'][str(position)])

    def _move_targets(self, state: dict[str, Any],
                      position: int) -> tuple[str, ...]:
        occupied = self._occupied(state)
        return self._ordered([cell for cell in
                              self._adjacent(self._meeple(state, position))
                              if cell not in occupied])

    def _scout_targets(self, state: dict[str, Any],
                       position: int) -> tuple[str, ...]:
        occupied = self._occupied(state)
        return self._ordered([cell for cell in
                              self._adjacent(self._meeple(state, position))
                              if cell not in occupied
                              and cell not in state['contents']])

    def _reveal(self, state: dict[str, Any], hidden: dict[str, Any],
                cell: str) -> dict[str, Any]:
        content: dict[str, Any]
        if cell in hidden['caches']:
            hidden['caches'] = [key for key in hidden['caches']
                                if key != cell]
            content = {'kind': 'cache', 'seat': None}
        elif cell in hidden['objectives'].values():
            owner = next(int(seat) for seat, start in
                         hidden['objectives'].items() if start == cell)
            content = {'kind': 'objective', 'seat': owner}
        else:
            content = {'kind': 'empty', 'seat': None}
        state['contents'][cell] = content
        return content

    def legal_actions(self, ctx: Context,
                      actor: int) -> tuple[ActionOption, ...]:
        if ctx.active != actor or self.is_over(ctx):
            return ()
        actions: list[ActionOption] = []
        moves = self._move_targets(ctx.state, actor)
        if moves:
            actions.append(ActionOption(
                id='move', label='Move',
                params=(Param('cell', 'Cell', options=moves,
                              labels=tuple(self._cell_label(cell)
                                           for cell in moves)),)))
        scouts = self._scout_targets(ctx.state, actor)
        if scouts:
            actions.append(ActionOption(
                id='scout', label='Scout',
                params=(Param('cell', 'Cell', options=scouts,
                              labels=tuple(self._cell_label(cell)
                                           for cell in scouts)),)))
        actions.append(ActionOption(id='pass', label='Pass'))
        return tuple(actions)

    def apply(self, ctx: Context, action: Action) -> Transition:
        if self.is_over(ctx):
            raise IllegalAction('The game is over.')
        if action.actor != ctx.active:
            raise IllegalAction('It is not your turn.')
        legal = {option.id for option in self.legal_actions(ctx, action.actor)}
        if action.id not in legal:
            raise IllegalAction(f'{action.id!r} is not legal here.')
        state = copy.deepcopy(ctx.state)
        hidden = copy.deepcopy(ctx.hidden)
        if action.id == 'move':
            return self._move(ctx, action, state, hidden)
        if action.id == 'scout':
            return self._scout(ctx, action, state, hidden)
        return self._pass(ctx, action, state, hidden)

    def _move(self, ctx: Context, action: Action, state: dict[str, Any],
              hidden: dict[str, Any]) -> Transition:
        cell = action.params.get('cell')
        if cell not in self._move_targets(state, action.actor):
            raise IllegalAction('Move to one of the adjacent free cells.')
        state['meeples'][str(action.actor)] = cell
        log = [LogEntry(f'{self._name(ctx, action.actor)} moves to {cell}.')]
        revealed = cell not in state['contents']
        if revealed:
            content = self._reveal(state, hidden, cell)
            state['counters'][EXPLORED][action.actor] += 1
            if content['kind'] == 'cache':
                state['counters'][SUPPLY][action.actor] += CACHE_SUPPLY
                log.append(LogEntry(f'{self._name(ctx, action.actor)} finds '
                                    f'a cache.'))
            elif content['kind'] == 'objective':
                log.append(LogEntry(
                    f"{self._name(ctx, int(content['seat']))}'s objective "
                    f'is revealed.'))
        return self._advance(ctx, action.actor, state, hidden, log, revealed)

    def _scout(self, ctx: Context, action: Action, state: dict[str, Any],
               hidden: dict[str, Any]) -> Transition:
        cell = action.params.get('cell')
        if cell not in self._scout_targets(state, action.actor):
            raise IllegalAction('Scout one of the adjacent hidden free cells.')
        if cell not in hidden['caches']:
            hidden['caches'] = [*hidden['caches'], cell]
        log = [LogEntry(f'{self._name(ctx, action.actor)} scouts {cell}.')]
        return self._advance(ctx, action.actor, state, hidden, log, False)

    def _pass(self, ctx: Context, action: Action, state: dict[str, Any],
              hidden: dict[str, Any]) -> Transition:
        log = [LogEntry(f'{self._name(ctx, action.actor)} passes.')]
        return self._advance(ctx, action.actor, state, hidden, log, False)

    def _advance(self, ctx: Context, actor: int, state: dict[str, Any],
                 hidden: dict[str, Any], log: list[LogEntry],
                 reveals: bool) -> Transition:
        positions = tuple(seat.position for seat in ctx.seats)
        following = TurnOrder(positions).after(actor)
        if following == positions[0]:
            state['rounds'] += 1
        over = (state['rounds'] >= int(ctx.options.get('rounds',
                                                       ROUND_LIMIT))
                or len(state['contents']) >= COLUMNS * ROWS)
        state['over'] = over
        outbox: tuple[OutboxItem, ...] = ()
        if over:
            outbox = (OutboxItem(
                kind='match_over',
                payload={'scores': self._scores_from_state(ctx, state)}),)
        return Transition(state=state, hidden=hidden, log=tuple(log),
                          active=None if over else following,
                          phase=FINISHED if over else PHASE,
                          over=over, reveals=reveals, outbox=outbox)

    def view(self, ctx: Context, position: int | None) -> RenderModel:
        grid = BoardGrid(COLUMNS, ROWS)
        contents = ctx.state['contents']
        meeples = {cell: int(seat) for seat, cell
                   in ctx.state['meeples'].items()}
        cells = []
        for row in range(ROWS):
            for column in range(COLUMNS):
                cell = grid.key(column, row)
                content = contents.get(cell)
                owner = meeples.get(cell)
                tokens: tuple[TokenView, ...] = ()
                if owner is not None:
                    tokens = (TokenView(node=cell, label=str(owner + 1),
                                        owner=owner),)
                kind = content['kind'] if content else 'hidden'
                label = ''
                if content and content['kind'] == 'objective':
                    label = self._name(ctx, int(content['seat']))
                cells.append(CellView(column=column, row=row, label=label,
                                      kind=kind, tokens=tokens))
        seats = tuple(SeatView(
            position=seat.position, label=self._name(ctx, seat.position),
            is_active=seat.position == ctx.active,
            counters={EXPLORED: ctx.state['counters'][EXPLORED][seat.position],
                      SUPPLY: ctx.state['counters'][SUPPLY][seat.position]})
            for seat in ctx.seats)
        actions = (self.legal_actions(ctx, position)
                   if position is not None else ())
        return RenderModel(
            board=GridView(columns=COLUMNS, rows=ROWS, cells=tuple(cells)),
            seats=seats, actions=actions, status=self._status(ctx))

    def summary(self, ctx: Context,
                position: int | None) -> dict[str, Any]:
        return {'phase': ctx.phase, 'rounds': ctx.state.get('rounds', 0),
                'active': ctx.active, 'scores': self.scores(ctx)}

    def is_over(self, ctx: Context) -> bool:
        return (bool(ctx.state.get('over'))
                or len(ctx.state.get('contents', {})) >= COLUMNS * ROWS)

    def scores(self, ctx: Context) -> list[dict[str, Any]]:
        return self._scores_from_state(ctx, ctx.state)

    def _scores_from_state(self, ctx: Context,
                           state: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for seat in ctx.seats:
            explored = state['counters'][EXPLORED][seat.position]
            supply = state['counters'][SUPPLY][seat.position]
            objective = OBJECTIVE_BONUS * sum(
                1 for content in state['contents'].values()
                if content['kind'] == 'objective'
                and content['seat'] == seat.position)
            rows.append({'position': seat.position,
                         'name': self._name(ctx, seat.position),
                         'explored': explored, 'supply': supply,
                         'objective': objective,
                         'total': explored + supply + objective})
        return sorted(rows, key=lambda row: row['total'], reverse=True)

    def _status(self, ctx: Context) -> str:
        if self.is_over(ctx):
            return f'{self.name} finished.'
        if ctx.active is None:
            return 'No active seat.'
        return (f'Round {int(ctx.state.get("rounds", 0)) + 1}: '
                f'{self._name(ctx, ctx.active)} to move.')
