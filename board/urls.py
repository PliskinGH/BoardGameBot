"""URLs of the web display."""

from django.urls import path

from . import views

app_name = 'board'

urlpatterns = [
    path('', views.IndexView.as_view(), name='index'),
    path('g/<int:discord_guild_id>/matches/<int:pk>/',
         views.MatchView.as_view(), name='match'),
    path('g/<int:discord_guild_id>/matches/<int:pk>/state/',
         views.MatchStateView.as_view(), name='match_state'),
]
