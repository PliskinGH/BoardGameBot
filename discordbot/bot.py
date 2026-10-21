"""The Discord client, started by the ``runbot`` management command."""

import asyncio
import logging
from importlib import import_module
from pathlib import Path

import discord
from django.conf import settings
from discord.ext import commands

from .outbox_worker import worker_loop
from .views import (MatchActionButton, MatchActButton, MatchCloseButton,
                    MatchFormButton, MatchHandButton, MatchJoinButton,
                    MatchLeaveButton, MatchParamSelect, MatchPrivateButton,
                    MatchStartButton, MatchUndoButton)

logger = logging.getLogger(__name__)

COGS_PACKAGE = 'discordbot.cogs'


def cog_extensions() -> list[str]:
    """Return the import path of every module in ``discordbot/cogs``."""
    module_file = import_module(COGS_PACKAGE).__file__
    if module_file is None:
        return []
    directory = Path(module_file).parent
    return [f'{COGS_PACKAGE}.{path.stem}'
            for path in sorted(directory.glob('*.py'))
            if not path.stem.startswith('_')]


class BoardGameBot(commands.Bot):
    """Discord client wired to the Django project's settings and database."""

    def __init__(self) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(command_prefix=commands.when_mentioned,
                         intents=intents)
        self.worker: asyncio.Task[None] | None = None

    async def setup_hook(self) -> None:
        """Load the cogs, revive the controls, and start the outbox worker."""
        for extension in cog_extensions():
            await self.load_extension(extension)
        self.add_dynamic_items(MatchActButton, MatchHandButton,
                               MatchPrivateButton, MatchJoinButton,
                               MatchLeaveButton, MatchStartButton,
                               MatchCloseButton, MatchUndoButton,
                               MatchActionButton, MatchParamSelect,
                               MatchFormButton)
        await self.sync_commands()
        self.worker = asyncio.create_task(worker_loop(self), name='outbox')

    async def close(self) -> None:
        """Stop the worker before the gateway closes."""
        if self.worker is not None:
            self.worker.cancel()
            self.worker = None
        await super().close()

    async def sync_commands(self) -> None:
        """Publish the slash commands, to the test guilds first when set."""
        if not settings.TEST_GUILD_IDS:
            try:
                synced = await self.tree.sync()
            except discord.HTTPException as error:
                logger.warning('Could not sync commands globally: %s', error)
            else:
                logger.info('Synced %s slash commands globally', len(synced))
            return
        for guild_id in settings.TEST_GUILD_IDS:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            try:
                synced = await self.tree.sync(guild=guild)
            except discord.HTTPException as error:
                logger.warning('Could not sync commands to guild %s: %s',
                               guild_id, error)
            else:
                logger.info('Synced %s slash commands to guild %s',
                            len(synced), guild_id)

    async def on_ready(self) -> None:
        logger.info('Logged in as %s (ID: %s)', self.user,
                    getattr(self.user, 'id', None))


def create_bot() -> BoardGameBot:
    """Return a bot instance, ready to be started with a token."""
    return BoardGameBot()
