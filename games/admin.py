"""Admin views of matches, their logs and their outbox."""

from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from .models import Action, Match, OutboxMessage, Seat


class SeatInline(admin.TabularInline):  # type: ignore[type-arg]
    """The seats of a match, read only."""

    model = Seat
    extra = 0
    fields = ('position', 'player', 'display_name', 'role', 'eliminated')
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request: HttpRequest,
                           obj: Any = None) -> bool:
        return False


class ActionInline(admin.TabularInline):  # type: ignore[type-arg]
    """The action log of a match, read only."""

    model = Action
    extra = 0
    fields = ('seq', 'type', 'actor', 'random', 'revealed', 'created_at')
    readonly_fields = fields
    can_delete = False
    ordering = ('-seq',)

    def has_add_permission(self, request: HttpRequest,
                           obj: Any = None) -> bool:
        return False


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Matches, their host and their log; new ones come from the service."""

    list_display = ('id', 'name', 'slug', 'guild', 'host', 'status',
                    'version', 'position', 'rules_version', 'created_at')
    list_filter = ('status', 'slug')
    search_fields = ('name', 'host__username', 'host__discord_name',
                     'guild__name')
    readonly_fields = ('state', 'hidden_state', 'last_needed_seats',
                       'version', 'position', 'created_at', 'finished_at')
    inlines = (SeatInline, ActionInline)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False


@admin.register(Action)
class ActionAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """The append-only action log."""

    list_display = ('id', 'match', 'seq', 'type', 'actor', 'created_at')
    list_filter = ('type', 'random', 'revealed')
    search_fields = ('match__slug', 'actor__username', 'actor__discord_name')
    readonly_fields = ('match', 'seq', 'actor', 'type', 'payload', 'result',
                       'random', 'revealed', 'created_at')

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest,
                              obj: Any = None) -> bool:
        return False


@admin.register(OutboxMessage)
class OutboxMessageAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Queued Discord posts, for diagnosing a stuck worker."""

    list_display = ('id', 'match', 'kind', 'status', 'attempts',
                    'next_attempt_at', 'sent_at')
    list_filter = ('status', 'kind')
    search_fields = ('match__slug',)
    readonly_fields = ('match', 'kind', 'payload', 'status', 'attempts',
                       'claimed_at', 'sent_at', 'message_ids', 'error',
                       'next_attempt_at')

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest,
                              obj: Any = None) -> bool:
        return False
