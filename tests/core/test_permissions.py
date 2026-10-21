"""Tests for the guild-scoped manager permission."""

from types import SimpleNamespace

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from guardian.models import UserObjectPermission

from core import discord_api, permissions
from core.models import Guild, Player
from tests.factories import make_guild, make_player


def grants(player, guild):
    """Return how many object permissions the player holds on the guild."""
    return UserObjectPermission.objects.filter(
        user=player,
        content_type=ContentType.objects.get_for_model(guild),
        object_pk=str(guild.pk)).count()


class AnonymousUserTests(TestCase):
    def test_guardian_creates_no_anonymous_player(self):
        self.assertFalse(Player.objects.filter(username='AnonymousUser')
                         .exists())


class AccessTests(TestCase):
    def test_a_session_access_flags_managed_guilds(self):
        access = permissions.access_from_session({
            discord_api.GUILDS_SESSION_KEY: [
                {'id': 7, 'name': 'Seven',
                 'permissions': discord_api.MANAGE_GUILD},
                {'id': 8, 'name': 'Eight', 'permissions': 0},
            ],
        })

        self.assertEqual(access, [permissions.GuildAccess(7, True),
                                  permissions.GuildAccess(8, False)])

    def test_a_member_access_flags_its_guild(self):
        self.assertEqual(
            permissions.access_from_member(7,
                                           SimpleNamespace(manage_guild=True)),
            [permissions.GuildAccess(7, True)])
        self.assertEqual(
            permissions.access_from_member(7, None),
            [permissions.GuildAccess(7, False)])


class SeedTests(TestCase):
    def setUp(self):
        self.guild = make_guild(discord_id=7)
        self.player = make_player('manager')

    def test_a_managed_guild_grants_the_permission(self):
        granted = permissions.seed_managers(
            self.player,
            [permissions.GuildAccess(self.guild.discord_id, True)])

        self.assertEqual(granted, 1)
        self.assertTrue(permissions.is_guild_manager(self.guild, self.player))

    def test_an_unmanaged_guild_grants_nothing(self):
        granted = permissions.seed_managers(
            self.player,
            [permissions.GuildAccess(self.guild.discord_id, False)])

        self.assertEqual(granted, 0)
        self.assertFalse(permissions.is_guild_manager(self.guild, self.player))

    def test_an_unknown_guild_is_ignored(self):
        granted = permissions.seed_managers(
            self.player,
            [permissions.GuildAccess(self.guild.discord_id + 1, True)])

        self.assertEqual(granted, 0)
        self.assertEqual(grants(self.player, self.guild), 0)

    def test_seeding_twice_is_idempotent(self):
        access = [permissions.GuildAccess(self.guild.discord_id, True)]

        permissions.seed_managers(self.player, access)
        permissions.seed_managers(self.player, access)

        self.assertEqual(grants(self.player, self.guild), 1)

    def test_the_permission_is_scoped_to_its_guild(self):
        other = make_guild(discord_id=8)
        permissions.grant_manager(self.guild, self.player)

        self.assertTrue(permissions.is_guild_manager(self.guild, self.player))
        self.assertFalse(permissions.is_guild_manager(other, self.player))

    def test_a_superuser_manages_every_guild(self):
        self.player.is_superuser = True
        self.player.save(update_fields=['is_superuser'])

        self.assertTrue(permissions.is_guild_manager(self.guild, self.player))

    def test_an_inactive_player_is_not_a_manager(self):
        permissions.grant_manager(self.guild, self.player)
        self.player.is_active = False
        self.player.save(update_fields=['is_active'])

        self.assertFalse(permissions.is_guild_manager(self.guild, self.player))

    def test_managed_guilds_lists_the_granted_servers(self):
        permissions.grant_manager(self.guild, self.player)
        make_guild(discord_id=8)

        self.assertEqual(list(permissions.managed_guilds(self.player)),
                         [self.guild])

    def test_a_superuser_manages_every_guild(self):
        make_guild(discord_id=8)
        self.player.is_superuser = True
        self.player.save(update_fields=['is_superuser'])

        self.assertEqual(set(permissions.managed_guilds(self.player)),
                         set(Guild.objects.all()))

    def test_an_inactive_player_manages_no_guild(self):
        permissions.grant_manager(self.guild, self.player)
        self.player.is_active = False
        self.player.save(update_fields=['is_active'])

        self.assertFalse(permissions.managed_guilds(self.player).exists())

    def test_revoking_reports_whether_a_grant_existed(self):
        permissions.grant_manager(self.guild, self.player)

        self.assertTrue(permissions.revoke_manager(self.guild, self.player))
        self.assertFalse(permissions.revoke_manager(self.guild, self.player))
        self.assertFalse(permissions.is_guild_manager(self.guild, self.player))
