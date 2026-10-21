"""The admin surfaces for players, servers and server managers."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _
from guardian.admin import GuardedModelAdmin

from .models import Guild, Player


@admin.register(Player)
class PlayerAdmin(UserAdmin):  # type: ignore[type-arg]
    """Players, their Discord identity and their global rights."""

    list_display = ('username', 'discord_name', 'is_staff', 'is_active')
    list_filter = ('is_active', 'is_staff', 'is_superuser')
    search_fields = ('username', 'discord_name', 'discord_user_id', 'email')
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        (_('Personal info'), {'fields': ('email', 'discord_user_id',
                                         'discord_name')}),
        (_('Permissions'), {'fields': ('is_active', 'is_staff', 'is_superuser',
                                       'groups', 'user_permissions')}),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {'classes': ('wide',),
                'fields': ('username', 'email', 'discord_user_id',
                           'discord_name', 'usable_password',
                           'password1', 'password2')}),
    )


@admin.register(Guild)
class GuildAdmin(GuardedModelAdmin):
    """Servers, their public display and their object permissions."""

    list_display = ('name', 'discord_id', 'public_display',
                    'default_channel_id', 'default_ping_role_id', 'created_at')
    list_filter = ('public_display',)
    search_fields = ('name', 'discord_id')
    readonly_fields = ('created_at',)
