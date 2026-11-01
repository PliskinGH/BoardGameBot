"""A small graph game that exercises the graph view and web renderer."""

import copy
import math
from typing import Any

from ...base import (Action, ActionOption, Context, GraphEdgeView,
                     GraphNodeView, GraphView, IllegalAction, LogEntry,
                     OutboxItem, Param, RenderModel, SeatRef, SeatView, Setup,
                     TokenView, Transition)
from ...primitives.turn import TurnOrder

PHASE = 'play'
FINISHED = 'finished'
FINISH = 'finish'
START = 'start'
MID = 'mid'
MIN_PLAYERS = 2
MAX_PLAYERS = 4
VERSION = 1
OUTER_RADIUS = 2.0
MID_RADIUS = 1.1


class GraphSampleGame:
    """Advance a token along a path to the shared finish."""

    slug = 'graph-sample-game'
    name = 'Graph Sample Game'
    version = VERSION
    min_players = MIN_PLAYERS
    max_players = MAX_PLAYERS
    capabilities = frozenset({'graph'})

    def validate_setup(self, options: dict[str, Any],
                       seats: tuple[SeatRef, ...]) -> None:
        if not self.min_players <= len(seats) <= self.max_players:
            raise ValueError(f'{self.name} seats {self.min_players} to '
                             f'{self.max_players} players.')
        if len({seat.position for seat in seats}) != len(seats):
            raise ValueError('Seat positions must be unique.')

    def setup(self, options: dict[str, Any], seats: tuple[SeatRef, ...],
              seed: int) -> Setup:
        self.validate_setup(options, seats)
        positions = {str(seat.position): f'{START}-{seat.position}'
                     for seat in seats}
        return Setup(
            state={'positions': positions, 'turns': 0,
                   'winner': None, 'over': False},
            private={seat.position: {} for seat in seats})

    def initial_phase(self) -> str:
        return PHASE

    def legal_actions(self, ctx: Context,
                      actor: int) -> tuple[ActionOption, ...]:
        if self.is_over(ctx) or ctx.active != actor:
            return ()
        next_node = self._next_node(ctx, actor)
        if next_node is None:
            return ()
        label = self._node_label(next_node)
        return (ActionOption(
            id='advance', label=f'Advance to {label}',
            params=(Param('node', 'Destination', options=(next_node,),
                          labels=(label,)),)),)

    def apply(self, ctx: Context, action: Action) -> Transition:
        if action.id != 'advance':
            raise IllegalAction(f'Unknown action {action.id!r}.')
        if action.actor != ctx.active:
            raise IllegalAction('It is not your turn.')
        next_node = self._next_node(ctx, action.actor)
        if next_node is None or action.params.get('node') != next_node:
            raise IllegalAction('That move is not available.')
        state = copy.deepcopy(ctx.state)
        state['positions'][str(action.actor)] = next_node
        state['turns'] = int(state.get('turns', 0)) + 1
        if next_node == FINISH:
            state['over'] = True
            state['winner'] = action.actor
            scores = self._scores_from_state(ctx, state)
            return Transition(

                state=state, active=None, phase=FINISHED, over=True,
                log=(LogEntry(f'{self._name(ctx, action.actor)} reaches '
                              'the finish.'),),
                outbox=(OutboxItem(kind='match_over',
                                   payload={'scores': scores}),))
        positions = tuple(seat.position for seat in ctx.seats)
        following = TurnOrder(positions).after(action.actor)
        return Transition(
            state=state, active=following, phase=PHASE,
            log=(LogEntry(f'{self._name(ctx, action.actor)} advances to '
                          f'{self._node_label(next_node)}.'),))

    def view(self, ctx: Context, position: int | None) -> RenderModel:
        seats = tuple(SeatView(
            position=seat.position, label=self._name(ctx, seat.position),
            is_active=seat.position == ctx.active) for seat in ctx.seats)
        actions = (self.legal_actions(ctx, position)
                   if position is not None else ())
        return RenderModel(
            board=self._graph(ctx), seats=seats, actions=actions,
            status=self._status(ctx))

    def summary(self, ctx: Context,
                position: int | None) -> dict[str, Any]:
        return {'scores': self.scores(ctx),
                'winner': ctx.state.get('winner')}

    def is_over(self, ctx: Context) -> bool:
        return bool(ctx.state.get('over'))

    def scores(self, ctx: Context) -> list[dict[str, Any]]:
        return self._scores_from_state(ctx, ctx.state)

    def _scores_from_state(self, ctx: Context,
                           state: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for seat in ctx.seats:
            node = state['positions'].get(str(seat.position), FINISH)
            distance = self._distance(node)
            rows.append({'position': seat.position,
                         'name': self._name(ctx, seat.position),
                         'distance': distance,
                         'total': 3 - distance})
        return sorted(rows, key=lambda row: (-row['total'],
                                             row['position']))

    def _graph(self, ctx: Context) -> GraphView:
        nodes = [GraphNodeView(id=FINISH, label='Finish', x=0.0, y=0.0,
                               kind=FINISH)]
        edges: list[GraphEdgeView] = []
        tokens: list[TokenView] = []
        count = max(len(ctx.seats), 1)
        for index, seat in enumerate(ctx.seats):
            angle = 2 * math.pi * index / count
            start = f'{START}-{seat.position}'
            mid = f'{MID}-{seat.position}'
            nodes.extend((
                GraphNodeView(start, f'Start {seat.position + 1}',
                              math.cos(angle) * OUTER_RADIUS,
                              math.sin(angle) * OUTER_RADIUS, START),
                GraphNodeView(mid, f'Middle {seat.position + 1}',
                              math.cos(angle) * MID_RADIUS,
                              math.sin(angle) * MID_RADIUS, MID),
            ))
            edges.extend((
                GraphEdgeView(start, mid, kind='path'),
                GraphEdgeView(mid, FINISH, kind='path'),
            ))
            tokens.append(TokenView(
                node=ctx.state['positions'][str(seat.position)],
                label=str(seat.position + 1), owner=seat.position))
        return GraphView(nodes=tuple(nodes), edges=tuple(edges),
                         tokens=tuple(tokens))

    def _next_node(self, ctx: Context, position: int) -> str | None:
        node = ctx.state['positions'].get(str(position))
        if node == f'{START}-{position}':
            return f'{MID}-{position}'
        if node == f'{MID}-{position}':
            return FINISH
        return None

    def _distance(self, node: str) -> int:
        if node == FINISH:
            return 0
        return 1 if node.startswith(f'{MID}-') else 2

    def _node_label(self, node: str) -> str:
        if node == FINISH:
            return 'Finish'
        return node.replace('-', ' ').title()

    def _name(self, ctx: Context, position: int) -> str:
        return ctx.seat(position).name or f'Seat {position + 1}'

    def _status(self, ctx: Context) -> str:
        if self.is_over(ctx):
            winner = ctx.state.get('winner')
            if winner is not None:
                return f'{self._name(ctx, int(winner))} wins.'
            return 'Game over.'
        if ctx.active is None:
            return 'No active seat.'
        return f'{self._name(ctx, ctx.active)} to advance.'

