"""A test-only game with an out-of-turn reaction window."""

import copy
from typing import Any

from bgb_engine import (Action, ActionOption, Context, IllegalAction,
                        LogEntry, OutboxItem, Param, PendingSpec, PendingView,
                        RenderModel, SeatRef, SeatView, Setup, Transition)
from bgb_engine.primitives.pending import for_seat
from bgb_engine.primitives.turn import TurnOrder
from games import registry

SLUG = 'pending-reaction-game'
PHASE = 'play'
REACTION = 'reaction'
FINISHED = 'finished'


class PendingReactionGame:
    """Open a reaction choice for the next seat, then finish the turn."""

    slug = SLUG
    name = 'Pending Reaction Game'
    version = 1
    min_players = 2
    max_players = 4
    capabilities = frozenset({'pending'})

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
        return Setup(
            state={'opened': False, 'resolved': False, 'over': False,
                   'reaction': '', 'turns': 0},
            private={seat.position: {} for seat in seats})

    def initial_phase(self) -> str:
        return PHASE

    def legal_actions(self, ctx: Context,
                      actor: int) -> tuple[ActionOption, ...]:
        if self.is_over(ctx):
            return ()
        if for_seat(ctx.pending, actor) is not None:
            return (ActionOption(
                id='react', label='React',
                params=(Param('answer', 'Answer', options=('accept',
                                                           'decline')),)),)
        if ctx.active != actor:
            return ()
        if not ctx.state.get('opened'):
            return (ActionOption(id='open', label='Open reaction'),)
        if ctx.state.get('resolved'):
            return (ActionOption(id='finish', label='Finish turn'),)
        return ()

    def apply(self, ctx: Context, action: Action) -> Transition:
        if action.id == 'open':
            return self._open(ctx, action)
        if action.id == 'react':
            return self._react(ctx, action)
        if action.id == 'finish':
            return self._finish(ctx, action)
        raise IllegalAction(f'Unknown action {action.id!r}.')

    def _open(self, ctx: Context, action: Action) -> Transition:
        if action.actor != ctx.active or ctx.state.get('opened'):
            raise IllegalAction('A reaction is already open.')
        positions = tuple(seat.position for seat in ctx.seats)
        target = TurnOrder(positions).after(action.actor)
        state = copy.deepcopy(ctx.state)
        state['opened'] = True
        return Transition(
            state=state, active=action.actor, phase=REACTION,
            pending=(PendingSpec(
                seat=target, kind='react', label='React to the turn',
                options=('accept', 'decline')),),
            log=(LogEntry(f'{self._name(ctx, action.actor)} opens a '
                          f'reaction for {self._name(ctx, target)}.'),))

    def _react(self, ctx: Context, action: Action) -> Transition:
        choice = for_seat(ctx.pending, action.actor)
        if choice is None:
            raise IllegalAction('You have no reaction to resolve.')
        answer = action.params.get('answer')
        if answer not in choice.options:
            raise IllegalAction('Pick one of the offered reactions.')
        state = copy.deepcopy(ctx.state)
        state['resolved'] = True
        state['reaction'] = answer
        positions = tuple(seat.position for seat in ctx.seats)
        next_actor = TurnOrder(positions).after(action.actor)
        return Transition(
            state=state, active=next_actor, phase=PHASE,
            pending=(PendingSpec(seat=action.actor, kind=choice.kind,
                                 close=True),),
            log=(LogEntry(f'{self._name(ctx, action.actor)} answers '
                          f'{answer}.'),))

    def _finish(self, ctx: Context, action: Action) -> Transition:
        if action.actor != ctx.active or not ctx.state.get('resolved'):
            raise IllegalAction('There is no resolved reaction to finish.')
        state = copy.deepcopy(ctx.state)
        state['turns'] = int(state.get('turns', 0)) + 1
        state['over'] = True
        scores = self._scores_from_state(ctx, state)
        return Transition(
            state=state, active=None, phase=FINISHED, over=True,
            log=(LogEntry('The reaction round is over.'),),
            outbox=(OutboxItem(kind='match_over',
                               payload={'scores': scores}),))

    def view(self, ctx: Context, position: int | None) -> RenderModel:
        choices = tuple(
            PendingView(kind=choice.kind, label=choice.label,
                        options=choice.options)
            for choice in ctx.pending if choice.seat == position)
        seats = tuple(SeatView(
            position=seat.position, label=self._name(ctx, seat.position),
            is_active=seat.position == ctx.active) for seat in ctx.seats)
        actions = (self.legal_actions(ctx, position)
                   if position is not None else ())
        return RenderModel(
            seats=seats, actions=actions,
            pending=choices[0] if choices else None,
            status=self._status(ctx, position))

    def summary(self, ctx: Context,
                position: int | None) -> dict[str, Any]:
        return {'scores': self.scores(ctx)}

    def is_over(self, ctx: Context) -> bool:
        return bool(ctx.state.get('over'))

    def scores(self, ctx: Context) -> list[dict[str, Any]]:
        return self._scores_from_state(ctx, ctx.state)

    def _scores_from_state(self, ctx: Context,
                           state: dict[str, Any]) -> list[dict[str, Any]]:
        return [{'position': seat.position,
                 'name': self._name(ctx, seat.position),
                 'reactions': int(bool(state.get('reaction')))}
                for seat in ctx.seats]

    def _name(self, ctx: Context, position: int) -> str:
        return ctx.seat(position).name or f'Seat {position + 1}'

    def _status(self, ctx: Context, position: int | None) -> str:
        if self.is_over(ctx):
            return 'Game over.'
        pending = next((choice for choice in ctx.pending
                        if choice.seat == position), None)
        if pending is not None:
            return f'{self._name(ctx, position)} must react.'
        if ctx.active is None:
            return 'No active seat.'
        return f'{self._name(ctx, ctx.active)} to act.'


def ensure_registered() -> None:
    """Register the fixture once for service-level tests."""
    try:
        registry.get(SLUG)
    except LookupError:
        registry.register(PendingReactionGame())
