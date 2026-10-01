"""Core pages (Day 1: landing only; auth + dashboards come Day 2)."""
from django.shortcuts import render


def landing(request):
    """Public landing page — stats are loaded live via /api/dashboard/stats/."""
    return render(request, 'core/landing.html')
