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


def _bin_payload(smart_bin):
    """Manual serializer (Day 3) — explicit fields, no magic. POST lands Day 4."""
    return {
        'bin_id': smart_bin.bin_id,
        'name': smart_bin.name,
        'location': smart_bin.location,
        'city': smart_bin.city,
        'latitude': smart_bin.latitude,
        'longitude': smart_bin.longitude,
        'fill_level': smart_bin.fill_level,
        'fill_status': smart_bin.status,
        'weight': smart_bin.weight,
        'temperature': smart_bin.temperature,
        'is_online': smart_bin.is_online,
        'data_source': smart_bin.data_source,
        'last_seen': smart_bin.last_seen.isoformat() if smart_bin.last_seen else None,
    }


@api_view(['GET'])
def bin_list_api(request):
    """GET /api/bins/ — public JSON list of all smart bins."""
    bins = SmartBin.objects.all().order_by('bin_id')
    return Response([_bin_payload(b) for b in bins])


@api_view(['GET'])
def bin_detail_api(request, bin_id):
    """GET /api/bins/<bin_id>/ — public JSON for one bin, 404 if unknown."""
    from django.shortcuts import get_object_or_404
    smart_bin = get_object_or_404(SmartBin, bin_id=bin_id)
    return Response(_bin_payload(smart_bin))
