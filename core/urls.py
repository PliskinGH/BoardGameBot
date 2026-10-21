"""URLs of the Discord login."""

from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = 'core'

urlpatterns = [
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('discord/connect/', views.DiscordConnectView.as_view(),
         name='discord_connect'),
    path('discord/callback/', views.DiscordCallbackView.as_view(),
         name='discord_callback'),
]
