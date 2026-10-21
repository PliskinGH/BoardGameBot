"""Discord OAuth2, and the identity reads the web login needs beside it."""

import logging
from typing import Any
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib.sessions.backends.base import SessionBase
from django.http import HttpRequest
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from .constants import HTTP_TIMEOUT_SECONDS
from .models import DiscordAccount

logger = logging.getLogger(__name__)

DISCORD_AUTHORIZE_URL = 'https://discord.com/oauth2/authorize'
DISCORD_API_BASE_URL = 'https://discord.com/api/v10'

# Session keys of the login flow.
STATE_SESSION_KEY = 'discord_oauth_state'
NEXT_SESSION_KEY = 'discord_oauth_next'
USER_SESSION_KEY = 'discord_user'
GUILDS_SESSION_KEY = 'discord_guilds'

# Scopes asked for, and the Manage Server bit Discord reports per guild.
DISCORD_OAUTH_SCOPES = 'identify guilds'
MANAGE_GUILD = 0x20

# Permissions the bot needs: see the channel, post the board (an embed), read
# its own message back to edit it, and answer in threads.
VIEW_CHANNELS = 1 << 10
SEND_MESSAGES = 1 << 11
EMBED_LINKS = 1 << 14
READ_MESSAGE_HISTORY = 1 << 16
SEND_MESSAGES_IN_THREADS = 1 << 38
BOT_PERMISSIONS = (VIEW_CHANNELS | SEND_MESSAGES | EMBED_LINKS
                   | READ_MESSAGE_HISTORY | SEND_MESSAGES_IN_THREADS)
BOT_SCOPES = 'bot applications.commands'

DISCORD_OAUTH_DISABLED = _('Discord login is not configured.')
DISCORD_OAUTH_ERROR = _('Discord login failed. Please try again.')


def discord_oauth_configured() -> bool:
    """Return True when the Discord application credentials are set."""
    return bool(settings.DISCORD_CLIENT_ID and settings.DISCORD_CLIENT_SECRET)


def discord_redirect_uri(request: HttpRequest) -> str:
    """Return the callback URI sent to Discord."""
    return settings.DISCORD_REDIRECT_URI or request.build_absolute_uri(
        reverse('core:discord_callback'))


def invite_url(discord_guild_id: int) -> str:
    """Return the page adding the bot to one server, or empty unconfigured."""
    if not settings.DISCORD_CLIENT_ID:
        return ''
    params = urlencode({
        'client_id': settings.DISCORD_CLIENT_ID,
        'scope': BOT_SCOPES,
        'permissions': BOT_PERMISSIONS,
        'guild_id': discord_guild_id,
        'disable_guild_select': 'true',
    })
    return f'{DISCORD_AUTHORIZE_URL}?{params}'


def manages_guild(guild: dict[str, Any]) -> bool:
    """Return True when the session says the player may manage a guild."""
    return bool(int(guild.get('permissions') or 0) & MANAGE_GUILD)


def authorize_url(request: HttpRequest, state: str) -> str:
    """Return the Discord page the visitor authorizes the application on."""
    params = urlencode({
        'client_id': settings.DISCORD_CLIENT_ID or '',
        'redirect_uri': discord_redirect_uri(request),
        'response_type': 'code',
        'scope': DISCORD_OAUTH_SCOPES,
        'state': state,
    })
    return f'{DISCORD_AUTHORIZE_URL}?{params}'


def fetch_discord_identity(request: HttpRequest, code: str) -> dict[str, Any]:
    """Exchange a code for the account it belongs to and the guilds it is in.

    Raises requests.RequestException, KeyError or ValueError on failure.
    """
    token = requests.post(
        f'{DISCORD_API_BASE_URL}/oauth2/token',
        data={
            'client_id': settings.DISCORD_CLIENT_ID,
            'client_secret': settings.DISCORD_CLIENT_SECRET,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': discord_redirect_uri(request),
        },
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    token.raise_for_status()
    headers = {'Authorization': f'Bearer {token.json()["access_token"]}'}
    account = requests.get(f'{DISCORD_API_BASE_URL}/users/@me',
                           headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
    account.raise_for_status()
    guilds = requests.get(f'{DISCORD_API_BASE_URL}/users/@me/guilds',
                          headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
    guilds.raise_for_status()
    return {'account': account.json(), 'guilds': guilds.json()}


def account_of(identity: dict[str, Any]) -> DiscordAccount:
    """Return the Discord account the fetched identity describes."""
    account = identity['account']
    return DiscordAccount(id=int(account['id']),
                          name=account.get('username', ''))


def store_identity(session: SessionBase, identity: dict[str, Any]) -> None:
    """Keep the logged in account and its guilds, with their permissions."""
    account = identity['account']
    session[USER_SESSION_KEY] = {'id': int(account['id']),
                                 'username': account.get('username', '')}
    session[GUILDS_SESSION_KEY] = [
        {'id': int(guild['id']),
         'name': guild.get('name') or str(guild['id']),
         'permissions': int(guild.get('permissions') or 0)}
        for guild in identity['guilds']]


def session_guilds(session: SessionBase) -> list[dict[str, Any]]:
    """Return the guilds the logged in account belongs to."""
    guilds: list[dict[str, Any]] = session.get(GUILDS_SESSION_KEY, [])
    return guilds
