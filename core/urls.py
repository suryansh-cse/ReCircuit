"""Core page routes (Day 1 landing + Day 2 user side + Day 3 pickups/bins)."""
from django.urls import path

from . import views, views_collection, views_trace

urlpatterns = [
    path('', views.landing, name='landing'),
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('submit/', views.submit_ewaste, name='submit-ewaste'),
    path('my-ewaste/', views.my_ewaste, name='my-ewaste'),
    path('profile/', views.profile_view, name='profile'),
    # Day 3 pickup management
    path('pickup/request/', views.pickup_request_view, name='pickup-request'),
    path('pickup/my/', views.pickup_my, name='pickup-my'),
    path('pickup/<int:pk>/', views.pickup_detail, name='pickup-detail'),
    # Day 3 smart bins (public) — specific routes BEFORE <bin_id>
    path('bins/', views.bin_list, name='bin-list'),
    path('bins/map/', views_trace.bin_map, name='bin-map'),
    path('bins/<str:bin_id>/deposit/', views_trace.bin_deposit, name='bin-deposit'),
    path('bins/<str:bin_id>/', views.bin_detail, name='bin-detail'),
    # Day 5 alerts (public monitoring)
    path('alerts/', views.alert_list_view, name='alert-list'),
    # Day 6 collection operations (staff) + collector tasks
    path('operations/', views_collection.ops_dashboard, name='collections-ops'),
    path('operations/collectors/', views_collection.collectors_manage, name='collectors-manage'),
    path('operations/collectors/create/', views_collection.collectors_create, name='collectors-create'),
    path('operations/collectors/<int:pk>/toggle/', views_collection.collectors_toggle, name='collectors-toggle'),
    path('operations/pickup/<int:pickup_id>/ensure-task/', views_collection.task_ensure_pickup, name='pickup-ensure-task'),
    path('tasks/mine/', views_collection.my_tasks, name='my-tasks'),
    path('tasks/<int:pk>/', views_collection.task_detail, name='collection-task-detail'),
    path('tasks/<int:pk>/assign/', views_collection.task_assign, name='collection-task-assign'),
    path('tasks/<int:pk>/start/', views_collection.task_start, name='collection-task-start'),
    path('tasks/<int:pk>/complete/', views_collection.task_complete, name='collection-task-complete'),
    path('tasks/<int:pk>/cancel/', views_collection.task_cancel, name='collection-task-cancel'),
    # Day 7 recycling operations (staff)
    path('recycling/', views_trace.recycling_dashboard, name='recycling-dash'),
    path('recycling/submissions/<int:pk>/advance/', views_trace.submission_advance, name='submission-advance'),
    # Backward-compat redirects for Day 2 dashboard buttons
    path('schedule-pickup/', views.schedule_pickup_placeholder, name='schedule-pickup'),
    path('find-bins/', views.find_bins_placeholder, name='find-bins'),
]
