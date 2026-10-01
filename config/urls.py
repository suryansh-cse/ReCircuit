"""ReCircuit root URL configuration."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),          # landing page + pages
    path('api/', include('core.api_urls')),  # /api/dashboard/stats/ etc (Day 1)
]
