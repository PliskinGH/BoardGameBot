"""The Discord login the web display guards its pages with."""

import secrets
from typing import Any, cast

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect
from django.utils.functional import Promise
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import TemplateView

from . import discord_api, permissions
from .constants import OAUTH_STATE_BYTES
from .models import Player


def _safe_next(request: HttpRequest, url: str) -> bool:
    """Return True when a next URL stays on this site."""
    return url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()},
        require_https=request.is_secure())


class LoginView(TemplateView):
    """Offer the Discord login button."""

    template_name = 'core/login.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context['discord_enabled'] = discord_api.discord_oauth_configured()
        return context


class DiscordConnectView(View):
    """Send the visitor to Discord to authorize the application."""

    http_method_names = ['get', 'options']

    def get(self, request: HttpRequest, *args: Any,
            **kwargs: Any) -> HttpResponse:
        if not discord_api.discord_oauth_configured():
            raise Http404(discord_api.DISCORD_OAUTH_DISABLED)
        state = secrets.token_urlsafe(OAUTH_STATE_BYTES)
        request.session[discord_api.STATE_SESSION_KEY] = state
        wanted = request.GET.get('next', '')
        if wanted and _safe_next(request, wanted):
            request.session[discord_api.NEXT_SESSION_KEY] = wanted
        else:
            request.session.pop(discord_api.NEXT_SESSION_KEY, None)
        return HttpResponseRedirect(discord_api.authorize_url(request, state))


class DiscordCallbackView(View):
    """Finish the Discord flow: verify it, then log the player in."""

    http_method_names = ['get', 'options']

    def get(self, request: HttpRequest, *args: Any,
            **kwargs: Any) -> HttpResponse:
        if not discord_api.discord_oauth_configured():
            raise Http404(discord_api.DISCORD_OAUTH_DISABLED)
        state = request.session.pop(discord_api.STATE_SESSION_KEY, None)
        if request.GET.get('error'):
            return self._refuse(request, _('Discord login was cancelled.'))
        code = request.GET.get('code')
        if (not code or not state or not secrets.compare_digest(
                request.GET.get('state', ''), state)):
            return self._refuse(request, discord_api.DISCORD_OAUTH_ERROR)
        try:
            identity = discord_api.fetch_discord_identity(request, code)
        except (requests.RequestException, KeyError, ValueError):
            return self._refuse(request, discord_api.DISCORD_OAUTH_ERROR)
        player = Player.objects.from_discord(discord_api.account_of(identity))
        discord_api.store_identity(request.session, identity)
        permissions.seed_managers(
            player, permissions.access_from_session(request.session))
        login(request, player,
              backend='django.contrib.auth.backends.ModelBackend')
        return redirect(self._next_url(request))

    def _next_url(self, request: HttpRequest) -> str:
        """Return the page the login was asked for, or the default one."""
        wanted = request.session.pop(discord_api.NEXT_SESSION_KEY, '')
        if wanted and _safe_next(request, wanted):
            return str(wanted)
        return str(settings.LOGIN_REDIRECT_URL)

    def _refuse(self, request: HttpRequest,
                reason: str | Promise) -> HttpResponse:
        """Send the visitor back to the login page with a message."""
        # No str(): the proxy is translated when the message is rendered.
        messages.error(request, cast(str, reason))
        return redirect('core:login')
