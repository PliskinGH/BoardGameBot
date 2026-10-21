"""Tests for the bot's wiring, and the command without a token."""

import asyncio

from unittest import mock

import discord
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from discordbot import discord_api
from discordbot.bot import cog_extensions, create_bot
from discordbot.cogs.match import MatchCog
from tests.discordbot.fakes import FakeBot, FakeChannel
from tests.support import NoDiscordMixin


class BotTests(NoDiscordMixin, SimpleTestCase):
    def test_the_match_cog_is_discovered(self):
        self.assertIn('discordbot.cogs.match', cog_extensions())

    def test_only_the_guilds_intent_is_requested(self):
        bot = create_bot()

        self.assertTrue(bot.intents.guilds)
        self.assertFalse(bot.intents.members)
        self.assertFalse(bot.intents.message_content)

    def test_the_match_and_manager_groups_are_registered(self):
        bot = create_bot()

        async def load_and_inspect():
            await bot.add_cog(MatchCog(bot))
            groups = {command.name: command
                      for command in bot.tree.get_commands()}
            await bot.close()
            return groups

        groups = asyncio.run(load_and_inspect())

        self.assertEqual(set(groups), {'match', 'manager'})
        self.assertEqual(
            {command.name for command in groups['match'].commands},
            {'new', 'join', 'leave', 'start', 'act', 'undo', 'private',
             'hand', 'board', 'status', 'close', 'upgrade'})
        self.assertEqual(
            {command.name for command in groups['manager'].commands},
            {'add', 'remove'})

    def test_the_hook_loads_the_cog_and_starts_the_worker(self):
        bot = create_bot()
        bot.tree.sync = mock.AsyncMock(return_value=[])

        async def start_and_stop():
            with mock.patch('discordbot.bot.worker_loop',
                            new=mock.AsyncMock()):
                await bot.setup_hook()
            self.assertIn('MatchCog', bot.cogs)
            self.assertIsNotNone(bot.worker)
            await bot.close()

        asyncio.run(start_and_stop())

    @override_settings(DISCORD_TOKEN=None)
    def test_runbot_refuses_without_a_token(self):
        with self.assertRaises(CommandError):
            call_command('runbot')


class DiscordApiTests(NoDiscordMixin, SimpleTestCase):
    def test_a_send_returns_the_message_id(self):
        channel = FakeChannel(100)

        message_id = asyncio.run(discord_api.send_embed(
            FakeBot(channel), 100, discord.Embed(title='board')))

        self.assertEqual(message_id, 500)
        self.assertEqual(len(channel.messages), 1)

    def test_an_edit_reaches_the_message(self):
        channel = FakeChannel(100)
        bot = FakeBot(channel)
        asyncio.run(discord_api.send_embed(bot, 100,
                                           discord.Embed(title='board')))

        asyncio.run(discord_api.edit_embed(bot, 100, 500,
                                           discord.Embed(title='new')))

        self.assertEqual(channel.by_id[500].edits[0]['embed'].title, 'new')
