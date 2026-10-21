"""The only place the bot talks to Discord's REST API."""

from typing import Any, cast

import discord
from discord.ext import commands


async def send_embed(bot: commands.Bot, channel_id: int,
                     embed: discord.Embed,
                     view: discord.ui.View | None = None,
                     content: str | None = None) -> int:
    """Post an embed in a channel and return the message id."""
    channel = await _channel(bot, channel_id)
    payload: dict[str, Any] = {'embed': embed}
    if view is not None:
        payload['view'] = view
    if content:
        payload['content'] = content
    message = await channel.send(**payload)
    return message.id


async def edit_embed(bot: commands.Bot, channel_id: int, message_id: int,
                     embed: discord.Embed,
                     view: discord.ui.View | None = None) -> None:
    """Edit a message the bot posted."""
    channel = await _channel(bot, channel_id)
    message = await channel.fetch_message(message_id)
    payload: dict[str, Any] = {'embed': embed}
    if view is not None:
        payload['view'] = view
    await message.edit(**payload)


async def delete_message(bot: commands.Bot, channel_id: int,
                         message_id: int) -> None:
    """Delete a message the bot posted."""
    channel = await _channel(bot, channel_id)
    message = await channel.fetch_message(message_id)
    await message.delete()


async def _channel(bot: commands.Bot,
                   channel_id: int) -> discord.abc.Messageable:
    """Return the channel to post in, cached or fetched."""
    channel = bot.get_channel(channel_id)
    if channel is None:
        channel = await bot.fetch_channel(channel_id)
    return cast(discord.abc.Messageable, channel)
