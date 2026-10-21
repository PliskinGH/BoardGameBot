"""The read-only web display of matches."""

from typing import Any

from django.contrib.auth.mixins import AccessMixin, LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseBase
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView

from core import discord_api, permissions
from core.models import Guild
from games.models import Match, MatchStatus
from games.services.matches import match_title

from . import queries
from .constants import RECENT_MATCHES_LIMIT


@method_decorator(never_cache, name='dispatch')
class IndexView(LoginRequiredMixin, TemplateView):
    """List the matches the logged in player holds a seat in."""

    template_name = 'board/index.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context.update(self._guilds())
        player = queries.current_player(self.request)
        if player is None:
            context['matches'] = []
            return context
        rows = (Match.objects.filter(seats__player=player)
                .select_related('guild').distinct()[:RECENT_MATCHES_LIMIT])
        context['matches'] = [
            {'match': match, 'game_name': queries.game_name(match),
             'match_title': match_title(match, queries.game_name(match))}
            for match in rows]
        return context

    def _guilds(self) -> dict[str, Any]:
        """Return the servers the player manages, with their invite links."""
        guilds = discord_api.session_guilds(self.request.session)
        session_rows = {int(guild['id']): guild for guild in guilds
                        if discord_api.manages_guild(guild)}
        player = queries.current_player(self.request)
        granted = ({guild.discord_id: guild
                    for guild in permissions.managed_guilds(player)}
                   if player is not None else {})
        known = ({guild.discord_id: guild
                  for guild in Guild.objects.filter(
                      discord_id__in=session_rows.keys())}
                 if session_rows else {})
        rows: list[dict[str, Any]] = []
        for guild_id in set(session_rows) | set(granted):
            entry = session_rows.get(guild_id)
            guild = granted.get(guild_id) or known.get(guild_id)
            name = (str(entry.get('name') or guild_id) if entry is not None
                    else guild.name if guild is not None else str(guild_id))
            rows.append({'discord_id': guild_id, 'name': name,
                         'added': guild is not None,
                         'invite_url': discord_api.invite_url(guild_id)})
        rows.sort(key=lambda row: row['name'].casefold())
        return {'managed_guilds': rows, 'session_has_guilds': bool(guilds)}


@method_decorator(never_cache, name='dispatch')
class MatchView(AccessMixin, TemplateView):
    """Show a match, publicly when its server allows it."""

    template_name = 'board/match.html'
    match: Match

    def dispatch(self, request: HttpRequest, *args: Any,
                 **kwargs: Any) -> HttpResponseBase:
        """Let a visitor in only when the server has made it public."""
        self.match = queries.match_for_display(
            int(kwargs['discord_guild_id']), int(kwargs['pk']))
        if (not request.user.is_authenticated
                and not self.match.guild.public_display):
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        match = self.match
        state_url = reverse('board:match_state',
                            args=[match.guild.discord_id, match.pk])
        context.update(queries.state_context(
            match, queries.current_player(self.request), state_url))
        context['public_view'] = not self.request.user.is_authenticated
        return context


@method_decorator(never_cache, name='dispatch')
class MatchStateView(TemplateView):
    """Render the match state, or answer 204 when the viewer is up to date."""

    template_name = 'board/_state.html'
    match: Match

    def dispatch(self, request: HttpRequest, *args: Any,
                 **kwargs: Any) -> HttpResponseBase:
        """Refuse a poll the match page would send to login."""
        self.match = queries.match_for_display(
            int(kwargs['discord_guild_id']), int(kwargs['pk']))
        if (not request.user.is_authenticated
                and not self.match.guild.public_display):
            return HttpResponse(status=403)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, *args: Any,
            **kwargs: Any) -> HttpResponse:
        match = self.match
        since = self._since(request)
        if match.status != MatchStatus.SETUP and since == match.version:
            response = HttpResponse(status=204)
            response['X-Match-Version'] = str(match.version)
            return response
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        match = self.match
        state_url = reverse('board:match_state',
                            args=[match.guild.discord_id, match.pk])
        context.update(queries.state_context(
            match, queries.current_player(self.request), state_url))
        return context

    @staticmethod
    def _since(request: HttpRequest) -> int | None:
        """Return the version the viewer last saw, or None when unknown."""
        raw = request.GET.get('since')
        try:
            return int(raw) if raw is not None else None
        except ValueError:
            return None