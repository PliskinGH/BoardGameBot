"""Deliver the Discord posts the write path queued."""

import asyncio
import logging

import discord
from discord.ext import commands

from games.models import Match, OutboxMessage
from games.services import outbox
from games.services.contexts import definition_for
from games.services.log import BOARD_LIMIT, entries as log_entries
from games.services.projections import render_model, summary

from . import db, discord_api, embeds, views

logger = logging.getLogger(__name__)

POLL_SECONDS = 1.0


def _match(match_id: int) -> Match | None:
    """Return the match of a post, with what rendering it needs."""
    return (Match.objects.select_related('guild', 'active_seat__player')
            .filter(pk=match_id).first())


def _board_embed(match: Match) -> discord.Embed:
    """Render the public board of a match from its current state."""
    return embeds.board_embed(
        match, render_model(match, None), definition_for(match).name,
        pending=views.pending_choice(match),
        log=log_entries(match, limit=BOARD_LIMIT),
        web_url=views.web_url(match))


def _recap_embed(match: Match) -> discord.Embed:
    """Render the final scores of a finished match."""
    return embeds.recap_embed(
        match, summary(match, None), definition_for(match).name,
        views.web_url(match))


def _store_board(match: Match, message_id: int,
                 needed: set[int]) -> None:
    """Remember the board message and the seats that needed to act."""
    match.board_message_id = message_id
    match.last_needed_seats = sorted(needed)
    match.save(update_fields=['board_message_id', 'last_needed_seats'])


def _remember_needed(match: Match, needed: set[int]) -> None:
    """Remember the seats that needed to act after an edit."""
    match.last_needed_seats = sorted(needed)
    match.save(update_fields=['last_needed_seats'])


async def deliver(bot: commands.Bot, message: OutboxMessage) -> None:
    """Send or edit the message one outbox row describes."""
    match = await db.run_db(_match, message.match_id)
    if match is None:
        raise ValueError('The match of this post is gone.')
    if message.kind == outbox.BOARD_UPDATE:
        embed = await db.run_db(_board_embed, match)
        view = views.board_view(match)
        needed = await db.run_db(views.needed_seats, match)
        previous = set(match.last_needed_seats or [])
        new = needed - previous
        content = (await db.run_db(views.turn_mentions, match, new)
                   if new else '')
        if new:
            if match.board_message_id:
                try:
                    await discord_api.delete_message(
                        bot, match.channel_id, match.board_message_id)
                except discord.NotFound:
                    pass
            message_id = await discord_api.send_embed(
                bot, match.channel_id, embed, view, content=content or None)
            await db.run_db(_store_board, match, message_id, needed)
            message.message_ids = [message_id]
            return
        if match.board_message_id:
            try:
                await discord_api.edit_embed(
                    bot, match.channel_id, match.board_message_id, embed, view)
            except discord.NotFound:
                pass
            else:
                await db.run_db(_remember_needed, match, needed)
                message.message_ids = [match.board_message_id]
                return
        message_id = await discord_api.send_embed(
            bot, match.channel_id, embed, view)
        await db.run_db(_store_board, match, message_id, needed)
        message.message_ids = [message_id]
        return
    if message.kind == outbox.MATCH_OVER:
        embed = await db.run_db(_recap_embed, match)
        message_id = await discord_api.send_embed(
            bot, match.channel_id, embed)
        message.message_ids = [message_id]
        return
    raise ValueError(f'Unknown outbox kind {message.kind!r}.')


async def run_once(bot: commands.Bot,
                   limit: int = outbox.OUTBOX_BATCH) -> int:
    """Deliver one batch of queued posts and return how many were handled."""
    messages = await db.run_db(outbox.claim_batch, limit=limit)
    for message in messages:
        try:
            await deliver(bot, message)
        except Exception as error:  # noqa: BLE001 - every failure is recorded
            logger.warning('Could not deliver outbox %s: %s', message.pk,
                           error)
            await db.run_db(outbox.mark_failed, message, str(error))
        else:
            await db.run_db(outbox.mark_sent, message, message.message_ids)
    return len(messages)


async def worker_loop(bot: commands.Bot) -> None:
    """Deliver the outbox while the bot stays connected."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await run_once(bot)
        except Exception:  # noqa: BLE001 - the loop must survive a bad tick
            logger.exception('The outbox worker failed')
        await asyncio.sleep(POLL_SECONDS)
