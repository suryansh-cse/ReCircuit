"""Day-1 public API: live stats for the landing page.

All numbers come from the database — nothing is hardcoded.
Empty DB → zeros (correct empty state, not fake data).
"""
from django.contrib.auth import get_user_model
from django.db.models import Sum
from rest_framework.decorators import api_view
from rest_framework.response import Response

from bins.models import SmartBin
from waste.models import Collection, EwasteSubmission, PickupRequest

User = get_user_model()


@api_view(['GET'])
def dashboard_stats(request):
    total_users = User.objects.count()
    total_bins = SmartBin.objects.count()
    online_bins = SmartBin.objects.filter(is_online=True).count()
    offline_bins = total_bins - online_bins

    submitted_weight = (
        EwasteSubmission.objects.aggregate(total=Sum('estimated_weight'))['total'] or 0.0
    )
    collected_weight = (
        Collection.objects.aggregate(total=Sum('collected_weight'))['total'] or 0.0
    )
    # Total e-waste tracked = user estimates + actually collected tonnage
    total_ewaste_kg = round(submitted_weight + collected_weight, 2)

    pending_pickups = PickupRequest.objects.filter(status='pending').count()
    total_pickups = PickupRequest.objects.count()
    full_bins = SmartBin.objects.filter(fill_level__gte=80.0).count()

    return Response({
        'total_users': total_users,
        'total_bins': total_bins,
        'online_bins': online_bins,
        'offline_bins': offline_bins,
        'full_bins': full_bins,
        'total_ewaste_kg': total_ewaste_kg,
        'pending_pickups': pending_pickups,
        'total_pickups': total_pickups,
    })
