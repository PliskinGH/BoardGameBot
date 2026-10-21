"""Queue the Discord work a write produces."""

from collections.abc import Iterable
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from games.engine.base import OutboxItem
from games.models import Match, OutboxMessage, OutboxStatus

BOARD_UPDATE = 'board_update'
MATCH_OVER = 'match_over'

# How many posts a worker takes at once, and when it gives one up.
OUTBOX_BATCH = 10
OUTBOX_CLAIM_TIMEOUT_SECONDS = 120
OUTBOX_MAX_ATTEMPTS = 5
OUTBOX_RETRY_BASE_SECONDS = 2
OUTBOX_RETRY_FACTOR = 2
OUTBOX_RETRY_MAX_SECONDS = 300
OUTBOX_ERROR_LIMIT = 1000


def enqueue(match: Match, items: Iterable[OutboxItem] = (), *,
            update_board: bool = True) -> list[OutboxMessage]:
    """Append the outbox rows of a write, including the board refresh."""
    messages = []
    if update_board:
        messages.append(OutboxMessage(match=match, kind=BOARD_UPDATE,
                                      payload={}))
    messages.extend(OutboxMessage(match=match, kind=item.kind,
                                  payload=item.payload)
                    for item in items)
    OutboxMessage.objects.bulk_create(messages)
    return messages


def supersede(match: Match) -> int:
    """Drop the queued but unsent work of a match, e.g. after an undo."""
    return (match.outbox.filter(status=OutboxStatus.PENDING)
            .update(status=OutboxStatus.SUPERSEDED))


def _claimable(now: datetime) -> Q:
    """Return the rows a worker may take: free, stale, or due a retry."""
    stale = now - timedelta(seconds=OUTBOX_CLAIM_TIMEOUT_SECONDS)
    return (Q(status=OutboxStatus.PENDING, claimed_at__isnull=True)
            | Q(status=OutboxStatus.PENDING, claimed_at__lt=stale)
            | Q(status=OutboxStatus.FAILED, next_attempt_at__lte=now))


@transaction.atomic
def claim_batch(limit: int = OUTBOX_BATCH,
                now: datetime | None = None) -> list[OutboxMessage]:
    """Take up to ``limit`` due rows, skipping the ones another worker holds.

    Older board refreshes of a match are superseded by the newest one of the
    batch, so a burst of changes costs one edit instead of one per change.
    """
    moment = now or timezone.now()
    rows = list(OutboxMessage.objects.select_for_update(skip_locked=True)
                .filter(_claimable(moment)).order_by('pk')[:limit])
    newest: dict[int, OutboxMessage] = {}
    for row in rows:
        if row.kind == BOARD_UPDATE:
            newest[row.match_id] = row
    claimed = []
    for row in rows:
        if row.kind == BOARD_UPDATE and newest[row.match_id].pk != row.pk:
            row.status = OutboxStatus.SUPERSEDED
            row.claimed_at = None
            row.save(update_fields=['status', 'claimed_at'])
            continue
        row.claimed_at = moment
        row.save(update_fields=['claimed_at'])
        claimed.append(row)
    return claimed


def mark_sent(message: OutboxMessage,
              message_ids: Iterable[int] = ()) -> OutboxMessage:
    """Record the messages a post produced."""
    message.status = OutboxStatus.SENT
    message.sent_at = timezone.now()
    message.claimed_at = None
    message.message_ids = [int(pk) for pk in message_ids]
    message.error = ''
    message.save(update_fields=['status', 'sent_at', 'claimed_at',
                                'message_ids', 'error'])
    return message


def mark_failed(message: OutboxMessage, reason: str) -> OutboxMessage:
    """Record a failed attempt and schedule the next one, or give the post up."""
    message.attempts += 1
    message.claimed_at = None
    message.error = str(reason)[:OUTBOX_ERROR_LIMIT]
    message.status = OutboxStatus.FAILED
    if message.attempts >= OUTBOX_MAX_ATTEMPTS:
        message.next_attempt_at = None
    else:
        delay = min(
            OUTBOX_RETRY_BASE_SECONDS
            * OUTBOX_RETRY_FACTOR ** (message.attempts - 1),
            OUTBOX_RETRY_MAX_SECONDS)
        message.next_attempt_at = timezone.now() + timedelta(seconds=delay)
    message.save(update_fields=['status', 'attempts', 'claimed_at', 'error',
                                'next_attempt_at'])
    return message
