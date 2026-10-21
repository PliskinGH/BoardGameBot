"""Answer an interaction, ephemerally, before or after a defer."""

from typing import Any

import discord


async def reply(interaction: discord.Interaction, *,
                content: str | None = None,
                embed: discord.Embed | None = None,
                view: discord.ui.View | discord.ui.LayoutView
                | None = None) -> None:
    """Send an ephemeral message, whichever half of the interaction is free."""
    payload: dict[str, Any] = {'ephemeral': True}
    if content is not None:
        payload['content'] = content
    if embed is not None:
        payload['embed'] = embed
    if view is not None:
        payload['view'] = view
    if interaction.response.is_done():
        await interaction.followup.send(**payload)
    else:
        await interaction.response.send_message(**payload)
