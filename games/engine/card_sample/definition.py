"""A minimal numbered-card scoring game, written to exercise the framework.

CardSampleGame is not meant to ship: it uses hands, shared hidden state,
counters, phases, turn order and a pending choice, which is the surface a real
game needs. It is an original sample, not an adaptation of a published game.
"""

import copy
from typing import Any

from ..base import (Action, ActionOption, CardView, Context, IllegalAction,
                    LogEntry, OutboxItem, Param, PendingSpec, PendingView,
                    RenderModel, SeatRef, SeatView, Setup, Transition, ZoneView)
from ..primitives.counters import Counters
from ..primitives.pending import for_seat
from ..primitives.phases import PhaseMachine
from ..primitives.projection import hand_view
from ..primitives.turn import TurnOrder
from ..primitives.zones import Card, find, shuffled

PHASES = PhaseMachine(('play', 'finished'))
DECK_VALUES = (0, 1, 2, 3, 4, 5)
STARTING_CARDS = 3
DECK_ROUNDS = 2
STARTING_CARDS_MIN = 1
STARTING_CARDS_MAX = 5
DECK_ROUNDS_MIN = 1
DECK_ROUNDS_MAX = 5
MIN_PLAYERS = 2
MAX_PLAYERS = 4
VERSION = 1
SWAP = 0
COINS = 'coins'


class CardSampleGame:
    """Play a card to score its value; the swap card trades counters."""

    slug = 'card-sample-game'
    name = 'Card Sample Game'
    version = VERSION
    min_players = MIN_PLAYERS
    max_players = MAX_PLAYERS
    capabilities = frozenset({'hands', 'counters', 'pending', 'private'})

    def validate_setup(self, options: dict[str, Any],
                       seats: tuple[SeatRef, ...]) -> None:
        count = options.get('starting_cards', STARTING_CARDS)
        if not isinstance(count, int) or not (
                STARTING_CARDS_MIN <= count <= STARTING_CARDS_MAX):
            raise ValueError(
                f'starting_cards must be an integer from '
                f'{STARTING_CARDS_MIN} to {STARTING_CARDS_MAX}.')
        rounds = options.get('deck_rounds', DECK_ROUNDS)
        if not isinstance(rounds, int) or not (
                DECK_ROUNDS_MIN <= rounds <= DECK_ROUNDS_MAX):
            raise ValueError(
                f'deck_rounds must be an integer from '
                f'{DECK_ROUNDS_MIN} to {DECK_ROUNDS_MAX}.')
        if not self.min_players <= len(seats) <= self.max_players:
            raise ValueError(f'{self.name} seats {self.min_players} to '
                             f'{self.max_players} players.')
        positions = [seat.position for seat in seats]
        if len(set(positions)) != len(positions):
            raise ValueError('Seat positions must be unique.')

    def setup(self, options: dict[str, Any], seats: tuple[SeatRef, ...],
              seed: int) -> Setup:
        self.validate_setup(options, seats)
        count = options.get('starting_cards', STARTING_CARDS)
        rounds = options.get('deck_rounds', DECK_ROUNDS)
        deck = shuffled(self.deck(len(seats), rounds), seed=seed, salt='deal')
        private = {}
        for seat in seats:
            hand, deck = deck[:count], deck[count:]
            private[seat.position] = {
                'hand': [card.to_dict() for card in hand]}
        state = {
            'counters': {COINS: [0] * len(seats)},
            'discard': [],
            'deck_count': len(deck),
        }
        hidden = {'deck': [card.to_dict() for card in deck]}
        return Setup(state=state, hidden=hidden, private=private)

    def deck(self, player_count: int,
             rounds: int = DECK_ROUNDS) -> list[Card]:
        """Return the cards a table of ``player_count`` plays with."""
        cards = []
        for index in range(len(DECK_VALUES) * rounds * player_count):
            value = DECK_VALUES[index % len(DECK_VALUES)]
            label = 'Swap' if value == SWAP else str(value)
            cards.append(Card(id=f'c{index:02d}', label=label, value=value))
        return cards

    def initial_phase(self) -> str:
        return PHASES.first

    def legal_actions(self, ctx: Context,
                      actor: int) -> tuple[ActionOption, ...]:
        if ctx.active != actor or self.is_over(ctx):
            return ()
        choice = for_seat(ctx.pending, actor)
        if choice is not None:
            return (ActionOption(
                id='resolve_choice', label=choice.label,
                params=(Param('target', 'Target', kind='seat',
                              options=choice.options),)),)
        hand = self._hand(ctx, actor)
        if not hand:
            return (ActionOption(id='pass', label='Pass'),)
        return (ActionOption(
            id='play_card', label='Play a card',
            params=(Param('card', 'Card', kind='card',
                          options=tuple(card['id'] for card in hand)),)),)

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
        private = {position: copy.deepcopy(values)
                   for position, values in ctx.private.items()}

        if action.id == 'play_card':
            return self._play(ctx, action, state, hidden, private)
        if action.id == 'resolve_choice':
            return self._resolve(ctx, action, state, hidden, private)
        return self._pass(ctx, action, state, hidden, private)

    def view(self, ctx: Context, position: int | None) -> RenderModel:
        state = ctx.state
        counters = Counters.from_dict(state.get('counters', {}))
        zones = []
        if position is not None:
            cards = [Card.from_dict(entry)
                     for entry in self._hand(ctx, position)]
            visible, hidden_count = hand_view(cards, owned=True)
            zones.append(ZoneView(
                kind='hand', label='Your hand',
                cards=tuple(CardView(id=card.id, label=card.label,
                                     value=card.value) for card in visible),
                hidden_count=hidden_count, private=True))
        zones.append(ZoneView(
            kind='discard', label='Discard',
            cards=tuple(CardView(id=card['id'], label=card['label'],
                                 value=card['value'])
                        for card in state.get('discard', []))))
        zones.append(ZoneView(kind='deck', label='Deck',
                              hidden_count=state.get('deck_count', 0)))

        seats = []
        for seat in ctx.seats:
            owned = seat.position == position
            _, hidden_count = hand_view(
                [Card.from_dict(entry)
                 for entry in self._hand(ctx, seat.position)], owned=owned)
            seats.append(SeatView(
                position=seat.position,
                label=self._name(ctx, seat.position),
                is_active=seat.position == ctx.active,
                counters={COINS: counters.get(COINS, seat.position)},
                hidden_cards=hidden_count or 0))

        choice = for_seat(ctx.pending, position) if position is not None else None
        pending = (PendingView(kind=choice.kind, label=choice.label,
                               options=choice.options) if choice else None)
        actions = (self.legal_actions(ctx, position)
                   if position is not None else ())
        return RenderModel(zones=tuple(zones), seats=tuple(seats),
                           actions=actions, pending=pending,
                           status=self._status(ctx))

    def summary(self, ctx: Context,
                position: int | None) -> dict[str, Any]:
        return {'phase': ctx.phase, 'active': ctx.active,
                'scores': self.scores(ctx)}

    def is_over(self, ctx: Context) -> bool:
        if ctx.pending:
            return False
        if ctx.state.get('over'):
            return True
        return (ctx.state.get('deck_count', 0) == 0
                and all(not values.get('hand')
                        for values in ctx.private.values()))

    def scores(self, ctx: Context) -> list[dict[str, Any]]:
        counters = Counters.from_dict(ctx.state.get('counters', {}))
        rows = [{'position': seat.position,
                 'name': self._name(ctx, seat.position),
                 'coins': counters.get(COINS, seat.position)}
                for seat in ctx.seats]
        return sorted(rows, key=lambda row: row['coins'], reverse=True)

    def _play(self, ctx: Context, action: Action, state: dict[str, Any],
              hidden: dict[str, Any], private: dict[int, dict[str, Any]]) -> Transition:
        card_id = action.params.get('card')
        if not isinstance(card_id, str):
            raise IllegalAction('Pick one of your cards.')
        hand = private[action.actor]['hand']
        card = find([Card.from_dict(entry) for entry in hand], card_id)
        if card is None:
            raise IllegalAction('That card is not in your hand.')
        hand = [entry for entry in hand if entry['id'] != card_id]
        private[action.actor]['hand'] = hand
        state['discard'].append(card.to_dict())
        log = [LogEntry(f'{self._name(ctx, action.actor)} plays {card.label}.')]

        if card.value == SWAP:
            targets = tuple(seat.position for seat in ctx.seats
                            if seat.position != action.actor)
            return Transition(
                state=state, hidden=hidden,
                private={action.actor: {'hand': hand}},
                pending=(PendingSpec(
                    seat=action.actor, kind='swap_target',
                    label='Swap counters with which seat?',
                    options=targets),),
                log=tuple(log), active=action.actor)
        counters = Counters.from_dict(state['counters'])
        state['counters'] = counters.with_add(
            COINS, action.actor, card.value).as_dict()
        return self._end_turn(ctx, state, hidden, private, action.actor, log)

    def _resolve(self, ctx: Context, action: Action, state: dict[str, Any],
                 hidden: dict[str, Any], private: dict[int, dict[str, Any]]) -> Transition:
        choice = for_seat(ctx.pending, action.actor)
        if choice is None:
            raise IllegalAction('You have no choice to resolve.')
        target = action.params.get('target')
        if not isinstance(target, int):
            raise IllegalAction('Pick one of the offered seats.')
        if target not in choice.options:
            raise IllegalAction('That target is not offered.')
        counters = Counters.from_dict(state['counters'])
        state['counters'] = counters.with_swap(
            COINS, action.actor, target).as_dict()
        log = [LogEntry(f'{self._name(ctx, action.actor)} swaps counters with '
                        f'{self._name(ctx, target)}.')]
        close = PendingSpec(seat=action.actor, kind=choice.kind, close=True)
        return self._end_turn(ctx, state, hidden, private, action.actor, log,
                              pending=(close,))

    def _pass(self, ctx: Context, action: Action, state: dict[str, Any],
              hidden: dict[str, Any], private: dict[int, dict[str, Any]]) -> Transition:
        log = [LogEntry(f'{self._name(ctx, action.actor)} passes.')]
        return self._end_turn(ctx, state, hidden, private, action.actor, log,
                              draw=False)

    def _end_turn(self, ctx: Context, state: dict[str, Any],
                  hidden: dict[str, Any], private: dict[int, dict[str, Any]],
                  actor: int, log: list[LogEntry], *, draw: bool = True,
                  pending: tuple[PendingSpec, ...] = ()) -> Transition:
        if draw and hidden.get('deck'):
            deck = [Card.from_dict(entry) for entry in hidden['deck']]
            drawn, deck = deck[0], deck[1:]
            private[actor]['hand'] = private[actor]['hand'] + [drawn.to_dict()]
            hidden['deck'] = [card.to_dict() for card in deck]
            state['deck_count'] = len(deck)
        patch = {actor: {'hand': private[actor]['hand']}}

        over = (state['deck_count'] == 0
                and all(not values.get('hand')
                        for values in private.values()))
        if over:
            return Transition(
                state=state, hidden=hidden, private=patch, pending=pending,
                log=tuple(log), outbox=(OutboxItem(
                    kind='match_over',
                    payload={'scores': self._scores_from_state(ctx, state)}),),
                active=None, phase=PHASES.last, over=True)
        positions = tuple(seat.position for seat in ctx.seats)
        return Transition(state=state, hidden=hidden, private=patch,
                          pending=pending, log=tuple(log),
                          active=TurnOrder(positions).after(actor),
                          phase=PHASES.first)

    def _scores_from_state(self, ctx: Context,
                           state: dict[str, Any]) -> list[dict[str, Any]]:
        counters = Counters.from_dict(state.get('counters', {}))
        return [{'position': seat.position,
                 'name': self._name(ctx, seat.position),
                 'coins': counters.get(COINS, seat.position)}
                for seat in ctx.seats]

    def _hand(self, ctx: Context, position: int) -> list[dict[str, Any]]:
        return list(ctx.private.get(position, {}).get('hand', []))

    def _name(self, ctx: Context, position: int) -> str:
        seat = ctx.seat(position)
        return seat.name or f'Seat {position + 1}'

    def _status(self, ctx: Context) -> str:
        if self.is_over(ctx):
            return 'Game over.'
        if ctx.active is None:
            return 'No active seat.'
        return f'{self._name(ctx, ctx.active)} to act.'


