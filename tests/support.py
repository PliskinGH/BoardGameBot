"""Drive a game definition in memory, and keep the tests off the network."""

import asyncio
from unittest import mock

from asgiref.sync import sync_to_async
from django.db import connections

from bgb_engine.base import Action, Context, PendingRef, SeatRef


def seats(count: int) -> tuple[SeatRef, ...]:
    """Return ``count`` named seats in play order."""
    return tuple(SeatRef(position=index, name=f'P{index + 1}')
                 for index in range(count))


class Table:
    """An in-memory match; P2's services take over this role."""

    def __init__(self, definition, seat_refs, options=None, seed=7):
        self.definition = definition
        self.seats = tuple(seat_refs)
        self.options = dict(options or {})
        self.seed = seed
        setup = definition.setup(self.options, self.seats, seed)
        self.state = setup.state
        self.hidden = setup.hidden
        self.private = setup.private
        self.phase = definition.initial_phase()
        self.active = self.seats[0].position if self.seats else None
        self.pending = ()

    def context(self) -> Context:
        return Context(slug=self.definition.slug, seed=self.seed,
                       options=self.options, state=self.state,
                       hidden=self.hidden, private=self.private,
                       seats=self.seats, phase=self.phase,
                       active=self.active, pending=self.pending)

    def legal_actions(self, actor=None):
        return self.definition.legal_actions(
            self.context(), self.active if actor is None else actor)

    def apply(self, action_id, params=None, actor=None):
        actor = self.active if actor is None else actor
        transition = self.definition.apply(
            self.context(),
            Action(actor=actor, id=action_id, params=dict(params or {})))
        self.state = transition.state
        self.hidden = {**self.hidden, **transition.hidden}
        for position, patch in transition.private.items():
            self.private[position] = {**self.private.get(position, {}),
                                      **patch}
        self.pending = self._pending_after(transition.pending)
        if transition.over:
            self.active = None
        elif transition.active is not None:
            self.active = transition.active
        if transition.phase is not None:
            self.phase = transition.phase
        return transition

    def over(self) -> bool:
        return self.definition.is_over(self.context())

    def _pending_after(self, specs):
        pending = list(self.pending)
        for spec in specs:
            pending = [choice for choice in pending
                       if not (choice.seat == spec.seat
                               and choice.kind == spec.kind)]
            if not spec.close:
                pending.append(PendingRef(seat=spec.seat, kind=spec.kind,
                                          label=spec.label,
                                          options=tuple(spec.options)))
        return tuple(pending)


class NetworkAccessDenied(AssertionError):
    """A test tried to reach the network, which must never happen."""


def _no_network(*args, **kwargs):
    """Refuse an outgoing request, so a forgotten mock fails the test."""
    raise NetworkAccessDenied(
        'A test made a real HTTP request without mocking it. Patch the '
        'discord_api helper it calls, or the service beneath it.')


class NoNetworkMixin:
    """Block the network for the whole class, whichever base it is mixed into.

    Applied in ``setUpClass`` rather than ``setUp`` so a subclass that forgets
    to call ``super().setUp()`` is still guarded.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        patcher = mock.patch('requests.Session.send', _no_network)
        patcher.start()
        cls.addClassCleanup(patcher.stop)


class NoDiscordMixin:
    """Block discord.py's HTTP client for the whole class."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()

        async def _no_discord(*args: object, **kwargs: object) -> None:
            raise NetworkAccessDenied(
                'A test tried to reach Discord without mocking the seam.')

        patcher = mock.patch('discord.http.HTTPClient.request', _no_discord)
        patcher.start()
        cls.addClassCleanup(patcher.stop)

    @classmethod
    def tearDownClass(cls) -> None:
        """Close the ORM thread's connection, which would block the test DB."""
        asyncio.run(sync_to_async(connections.close_all,
                                  thread_sensitive=True)())
        super().tearDownClass()
