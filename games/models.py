"""Matches, seats, actions, pending choices and the outbox.

A match holds the public state and the shared hidden state; a seat holds what
only that seat may see. Every action keeps the state it replaced, so it can be
undone without the game implementing anything.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from .constants import (GAME_SLUG_MAX_LENGTH, KIND_MAX_LENGTH,
                       LABEL_MAX_LENGTH, MATCH_NAME_MAX_LENGTH,
                       PHASE_MAX_LENGTH, ROLE_MAX_LENGTH,
                       SEAT_NAME_MAX_LENGTH, STATUS_MAX_LENGTH,
                       TYPE_MAX_LENGTH, UNDO_POLICY_MAX_LENGTH)


class MatchStatus(models.TextChoices):
    SETUP = 'SETUP', _('setup')
    ACTIVE = 'ACTIVE', _('active')
    FINISHED = 'FINISHED', _('finished')


class UndoPolicy(models.TextChoices):
    SAFE = 'SAFE', _('only actions that revealed nothing')
    ALL = 'ALL', _('every action')


class OutboxStatus(models.TextChoices):
    PENDING = 'PENDING', _('pending')
    SENT = 'SENT', _('sent')
    FAILED = 'FAILED', _('failed')
    SUPERSEDED = 'SUPERSEDED', _('superseded')


class Match(models.Model):
    """One table: a game definition playing in one Discord channel."""

    guild = models.ForeignKey('core.Guild', on_delete=models.CASCADE,
                              related_name='matches', verbose_name=_('guild'))
    host = models.ForeignKey(
        'core.Player', on_delete=models.SET_NULL, related_name='hosted_matches',
        blank=True, null=True, default=None, verbose_name=_('host'),
        help_text=_('The player who opened this table and may run it.'))
    channel_id = models.BigIntegerField(_('channel ID'))
    board_message_id = models.BigIntegerField(
        _('board message ID'), blank=True, null=True, default=None)
    slug = models.CharField(_('game'), max_length=GAME_SLUG_MAX_LENGTH)
    name = models.CharField(_('name'), max_length=MATCH_NAME_MAX_LENGTH,
                             blank=True, default='')

    options = models.JSONField(_('options'), default=dict, blank=True)
    state = models.JSONField(_('state'), default=dict, blank=True)
    hidden_state = models.JSONField(
        _('hidden state'), default=dict, blank=True,
        help_text=_('Shared hidden data, such as a deck order. Never rendered.'))
    version = models.PositiveIntegerField(_('version'), default=0)
    position = models.PositiveIntegerField(
        _('position'), default=0,
        help_text=_('Sequence of the action whose result is live; 0 is the setup.'))
    rules_version = models.PositiveIntegerField(_('rules version'), default=0)
    undo_policy = models.CharField(_('undo policy'),
                                    max_length=UNDO_POLICY_MAX_LENGTH,
                                   choices=UndoPolicy.choices,
                                   default=UndoPolicy.SAFE)
    status = models.CharField(_('status'), max_length=STATUS_MAX_LENGTH,
                              choices=MatchStatus.choices,
                              default=MatchStatus.SETUP)
    phase = models.CharField(_('phase'), max_length=PHASE_MAX_LENGTH,
                              blank=True)
    active_seat = models.ForeignKey(
        'games.Seat', on_delete=models.SET_NULL, related_name='+',
        verbose_name=_('active seat'), blank=True, null=True, default=None)
    last_needed_seats = models.JSONField(
        _('last needed seats'), default=list, blank=True,
        help_text=_('Seats that needed to act when the board was last posted.'))

    seed = models.BigIntegerField(_('seed'))
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    finished_at = models.DateTimeField(_('finished at'), blank=True, null=True,
                                       default=None)

    class Meta:
        verbose_name = _('match')
        verbose_name_plural = _('matches')
        ordering = ('-created_at',)
        indexes = [models.Index(fields=('guild', 'status'),
                                name='match_guild_status')]

    def __str__(self) -> str:
        if self.name:
            return f'{self.name} ({self.slug} #{self.pk})'
        return f'{self.slug} #{self.pk}'


class Seat(models.Model):
    """One player's place at a table; ``player`` is empty until claimed."""

    match = models.ForeignKey(Match, on_delete=models.CASCADE,
                              related_name='seats', verbose_name=_('match'))
    player = models.ForeignKey('core.Player', on_delete=models.SET_NULL,
                               related_name='seats', blank=True, null=True,
                               default=None, verbose_name=_('player'))
    display_name = models.CharField(_('server display name'),
                                    max_length=SEAT_NAME_MAX_LENGTH,
                                    blank=True, default='')
    position = models.PositiveSmallIntegerField(_('position'))
    role = models.CharField(_('role'), max_length=ROLE_MAX_LENGTH,
                            blank=True)
    private_state = models.JSONField(_('private state'), default=dict,
                                     blank=True)
    is_ready = models.BooleanField(_('ready'), default=False)
    eliminated = models.BooleanField(_('eliminated'), default=False)

    class Meta:
        verbose_name = _('seat')
        verbose_name_plural = _('seats')
        ordering = ('position',)
        constraints = [
            models.UniqueConstraint(fields=('match', 'position'),
                                    name='unique_seat_position'),
            models.UniqueConstraint(fields=('match', 'player'),
                                    condition=models.Q(player__isnull=False),
                                    name='unique_seat_player'),
        ]

    def __str__(self) -> str:
        return f'{self.match} seat {self.position}'


class Action(models.Model):
    """An appended action; the write path never updates one."""

    match = models.ForeignKey(Match, on_delete=models.CASCADE,
                              related_name='actions', verbose_name=_('match'))
    seq = models.PositiveIntegerField(_('sequence'))
    actor = models.ForeignKey('core.Player', on_delete=models.SET_NULL,
                              related_name='actions', blank=True, null=True,
                              default=None, verbose_name=_('actor'))
    type = models.CharField(_('type'), max_length=TYPE_MAX_LENGTH)
    payload = models.JSONField(_('payload'), default=dict, blank=True)
    result = models.JSONField(_('result'), default=dict, blank=True)
    random = models.BooleanField(_('used randomness'), default=False)
    revealed = models.BooleanField(_('revealed information'), default=False)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    class Meta:
        verbose_name = _('action')
        verbose_name_plural = _('actions')
        ordering = ('seq',)
        constraints = [
            models.UniqueConstraint(fields=('match', 'seq'),
                                    name='unique_action_seq'),
        ]

    def __str__(self) -> str:
        return f'{self.match} #{self.seq} {self.type}'


class ActionSnapshot(models.Model):
    """The persisted state an action replaced, kept so it can be undone."""

    action = models.OneToOneField(Action, on_delete=models.CASCADE,
                                  related_name='snapshot',
                                  verbose_name=_('action'))
    data = models.JSONField(_('data'))

    class Meta:
        verbose_name = _('action snapshot')
        verbose_name_plural = _('action snapshots')

    def __str__(self) -> str:
        return f'snapshot of {self.action}'


class PendingChoice(models.Model):
    """A choice opened for one seat, still waiting for its answer."""

    match = models.ForeignKey(Match, on_delete=models.CASCADE,
                              related_name='pending_choices',
                              verbose_name=_('match'))
    seat = models.ForeignKey(Seat, on_delete=models.CASCADE,
                             related_name='pending_choices',
                             verbose_name=_('seat'))
    kind = models.CharField(_('kind'), max_length=KIND_MAX_LENGTH)
    label = models.CharField(_('label'), max_length=LABEL_MAX_LENGTH,
                              blank=True)
    options = models.JSONField(_('options'), default=list, blank=True)
    context = models.JSONField(_('context'), default=dict, blank=True)
    deadline = models.DateTimeField(_('deadline'), blank=True, null=True,
                                    default=None)
    response = models.JSONField(_('response'), blank=True, null=True,
                                default=None)
    resolved_at = models.DateTimeField(_('resolved at'), blank=True, null=True,
                                       default=None)

    class Meta:
        verbose_name = _('pending choice')
        verbose_name_plural = _('pending choices')
        ordering = ('pk',)
        indexes = [models.Index(fields=('match', 'resolved_at'),
                                name='pending_match_resolved')]

    def __str__(self) -> str:
        return f'{self.kind} for {self.seat}'


class OutboxMessage(models.Model):
    """A Discord post waiting for the bot process to claim it."""

    match = models.ForeignKey(Match, on_delete=models.CASCADE,
                              related_name='outbox', verbose_name=_('match'))
    kind = models.CharField(_('kind'), max_length=KIND_MAX_LENGTH)
    payload = models.JSONField(_('payload'), default=dict, blank=True)
    status = models.CharField(_('status'), max_length=STATUS_MAX_LENGTH,
                              choices=OutboxStatus.choices,
                              default=OutboxStatus.PENDING)
    attempts = models.PositiveSmallIntegerField(_('attempts'), default=0)
    claimed_at = models.DateTimeField(_('claimed at'), blank=True, null=True,
                                      default=None)
    sent_at = models.DateTimeField(_('sent at'), blank=True, null=True,
                                   default=None)
    message_ids = models.JSONField(_('message IDs'), default=list, blank=True)
    error = models.TextField(_('error'), blank=True)
    next_attempt_at = models.DateTimeField(_('next attempt at'), blank=True,
                                           null=True, default=None)

    class Meta:
        verbose_name = _('outbox message')
        verbose_name_plural = _('outbox messages')
        ordering = ('pk',)
        indexes = [models.Index(fields=('status', 'next_attempt_at'),
                                name='outbox_status_next_attempt')]

    def __str__(self) -> str:
        return f'{self.kind} ({self.status})'

