"""URL configuration for the board game bot."""

from django.contrib import admin
from django.urls import include, path

from . import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('', include('board.urls')),
    path('healthz', views.healthz, name='healthz'),
]
