"""Day-1 public API + Day 3 bin GET + Day 4 telemetry ingest.

All numbers come from the database — nothing is hardcoded.
Empty DB → zeros (correct empty state, not fake data).

Day 4 contract (matches the ESP32 firmware in firmware/):
    POST /api/telemetry/          REAL hardware readings (ESP32 only)
    POST /api/telemetry/simulate/ SIMULATED demo readings (no hardware needed)
The two paths can never mix: ingest always stores REAL, simulate always SIMULATED.
"""
import random

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from bins.models import DataSource, SmartBin, Telemetry, refresh_online_flags
from waste.models import Collection, EwasteSubmission, PickupRequest

User = get_user_model()


@api_view(['GET'])
def dashboard_stats(request):
    refresh_online_flags()
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
    refresh_online_flags()
    bins = SmartBin.objects.all().order_by('bin_id')
    return Response([_bin_payload(b) for b in bins])


@api_view(['GET'])
def bin_detail_api(request, bin_id):
    """GET /api/bins/<bin_id>/ — public JSON for one bin, 404 if unknown."""
    refresh_online_flags()
    smart_bin = get_object_or_404(SmartBin, bin_id=bin_id)
    return Response(_bin_payload(smart_bin))


def _validate_telemetry_payload(data):
    """Validate ESP32 payload. Returns (errors dict, cleaned values)."""
    errors = {}

    device_id = data.get('device_id')
    if not device_id or not str(device_id).strip():
        errors['device_id'] = 'device_id is required (e.g. ECO-BIN-001).'
    device_id = str(device_id).strip() if device_id else ''

    def _number(name, *, minimum, maximum, required=True):
        value = data.get(name)
        if value is None or value == '':
            if required:
                errors[name] = f'{name} is required.'
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            errors[name] = f'{name} must be a number.'
            return None
        if not (minimum <= number <= maximum):
            errors[name] = f'{name} must be between {minimum} and {maximum}.'
            return None
        return number

    fill = _number('fill_level', minimum=0, maximum=100)
    weight = _number('weight', minimum=0, maximum=5000)
    temperature = _number('temperature', minimum=-20, maximum=100, required=False)

    cleaned = {'device_id': device_id, 'fill_level': fill,
               'weight': weight, 'temperature': temperature}
    return errors, cleaned


@api_view(['POST'])
def telemetry_ingest(request):
    """POST /api/telemetry/ — REAL ESP32 hardware readings.

    Expected JSON: {"device_id": "ECO-BIN-001", "fill_level": 82,
                    "weight": 18.4, "temperature": 29.5}
    Steps: validate → identify device → store telemetry → update bin → timestamp.
    Unknown device_id → 404 (register the bin in /admin/ first — never auto-create).
    Open auth: ESP32 cannot do session login (lock down with tokens in production).
    """
    if not isinstance(request.data, dict):
        return Response({'error': 'Send a JSON object.'},
                        status=status.HTTP_400_BAD_REQUEST)
    errors, cleaned = _validate_telemetry_payload(request.data)
    if errors:
        return Response({'errors': errors}, status=status.HTTP_400_BAD_REQUEST)

    try:
        smart_bin = SmartBin.objects.get(bin_id=cleaned['device_id'])
    except SmartBin.DoesNotExist:
        return Response(
            {'error': f"Unknown device '{cleaned['device_id']}'. Register it in /admin/ first."},
            status=status.HTTP_404_NOT_FOUND,
        )

    reading = Telemetry.objects.create(
        smart_bin=smart_bin,
        fill_level=cleaned['fill_level'],
        weight=cleaned['weight'],
        temperature=cleaned['temperature'],
        data_source=DataSource.REAL,
    )
    smart_bin.mark_seen(
        fill=cleaned['fill_level'],
        weight=cleaned['weight'],
        temperature=cleaned['temperature'],
        data_source=DataSource.REAL,
    )
    refresh_online_flags()
    payload = _bin_payload(smart_bin)
    payload['reading_id'] = reading.pk
    return Response(payload, status=status.HTTP_201_CREATED)


@api_view(['POST'])
def telemetry_simulate(request):
    """POST /api/telemetry/simulate/ — SIMULATED demo readings (no hardware).

    Body {"device_id": "ECO-BIN-001"} simulates one bin; empty body simulates all.
    Values random-walk from current state (never presented as hardware data:
    rows and bins stay labelled SIMULATED unless a real device reported).
    """
    device_id = None
    if isinstance(request.data, dict):
        device_id = request.data.get('device_id')

    if device_id:
        bins = list(SmartBin.objects.filter(bin_id=str(device_id).strip()))
        if not bins:
            return Response(
                {'error': f"Unknown device '{device_id}'. Register it in /admin/ first."},
                status=status.HTTP_404_NOT_FOUND,
            )
    else:
        bins = list(SmartBin.objects.all().order_by('bin_id'))
        if not bins:
            return Response({'error': 'No smart bins registered yet.'},
                            status=status.HTTP_404_NOT_FOUND)

    results = []
    for smart_bin in bins:
        fill = min(100.0, max(0.0, smart_bin.fill_level + random.uniform(-3, 6)))
        weight = round(fill / 100 * 25 + random.uniform(-0.5, 0.5), 1)
        weight = max(0.0, weight)
        base_temp = smart_bin.temperature if smart_bin.temperature is not None else 28.0
        temperature = round(min(60.0, max(10.0, base_temp + random.uniform(-1, 1))), 1)
        Telemetry.objects.create(
            smart_bin=smart_bin, fill_level=round(fill, 1),
            weight=weight, temperature=temperature,
            data_source=DataSource.SIMULATED,
        )
        smart_bin.fill_level = round(fill, 1)
        smart_bin.weight = weight
        smart_bin.temperature = temperature
        smart_bin.is_online = True
        smart_bin.last_seen = timezone.now()
        # Never promote to REAL here — only genuine ESP32 POSTs do that.
        smart_bin.save(update_fields=[
            'fill_level', 'weight', 'temperature',
            'is_online', 'last_seen', 'updated_at',
        ])
        results.append(_bin_payload(smart_bin))
    refresh_online_flags()
    return Response(results, status=status.HTTP_201_CREATED)
