"""Core page routes (Day 1 landing + Day 2 auth/dashboard/submissions)."""
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
    path('schedule-pickup/', views.schedule_pickup_placeholder, name='schedule-pickup'),
    path('find-bins/', views.find_bins_placeholder, name='find-bins'),
]
