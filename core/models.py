"""The identity and tenancy models every other app builds on."""

from dataclasses import dataclass
from typing import ClassVar

from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

from .constants import DISCORD_NAME_MAX_LENGTH, GUILD_NAME_MAX_LENGTH


@dataclass(frozen=True)
class DiscordAccount:
    """A Discord account as the OAuth flow reports it."""

    id: int
    name: str


class PlayerManager(UserManager['Player']):
    """Creates players from Discord accounts, which is how they are met."""

    def from_discord(self, account: DiscordAccount) -> 'Player':
        """Return the player linked to ``account``, keeping its names current."""
        name = account.name or None
        if name:
            self._release_stale(name, account.id)
        player, created = self.get_or_create(
            discord_user_id=account.id,
            defaults={
                'username': self._username_for(name, account.id),
                'discord_name': name,
            },
        )
        if created:
            player.set_unusable_password()
            player.save(update_fields=['password'])
            return player
        if name is None or player.discord_name == name:
            return player
        update_fields = ['discord_name']
        discord_owned = (player.username == player.discord_name
                         or player.username
                         == f'discord_{player.discord_user_id}')
        if (discord_owned
                and not self.filter(username=name)
                             .exclude(pk=player.pk).exists()):
            player.username = name
            update_fields.append('username')
        player.discord_name = name
        player.save(update_fields=update_fields)
        return player

    def _release_stale(self, name: str, discord_user_id: int) -> None:
        """Free ``name`` from every row but the claimant's, as Discord did."""
        for stale in (self.filter(discord_name=name)
                          .exclude(discord_user_id=discord_user_id)):
            update_fields = ['discord_name']
            if stale.discord_user_id and stale.username == stale.discord_name:
                stale.username = f'discord_{stale.discord_user_id}'
                update_fields.append('username')
            stale.discord_name = None
            stale.save(update_fields=update_fields)

    def _username_for(self, name: str | None, discord_user_id: int) -> str:
        """Discord name at first meeting, or the id format when it is taken."""
        if name and not self.filter(username=name).exists():
            return name
        return f'discord_{discord_user_id}'


class Player(AbstractUser):
    """A player, identified by their Discord account."""

    objects: ClassVar[PlayerManager] = PlayerManager()

    first_name = None  # type: ignore[assignment]
    last_name = None  # type: ignore[assignment]

    email = models.EmailField(_('email address'), unique=True,  # type: ignore[assignment]
                              blank=True, null=True, default=None)
    discord_user_id = models.BigIntegerField(_('Discord user ID'), unique=True,
                                             blank=True, null=True, default=None)
    discord_name = models.CharField(_('Discord username'),
                                    max_length=DISCORD_NAME_MAX_LENGTH,
                                    unique=True, blank=True, null=True,
                                    default=None)

    class Meta:
        verbose_name = _('player')
        verbose_name_plural = _('players')

    @property
    def display_name(self) -> str:
        """Return how the player is shown, Discord name preferred."""
        return self.discord_name or self.username

    def __str__(self) -> str:
        return self.display_name


class Guild(models.Model):
    """A Discord server the bot plays in."""

    discord_id = models.BigIntegerField(_('Discord server ID'), unique=True)
    name = models.CharField(_('name'), max_length=GUILD_NAME_MAX_LENGTH)
    default_channel_id = models.BigIntegerField(
        _('default channel ID'), blank=True, null=True, default=None)
    default_ping_role_id = models.BigIntegerField(
        _('default ping role ID'), blank=True, null=True, default=None)
    public_display = models.BooleanField(
        _('public display'), default=False,
        help_text=_('Serve this server’s matches to visitors who are not '
                    'logged in.'))
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    class Meta:
        verbose_name = _('guild')
        verbose_name_plural = _('guilds')
        ordering = ('name',)
        permissions = [('manage_matches',
                        _('Can manage matches of this server'))]

    def __str__(self) -> str:
        return self.name

