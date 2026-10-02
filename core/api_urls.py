"""API routes (stats + bins + Day 4 telemetry + Day 5 alerts/history + Day 6 tasks)."""
from django.urls import path

from . import api_views

urlpatterns = [
    path('dashboard/stats/', api_views.dashboard_stats, name='api-dashboard-stats'),
    path('bins/', api_views.bin_list_api, name='api-bin-list'),
    path('bins/<str:bin_id>/', api_views.bin_detail_api, name='api-bin-detail'),
    path('bins/<str:bin_id>/history/', api_views.bin_history_api, name='api-bin-history'),
    path('telemetry/', api_views.telemetry_ingest, name='api-telemetry'),
    path('telemetry/simulate/', api_views.telemetry_simulate, name='api-telemetry-simulate'),
    path('alerts/', api_views.alert_list_api, name='api-alert-list'),
    path('alerts/<int:pk>/', api_views.alert_detail_api, name='api-alert-detail'),
    path('alerts/<int:pk>/resolve/', api_views.alert_resolve_api, name='api-alert-resolve'),
    # Day 6 collection operations
    path('collection-tasks/', api_views.task_list_api, name='api-task-list'),
    path('collection-tasks/<int:pk>/', api_views.task_detail_api, name='api-task-detail'),
    path('collection-tasks/<int:pk>/assign/', api_views.task_assign_api, name='api-task-assign'),
    path('collection-tasks/<int:pk>/start/', api_views.task_start_api, name='api-task-start'),
    path('collection-tasks/<int:pk>/complete/', api_views.task_complete_api, name='api-task-complete'),
    path('collection-tasks/<int:pk>/cancel/', api_views.task_cancel_api, name='api-task-cancel'),
]
