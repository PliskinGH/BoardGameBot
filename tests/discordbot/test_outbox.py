"""Tests for claiming and delivering the outbox."""

import asyncio
from datetime import timedelta
from unittest import mock

import discord
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from discordbot import outbox_worker
from games.models import OutboxMessage, OutboxStatus
from games.services import matches, outbox
from tests.discordbot.fakes import bot_match, setup_match
from tests.support import NoDiscordMixin


class ClaimTests(NoDiscordMixin, TestCase):
    def setUp(self):
        self.match, _host, _guest = setup_match()
        OutboxMessage.objects.filter(match=self.match).delete()

    def test_a_free_row_is_claimed(self):
        row = outbox.enqueue(self.match)[0]

        [claimed] = outbox.claim_batch()

        self.assertEqual(claimed.pk, row.pk)
        self.assertIsNotNone(claimed.claimed_at)

    def test_a_fresh_claim_is_left_alone(self):
        outbox.enqueue(self.match)
        outbox.claim_batch()

        self.assertEqual(outbox.claim_batch(), [])

    def test_a_stale_claim_is_taken_over(self):
        outbox.enqueue(self.match)
        [claimed] = outbox.claim_batch()
        OutboxMessage.objects.filter(pk=claimed.pk).update(
            claimed_at=timezone.now() - timedelta(
                seconds=outbox.OUTBOX_CLAIM_TIMEOUT_SECONDS + 1))

        [again] = outbox.claim_batch()

        self.assertEqual(again.pk, claimed.pk)

    def test_superseded_rows_are_never_claimed(self):
        outbox.enqueue(self.match)
        outbox.supersede(self.match)

        self.assertEqual(outbox.claim_batch(), [])

    def test_older_board_refreshes_collapse_into_the_newest(self):
        first, second, third = (outbox.enqueue(self.match)[0]
                                for _ in range(3))

        claimed = outbox.claim_batch()

        self.assertEqual([row.pk for row in claimed], [third.pk])
        self.assertEqual(
            OutboxMessage.objects.filter(
                pk__in=[first.pk, second.pk],
                status=OutboxStatus.SUPERSEDED).count(), 2)

    def test_a_failed_row_is_claimed_when_due(self):
        row = outbox.enqueue(self.match)[0]
        OutboxMessage.objects.filter(pk=row.pk).update(
            status=OutboxStatus.FAILED,
            next_attempt_at=timezone.now() - timedelta(seconds=1))

        [claimed] = outbox.claim_batch()

        self.assertEqual(claimed.pk, row.pk)

    def test_a_failed_row_is_not_claimed_before_its_time(self):
        row = outbox.enqueue(self.match)[0]
        OutboxMessage.objects.filter(pk=row.pk).update(
            status=OutboxStatus.FAILED,
            next_attempt_at=timezone.now() + timedelta(minutes=5))

        self.assertEqual(outbox.claim_batch(), [])


class MarkTests(NoDiscordMixin, TestCase):
    def setUp(self):
        self.match, _host, _guest = setup_match()
        OutboxMessage.objects.filter(match=self.match).delete()

    def test_a_failure_schedules_a_retry(self):
        row = outbox.enqueue(self.match)[0]

        outbox.mark_failed(row, 'boom')
        row.refresh_from_db()

        self.assertEqual(row.status, OutboxStatus.FAILED)
        self.assertEqual(row.attempts, 1)
        self.assertIsNotNone(row.next_attempt_at)
        self.assertEqual(row.error, 'boom')

    def test_the_last_failure_gives_the_post_up(self):
        row = outbox.enqueue(self.match)[0]
        OutboxMessage.objects.filter(pk=row.pk).update(
            attempts=outbox.OUTBOX_MAX_ATTEMPTS - 1)
        row.refresh_from_db()

        outbox.mark_failed(row, 'boom')
        row.refresh_from_db()

        self.assertEqual(row.attempts, outbox.OUTBOX_MAX_ATTEMPTS)
        self.assertIsNone(row.next_attempt_at)

    def test_sent_keeps_the_message_ids(self):
        row = outbox.enqueue(self.match)[0]

        outbox.mark_sent(row, [77])
        row.refresh_from_db()

        self.assertEqual(row.status, OutboxStatus.SENT)
        self.assertEqual(row.message_ids, [77])


class _Response:
    status = 404
    reason = 'Not Found'


@override_settings(WEB_BASE_URL='https://example.test')
class DeliveryTests(NoDiscordMixin, TransactionTestCase):
    def setUp(self):
        self.match, self.players = bot_match()
        OutboxMessage.objects.filter(match=self.match).delete()
        self.bot = mock.Mock()

    def _run(self, send, edit, delete=None):
        with mock.patch.object(outbox_worker.discord_api, 'send_embed',
                               send), \
                mock.patch.object(outbox_worker.discord_api, 'edit_embed',
                                  edit), \
                mock.patch.object(outbox_worker.discord_api, 'delete_message',
                                  delete or mock.AsyncMock()):
            return asyncio.run(outbox_worker.run_once(self.bot))

    def test_the_board_is_posted_once_then_edited(self):
        send = mock.AsyncMock(return_value=900)
        edit = mock.AsyncMock()
        delete = mock.AsyncMock()
        outbox.enqueue(self.match)

        self.assertEqual(self._run(send, edit, delete), 1)

        self.match.refresh_from_db()
        self.assertEqual(self.match.board_message_id, 900)
        self.assertEqual(self.match.last_needed_seats,
                         [self.match.active_seat.position])
        send.assert_awaited_once()
        edit.assert_not_awaited()
        delete.assert_not_awaited()

        outbox.enqueue(self.match)
        self.assertEqual(self._run(send, edit, delete), 1)

        self.assertEqual(send.await_count, 1)
        edit.assert_awaited_once()
        self.assertEqual(edit.await_args.args[2], 900)

    def test_a_new_active_seat_replaces_and_pings(self):
        send = mock.AsyncMock(return_value=901)
        edit = mock.AsyncMock()
        delete = mock.AsyncMock()
        self.match.board_message_id = 900
        self.match.last_needed_seats = [0]
        self.match.save(update_fields=['board_message_id', 'last_needed_seats'])
        self.match.active_seat = self.match.seats.get(position=1)
        self.match.save(update_fields=['active_seat'])
        outbox.enqueue(self.match)

        self.assertEqual(self._run(send, edit, delete), 1)

        self.match.refresh_from_db()
        self.assertEqual(self.match.board_message_id, 901)
        self.assertEqual(self.match.last_needed_seats, [1])
        delete.assert_awaited_once_with(self.bot, self.match.channel_id, 900)
        send.assert_awaited_once()
        self.assertIn('<@43>', send.await_args.kwargs['content'])
        edit.assert_not_awaited()

    def test_shrinking_the_needed_set_edits_without_a_ping(self):
        send = mock.AsyncMock(return_value=904)
        edit = mock.AsyncMock()
        delete = mock.AsyncMock()
        self.match.board_message_id = 900
        self.match.last_needed_seats = [0, 1]
        self.match.save(update_fields=['board_message_id', 'last_needed_seats'])
        outbox.enqueue(self.match)

        self.assertEqual(self._run(send, edit, delete), 1)

        self.match.refresh_from_db()
        self.assertEqual(self.match.last_needed_seats, [0])
        edit.assert_awaited_once()
        send.assert_not_awaited()
        delete.assert_not_awaited()

    def test_a_deleted_board_is_posted_again_without_a_ping(self):
        send = mock.AsyncMock(return_value=902)
        edit = mock.AsyncMock(
            side_effect=discord.NotFound(_Response(), 'gone'))
        delete = mock.AsyncMock()
        self.match.board_message_id = 900
        self.match.last_needed_seats = [self.match.active_seat.position]
        self.match.save(update_fields=['board_message_id', 'last_needed_seats'])
        outbox.enqueue(self.match)

        self.assertEqual(self._run(send, edit, delete), 1)

        self.match.refresh_from_db()
        self.assertEqual(self.match.board_message_id, 902)
        send.assert_awaited_once()
        self.assertIsNone(send.await_args.kwargs.get('content'))
        delete.assert_not_awaited()

    def test_a_refused_post_is_recorded_for_a_retry(self):
        send = mock.AsyncMock(side_effect=RuntimeError('no channel'))
        edit = mock.AsyncMock()
        row = outbox.enqueue(self.match)[0]

        self._run(send, edit)

        row.refresh_from_db()
        self.assertEqual(row.status, OutboxStatus.FAILED)
        self.assertEqual(row.attempts, 1)
        self.assertIn('no channel', row.error)

    def test_a_finished_match_posts_a_recap(self):
        send = mock.AsyncMock(return_value=903)
        edit = mock.AsyncMock()
        outbox.enqueue(self.match)
        self._run(send, edit)
        OutboxMessage.objects.filter(match=self.match).delete()
        send.reset_mock()
        edit.reset_mock()

        matches.close_match(self.match.pk, self.players[0])
        self.assertEqual(self._run(send, edit), 2)

        self.assertEqual(send.await_count, 1)
        embed = send.await_args.args[2]
        self.assertIn('Game over.', embed.description)

