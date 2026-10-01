"""Core page routes (Day 1 landing + Day 2 user side + Day 3 pickups/bins)."""
from django.urls import path

from . import views

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
    # Day 3 smart bins (public)
    path('bins/', views.bin_list, name='bin-list'),
    path('bins/<str:bin_id>/', views.bin_detail, name='bin-detail'),
    # Day 5 alerts (public monitoring)
    path('alerts/', views.alert_list_view, name='alert-list'),
    # Backward-compat redirects for Day 2 dashboard buttons
    path('schedule-pickup/', views.schedule_pickup_placeholder, name='schedule-pickup'),
    path('find-bins/', views.find_bins_placeholder, name='find-bins'),
]
