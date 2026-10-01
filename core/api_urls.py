"""API routes (Day 1: stats only; bins/telemetry/pickups land Day 3-4)."""
from django.urls import path

from . import api_views

urlpatterns = [
    path('dashboard/stats/', api_views.dashboard_stats, name='api-dashboard-stats'),
]
