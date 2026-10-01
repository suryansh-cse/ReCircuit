"""API routes (Day 1 stats + Day 3 bin GET + Day 4 telemetry POST)."""
from django.urls import path

from . import api_views

urlpatterns = [
    path('dashboard/stats/', api_views.dashboard_stats, name='api-dashboard-stats'),
    path('bins/', api_views.bin_list_api, name='api-bin-list'),
    path('bins/<str:bin_id>/', api_views.bin_detail_api, name='api-bin-detail'),
    path('telemetry/', api_views.telemetry_ingest, name='api-telemetry'),
    path('telemetry/simulate/', api_views.telemetry_simulate, name='api-telemetry-simulate'),
]
