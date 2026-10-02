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

from bins.models import DataSource, SmartBin, Telemetry
from waste.models import Collection, EwasteSubmission, PickupRequest

from .alerts import process_bin_alerts, sweep_offline_alerts

User = get_user_model()


@api_view(['GET'])
def dashboard_stats(request):
    sweep_offline_alerts()
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

    from .alerts import monitoring_summary
    monitoring = monitoring_summary()
    from waste.recycling import recycling_summary
    recycling = recycling_summary()

    return Response({
        'total_users': total_users,
        'total_bins': total_bins,
        'online_bins': online_bins,
        'offline_bins': offline_bins,
        'full_bins': full_bins,
        'total_ewaste_kg': total_ewaste_kg,
        'pending_pickups': pending_pickups,
        'total_pickups': total_pickups,
        # Day 5 monitoring (additive — Day 1 fields unchanged)
        'normal_bins': monitoring['normal_bins'],
        'warning_bins': monitoring['warning_bins'],
        'critical_bins': monitoring['critical_bins'],
        'active_alerts': monitoring['active_alerts'],
        'critical_alerts': monitoring['critical_alerts'],
        'warning_alerts': monitoring['warning_alerts'],
        # Day 7 recycling aggregates (additive — Day 1 fields unchanged)
        'total_submissions': recycling['total_submissions'],
        'recycled_count': recycling['by_status']['recycled']['count'],
        'recycled_weight': recycling['by_status']['recycled']['weight'],
        'processing_count': recycling['by_status']['processing']['count'],
        'qr_verified': recycling['qr_verified'],
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
    sweep_offline_alerts()
    bins = SmartBin.objects.all().order_by('bin_id')
    return Response([_bin_payload(b) for b in bins])


@api_view(['GET'])
def bin_detail_api(request, bin_id):
    """GET /api/bins/<bin_id>/ — public JSON for one bin, 404 if unknown."""
    sweep_offline_alerts()
    try:
        smart_bin = SmartBin.objects.get(bin_id=bin_id)
    except SmartBin.DoesNotExist:
        return Response({'error': 'Smart bin not found.'},
                        status=status.HTTP_404_NOT_FOUND)
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
        return Response({'error': 'Invalid telemetry data.', 'details': errors},
                        status=status.HTTP_400_BAD_REQUEST)

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
    sweep_offline_alerts()
    process_bin_alerts(smart_bin, online_now=True)
    payload = _bin_payload(smart_bin)
    payload['reading_id'] = reading.pk
    return Response(payload, status=status.HTTP_201_CREATED)


@api_view(['POST'])
def telemetry_simulate(request):
    """POST /api/telemetry/simulate/ — SIMULATED demo readings (no hardware).

    Body {"device_id": "ECO-BIN-001"} simulates one bin; empty body simulates all.
    Optional explicit values {"device_id": ..., "fill_level": 90, "weight": 22.5,
    "temperature": 32} store exactly those (validated, for scenario testing).
    Otherwise values random-walk from current state. Rows and bins stay labelled
    SIMULATED unless a real device reported — never presented as hardware data.
    """
    data = request.data if isinstance(request.data, dict) else {}
    device_id = data.get('device_id')

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

    explicit = any(k in data for k in ('fill_level', 'weight', 'temperature'))
    if explicit:
        errors, cleaned = _validate_telemetry_payload({
            'device_id': (bins[0].bin_id if len(bins) == 1 else device_id),
            'fill_level': data.get('fill_level'),
            'weight': data.get('weight'),
            'temperature': data.get('temperature'),
        })
        if errors:
            return Response({'error': 'Invalid telemetry data.', 'details': errors},
                            status=status.HTTP_400_BAD_REQUEST)

    results = []
    for smart_bin in bins:
        if explicit:
            fill, weight, temperature = (
                cleaned['fill_level'], cleaned['weight'], cleaned['temperature'])
        else:
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
        process_bin_alerts(smart_bin, online_now=True)
        results.append(_bin_payload(smart_bin))
    sweep_offline_alerts()
    return Response(results, status=status.HTTP_201_CREATED)


def _alert_payload(alert):
    return {
        'id': alert.pk,
        'bin_id': alert.bin.bin_id if alert.bin else None,
        'alert_type': alert.alert_type,
        'alert_type_display': alert.get_alert_type_display(),
        'severity': alert.severity,
        'message': alert.message,
        'is_active': alert.is_active,
        'created_at': alert.created_at.isoformat(),
        'resolved_at': alert.resolved_at.isoformat() if alert.resolved_at else None,
    }


@api_view(['GET'])
def alert_list_api(request):
    """GET /api/alerts/?active=true&severity=critical&bin=ECO-BIN-001."""
    from .models import Alert
    alerts = Alert.objects.select_related('bin').all().order_by('-created_at')
    active = request.GET.get('active')
    if active == 'true':
        alerts = alerts.filter(is_active=True)
    elif active == 'false':
        alerts = alerts.filter(is_active=False)
    severity = request.GET.get('severity')
    if severity:
        alerts = alerts.filter(severity=severity)
    bin_id = request.GET.get('bin')
    if bin_id:
        alerts = alerts.filter(bin__bin_id=bin_id)
    return Response([_alert_payload(a) for a in alerts[:100]])


@api_view(['GET'])
def alert_detail_api(request, pk):
    """GET /api/alerts/<id>/ — 404 JSON if unknown."""
    from .models import Alert
    try:
        alert = Alert.objects.select_related('bin').get(pk=pk)
    except Alert.DoesNotExist:
        return Response({'error': 'Alert not found.'},
                        status=status.HTTP_404_NOT_FOUND)
    return Response(_alert_payload(alert))


@api_view(['POST'])
def alert_resolve_api(request, pk):
    """POST /api/alerts/<id>/resolve/ — staff only (403 for anyone else)."""
    from django.utils import timezone as tz

    from .models import Alert
    if not request.user.is_authenticated or not request.user.is_staff:
        return Response({'error': 'Staff permission required.'},
                        status=status.HTTP_403_FORBIDDEN)
    try:
        alert = Alert.objects.get(pk=pk)
    except Alert.DoesNotExist:
        return Response({'error': 'Alert not found.'},
                        status=status.HTTP_404_NOT_FOUND)
    if alert.is_active:
        alert.is_active = False
        alert.resolved_at = tz.now()
        alert.save(update_fields=['is_active', 'resolved_at'])
    return Response(_alert_payload(alert))


@api_view(['GET'])
def bin_history_api(request, bin_id):
    """GET /api/bins/<bin_id>/history/ — last 50 telemetry points for charts."""
    try:
        smart_bin = SmartBin.objects.get(bin_id=bin_id)
    except SmartBin.DoesNotExist:
        return Response({'error': 'Smart bin not found.'},
                        status=status.HTTP_404_NOT_FOUND)
    points = smart_bin.telemetry.all().order_by('-timestamp')[:50]
    return Response([{
        'timestamp': p.timestamp.isoformat(),
        'fill_level': p.fill_level,
        'weight': p.weight,
        'temperature': p.temperature,
        'data_source': p.data_source,
    } for p in reversed(points)])


# ---------- Day 6: collection task APIs ----------

def _task_payload(task):
    return {
        'id': task.pk,
        'status': task.status,
        'status_display': task.get_status_display(),
        'priority': task.priority,
        'priority_display': task.get_priority_display(),
        'source': task.source_label,
        'bin_id': task.smart_bin.bin_id if task.smart_bin else None,
        'bin_location': task.smart_bin.location if task.smart_bin else None,
        'bin_fill': task.smart_bin.fill_level if task.smart_bin else task.fill_level_at_creation,
        'bin_weight': task.smart_bin.weight if task.smart_bin else task.weight_at_creation,
        'pickup_id': task.pickup_request_id,
        'pickup_status': task.pickup_request.status if task.pickup_request else None,
        'assigned_to': task.assigned_to.username if task.assigned_to else None,
        'assigned_to_id': task.assigned_to_id,
        'notes': task.notes,
        'created_at': task.created_at.isoformat(),
        'assigned_at': task.assigned_at.isoformat() if task.assigned_at else None,
        'started_at': task.started_at.isoformat() if task.started_at else None,
        'completed_at': task.completed_at.isoformat() if task.completed_at else None,
    }


def _task_qs_for(user):
    """Staff see all; collectors see own; users see tasks for own pickups."""
    from django.db.models import Q

    from core.models import is_collector, is_ops_staff
    from waste.models import CollectionTask
    qs = CollectionTask.objects.select_related(
        'smart_bin', 'pickup_request', 'assigned_to').order_by('-created_at')
    if is_ops_staff(user):
        return qs
    if is_collector(user):
        return qs.filter(assigned_to=user)
    return qs.filter(pickup_request__user=user)


@api_view(['GET'])
def task_list_api(request):
    """GET /api/collection-tasks/ — scoped to the caller's role."""
    if not request.user.is_authenticated:
        return Response({'error': 'Authentication required.'},
                        status=status.HTTP_403_FORBIDDEN)
    tasks = _task_qs_for(request.user)
    s = request.GET.get('status')
    if s:
        tasks = tasks.filter(status=s)
    return Response([_task_payload(t) for t in tasks[:100]])


@api_view(['GET'])
def task_detail_api(request, pk):
    """GET /api/collection-tasks/<id>/ — 404 for foreign tasks (no leaking)."""
    from waste.collections import may_view_task
    from waste.models import CollectionTask
    if not request.user.is_authenticated:
        return Response({'error': 'Authentication required.'},
                        status=status.HTTP_403_FORBIDDEN)
    try:
        task = CollectionTask.objects.select_related(
            'smart_bin', 'pickup_request', 'assigned_to').get(pk=pk)
    except CollectionTask.DoesNotExist:
        return Response({'error': 'Task not found.'},
                        status=status.HTTP_404_NOT_FOUND)
    if not may_view_task(task, request.user):
        return Response({'error': 'Task not found.'},
                        status=status.HTTP_404_NOT_FOUND)
    return Response(_task_payload(task))


@api_view(['POST'])
def task_assign_api(request, pk):
    """POST /api/collection-tasks/<id>/assign/ — staff only."""
    from django.contrib.auth import get_user_model

    from core.models import is_ops_staff
    from waste.collections import TaskTransitionError, assign_task
    from waste.models import CollectionTask
    if not request.user.is_authenticated or not is_ops_staff(request.user):
        return Response({'error': 'Staff permission required.'},
                        status=status.HTTP_403_FORBIDDEN)
    try:
        task = CollectionTask.objects.get(pk=pk)
    except CollectionTask.DoesNotExist:
        return Response({'error': 'Task not found.'},
                        status=status.HTTP_404_NOT_FOUND)
    collector_id = (request.data or {}).get('collector_id')
    if not collector_id:
        return Response({'error': 'collector_id is required.'},
                        status=status.HTTP_400_BAD_REQUEST)
    try:
        collector = get_user_model().objects.get(pk=collector_id)
    except (get_user_model().DoesNotExist, ValueError, TypeError):
        return Response({'error': 'Unknown collector.'},
                        status=status.HTTP_404_NOT_FOUND)
    try:
        assign_task(task, collector)
    except TaskTransitionError as exc:
        return Response({'error': str(exc)},
                        status=status.HTTP_400_BAD_REQUEST)
    task.refresh_from_db()
    return Response(_task_payload(task))


def _operate_api(request, pk, action):
    from core.models import is_collector, is_ops_staff
    from waste.collections import TaskTransitionError, complete_task, start_task
    from waste.models import CollectionTask
    if not request.user.is_authenticated or not (
            is_collector(request.user) or is_ops_staff(request.user)):
        return Response({'error': 'Collector permission required.'},
                        status=status.HTTP_403_FORBIDDEN)
    try:
        task = CollectionTask.objects.get(pk=pk)
    except CollectionTask.DoesNotExist:
        return Response({'error': 'Task not found.'},
                        status=status.HTTP_404_NOT_FOUND)
    try:
        if action == 'start':
            start_task(task, by_user=request.user)
        elif action == 'complete':
            complete_task(task, by_user=request.user)
        else:
            from waste.collections import cancel_task
            if not is_ops_staff(request.user):
                return Response({'error': 'Staff permission required.'},
                                status=status.HTTP_403_FORBIDDEN)
            cancel_task(task)
    except TaskTransitionError as exc:
        return Response({'error': str(exc)},
                        status=status.HTTP_400_BAD_REQUEST)
    task.refresh_from_db()
    return Response(_task_payload(task))


@api_view(['POST'])
def task_start_api(request, pk):
    """POST /api/collection-tasks/<id>/start/ — own task only."""
    return _operate_api(request, pk, 'start')


@api_view(['POST'])
def task_complete_api(request, pk):
    """POST /api/collection-tasks/<id>/complete/ — own task only."""
    return _operate_api(request, pk, 'complete')


@api_view(['POST'])
def task_cancel_api(request, pk):
    """POST /api/collection-tasks/<id>/cancel/ — staff only."""
    return _operate_api(request, pk, 'cancel')


# ---------- Day 7: traceable e-waste + deposit + recycling ----------

def _ewaste_qs_for(user):
    """Staff see all (explicit ?scope=all); everyone else sees only own."""
    from core.models import is_ops_staff
    from waste.models import EwasteSubmission
    qs = EwasteSubmission.objects.select_related(
        'smart_bin', 'pickup_request', 'user').order_by('-created_at')
    if is_ops_staff(user):
        return qs
    return qs.filter(user=user)


@api_view(['GET', 'POST'])
def ewaste_list_create_api(request):
    """GET /api/ewaste/ (own; staff ?scope=all) · POST (auth, owner=caller)."""
    from core.forms import EwasteSubmissionForm
    from core.models import is_ops_staff
    from waste.models import EwasteSubmission
    from waste.recycling import get_valid_session, submission_payload
    if not request.user.is_authenticated:
        return Response({'error': 'Authentication required.'},
                        status=status.HTTP_403_FORBIDDEN)
    if request.method == 'GET':
        qs = _ewaste_qs_for(request.user)
        if is_ops_staff(request.user) and request.GET.get('scope') != 'all':
            qs = qs.filter(user=request.user)
        return Response([submission_payload(s) for s in qs[:100]])
    # POST — same validation as the HTML form, owner forced server-side.
    data = request.data if isinstance(request.data, dict) else {}
    form = EwasteSubmissionForm(data, user=request.user)
    token = (data.get('session_token') or '').strip()
    session = get_valid_session(request.user, token) if token else None
    if token and session is None:
        return Response(
            {'error': 'Deposit session expired or invalid — scan again.'},
            status=status.HTTP_400_BAD_REQUEST)
    if not form.is_valid():
        return Response({'error': 'Invalid submission.', 'details': form.errors},
                        status=status.HTTP_400_BAD_REQUEST)
    submission = form.save(commit=False)
    submission.user = request.user
    submission.status = EwasteSubmission.Status.SUBMITTED
    submission.submission_method = form.cleaned_data['submission_method']
    submission.smart_bin = form.cleaned_data.get('smart_bin')
    submission.pickup_request = form.cleaned_data.get('pickup_request')
    if submission.submission_method == EwasteSubmission.SubmissionMethod.PICKUP:
        submission.smart_bin = None
    if session is not None:
        if (submission.smart_bin_id is None
                or submission.smart_bin_id != session.smart_bin_id):
            return Response(
                {'error': 'Deposit session is for a different bin.'},
                status=status.HTTP_400_BAD_REQUEST)
        submission.deposit_session = session
        submission.verification_status = (
            EwasteSubmission.VerificationStatus.QR_VERIFIED)
    submission.save()
    if session is not None:
        session.mark_used(submission)
    return Response(submission_payload(submission),
                    status=status.HTTP_201_CREATED)


@api_view(['GET'])
def ewaste_detail_api(request, pk):
    """GET /api/ewaste/<id>/ — owner or staff; 404 otherwise (no leaking)."""
    from waste.models import EwasteSubmission
    from waste.recycling import submission_payload
    if not request.user.is_authenticated:
        return Response({'error': 'Authentication required.'},
                        status=status.HTTP_403_FORBIDDEN)
    try:
        sub = EwasteSubmission.objects.select_related(
            'smart_bin', 'pickup_request', 'user').get(pk=pk)
    except EwasteSubmission.DoesNotExist:
        return Response({'error': 'Submission not found.'},
                        status=status.HTTP_404_NOT_FOUND)
    from core.models import is_ops_staff
    if not is_ops_staff(request.user) and sub.user_id != request.user.pk:
        return Response({'error': 'Submission not found.'},
                        status=status.HTTP_404_NOT_FOUND)
    return Response(submission_payload(sub))


@api_view(['POST'])
def ewaste_advance_api(request, pk):
    """POST /api/ewaste/<id>/advance/ — staff moves lifecycle one step."""
    from core.models import is_ops_staff
    from waste.models import EwasteSubmission
    from waste.recycling import (
        SubmissionTransitionError, advance_submission, submission_payload,
    )
    if not request.user.is_authenticated or not is_ops_staff(request.user):
        return Response({'error': 'Staff permission required.'},
                        status=status.HTTP_403_FORBIDDEN)
    try:
        sub = EwasteSubmission.objects.get(pk=pk)
    except EwasteSubmission.DoesNotExist:
        return Response({'error': 'Submission not found.'},
                        status=status.HTTP_404_NOT_FOUND)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        weight_raw = (data.get('actual_weight') or '')
        advance_submission(
            sub, (data.get('action') or '').strip(), by_user=request.user,
            actual_weight=float(weight_raw) if str(weight_raw).strip() else None,
            partner=str(data.get('partner') or '').strip(),
            notes=str(data.get('notes') or '').strip(),
        )
    except (SubmissionTransitionError, ValueError, TypeError) as exc:
        return Response({'error': str(exc)},
                        status=status.HTTP_400_BAD_REQUEST)
    sub.refresh_from_db()
    return Response(submission_payload(sub))


@api_view(['POST'])
def deposit_start_api(request):
    """POST /api/deposit/start/ {"bin_id": "ECO-BIN-007"} → 5-min session."""
    from waste.recycling import start_deposit_session
    if not request.user.is_authenticated:
        return Response({'error': 'Authentication required.'},
                        status=status.HTTP_403_FORBIDDEN)
    data = request.data if isinstance(request.data, dict) else {}
    bin_id = str(data.get('bin_id') or '').strip()
    try:
        smart_bin = SmartBin.objects.get(bin_id=bin_id)
    except SmartBin.DoesNotExist:
        return Response({'error': f'Unknown SmartBin {bin_id!r}.'},
                        status=status.HTTP_404_NOT_FOUND)
    session = start_deposit_session(request.user, smart_bin)
    return Response({
        'token': session.token,
        'display_id': session.display_id,
        'bin_id': smart_bin.bin_id,
        'expires_at': session.expires_at.isoformat(),
        'submit_url': f'/submit/?bin={smart_bin.bin_id}&session={session.token}',
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
def bin_qr_api(request, bin_id):
    """GET /api/bins/<id>/qr/ — public QR payload (static deposit URL)."""
    try:
        smart_bin = SmartBin.objects.get(bin_id=bin_id)
    except SmartBin.DoesNotExist:
        return Response({'error': 'Smart bin not found.'},
                        status=status.HTTP_404_NOT_FOUND)
    payload = _bin_payload(smart_bin)
    payload['deposit_url'] = request.build_absolute_uri(f'/bins/{bin_id}/deposit/')
    return Response(payload)


def _recycling_payload(record):
    return {
        'id': record.pk,
        'submission_id': record.submission_id,
        'collection_task_id': record.collection_task_id,
        'category': record.category,
        'processing_status': record.processing_status,
        'received_weight': record.received_weight,
        'recycling_partner': record.recycling_partner,
        'notes': record.notes,
        'processed_at': record.processed_at.isoformat() if record.processed_at else None,
        'recycled_at': record.recycled_at.isoformat() if record.recycled_at else None,
        'created_at': record.created_at.isoformat(),
    }


@api_view(['GET'])
def recycling_list_api(request):
    """GET /api/recycling/ — staff only (operational ledger)."""
    from core.models import is_ops_staff
    from waste.models import RecyclingRecord
    if not request.user.is_authenticated or not is_ops_staff(request.user):
        return Response({'error': 'Staff permission required.'},
                        status=status.HTTP_403_FORBIDDEN)
    records = RecyclingRecord.objects.select_related(
        'submission').order_by('-created_at')[:100]
    return Response([_recycling_payload(r) for r in records])


@api_view(['GET'])
def recycling_detail_api(request, pk):
    """GET /api/recycling/<id>/ — staff only."""
    from core.models import is_ops_staff
    from waste.models import RecyclingRecord
    if not request.user.is_authenticated or not is_ops_staff(request.user):
        return Response({'error': 'Staff permission required.'},
                        status=status.HTTP_403_FORBIDDEN)
    try:
        record = RecyclingRecord.objects.get(pk=pk)
    except RecyclingRecord.DoesNotExist:
        return Response({'error': 'Recycling record not found.'},
                        status=status.HTTP_404_NOT_FOUND)
    return Response(_recycling_payload(record))


@api_view(['GET'])
def analytics_recycling_api(request):
    """GET /api/analytics/recycling/ — public aggregates only (no PII)."""
    from waste.recycling import recycling_summary
    return Response(recycling_summary())
