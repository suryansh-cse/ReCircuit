"""Day 6 collection service — single home for task rules.

Reuse rule: views and APIs never contain priority/dedupe/transition logic;
they call these helpers. Thresholds come from config.settings.

Dedupe rule: one ACTIVE task per source (bin or pickup). Active =
PENDING / ASSIGNED / IN_TRANSIT. COLLECTED / CANCELLED are terminal and
do not block a fresh task (e.g. bin fills up again after a collection).
"""
from django.utils import timezone


def priority_for_fill(fill_level: float) -> str:
    """80-89% -> HIGH, 90-100% -> CRITICAL (spec Step 5)."""
    from waste.models import CollectionTask
    if fill_level >= 90:
        return CollectionTask.Priority.CRITICAL
    if fill_level >= 80:
        return CollectionTask.Priority.HIGH
    return CollectionTask.Priority.NORMAL


def has_active_bin_task(smart_bin) -> bool:
    from waste.models import CollectionTask
    return CollectionTask.objects.filter(
        smart_bin=smart_bin, status__in=CollectionTask.ACTIVE_STATUSES,
    ).exists()


def has_active_pickup_task(pickup) -> bool:
    from waste.models import CollectionTask
    return CollectionTask.objects.filter(
        pickup_request=pickup, status__in=CollectionTask.ACTIVE_STATUSES,
    ).exists()


def ensure_bin_task(smart_bin, alert=None):
    """Create a task for a full bin unless an active one exists.

    Returns (task, created). Priority derives from current fill level.
    Never raises when fill < 80 — returns (None, False).
    """
    from django.conf import settings

    from waste.models import CollectionTask
    critical_at = getattr(settings, 'RECIRCUIT_FILL_CRITICAL_AT', 80.0)
    if smart_bin.fill_level < critical_at:
        return None, False
    existing = CollectionTask.objects.filter(
        smart_bin=smart_bin, status__in=CollectionTask.ACTIVE_STATUSES,
    ).order_by('-created_at').first()
    if existing:
        # Keep priority in step with the latest reading.
        want = priority_for_fill(smart_bin.fill_level)
        if existing.priority != want:
            existing.priority = want
            existing.save(update_fields=['priority', 'updated_at'])
        # Link the alert if the task was created before the alert row existed.
        if alert is not None and existing.created_from_alert_id is None:
            existing.created_from_alert = alert
            existing.save(update_fields=['created_from_alert', 'updated_at'])
        return existing, False
    task = CollectionTask.objects.create(
        smart_bin=smart_bin,
        created_from_alert=alert,
        priority=priority_for_fill(smart_bin.fill_level),
        status=CollectionTask.Status.PENDING,
        fill_level_at_creation=smart_bin.fill_level,
        weight_at_creation=smart_bin.weight,
        notes=f'Auto-created: {smart_bin.bin_id} at {smart_bin.fill_level:.0f}% fill. Collection required.',
    )
    return task, True


def ensure_pickup_task(pickup):
    """Create a NORMAL task for a user pickup unless an active one exists."""
    from waste.models import CollectionTask
    existing = CollectionTask.objects.filter(
        pickup_request=pickup, status__in=CollectionTask.ACTIVE_STATUSES,
    ).order_by('-created_at').first()
    if existing:
        return existing, False
    task = CollectionTask.objects.create(
        pickup_request=pickup,
        priority=CollectionTask.Priority.NORMAL,
        status=CollectionTask.Status.PENDING,
        weight_at_creation=pickup.estimated_weight,
        notes=f'Pickup #{pickup.pk} requested by {pickup.user}.',
    )
    return task, True


# ---------- State transitions (validation lives here, not in views) ----------

class TaskTransitionError(ValueError):
    """Invalid status change — views/APIs translate this to 400/messages."""


def _sync_pickup(task, status_value):
    """Mirror task progress onto the linked PickupRequest (Day 3 safe)."""
    from waste.models import PickupRequest
    if task.pickup_request_id is None:
        return
    mapping = {
        'assigned': PickupRequest.Status.ASSIGNED,
        'in_transit': PickupRequest.Status.IN_TRANSIT,
        'collected': PickupRequest.Status.COLLECTED,
    }
    if status_value in mapping:
        pickup = task.pickup_request
        if pickup.status != mapping[status_value]:
            pickup.status = mapping[status_value]
            pickup.save(update_fields=['status', 'updated_at'])


def assign_task(task, collector_user):
    """PENDING/CANCELLED/ASSIGNED -> ASSIGNED. Sets assigned_at, syncs pickup."""
    from core.models import ensure_profile, is_collector

    from waste.models import CollectionTask
    if not is_collector(collector_user):
        raise TaskTransitionError('Collector account is not an active collector.')
    ensure_profile(collector_user)
    if not collector_user.profile.is_collector_active:
        raise TaskTransitionError('Collector account is deactivated.')
    if task.status == CollectionTask.Status.COLLECTED:
        raise TaskTransitionError('Collected tasks cannot be reassigned.')
    if task.status == CollectionTask.Status.IN_TRANSIT:
        raise TaskTransitionError(
            'Task already in transit — cancel it before reassigning.')
    task.assigned_to = collector_user
    task.status = CollectionTask.Status.ASSIGNED
    task.assigned_at = timezone.now()
    task.save(update_fields=['assigned_to', 'status', 'assigned_at', 'updated_at'])
    _sync_pickup(task, 'assigned')
    return task


def start_task(task, by_user=None):
    """ASSIGNED -> IN_TRANSIT. Only the assigned collector (or staff)."""
    from waste.models import CollectionTask
    if task.status != CollectionTask.Status.ASSIGNED:
        raise TaskTransitionError(
            f'Cannot start a task with status {task.get_status_display()}. '
            'Expected Assigned.'
        )
    if by_user is not None and not _may_operate(task, by_user):
        raise TaskTransitionError('You are not assigned to this task.')
    task.status = CollectionTask.Status.IN_TRANSIT
    task.started_at = timezone.now()
    task.save(update_fields=['status', 'started_at', 'updated_at'])
    _sync_pickup(task, 'in_transit')
    return task


def complete_task(task, by_user=None):
    """IN_TRANSIT -> COLLECTED. Resolves the source fill alert (operational).

    IMPORTANT: SmartBin.fill_level is NOT changed here. The fill sensor is
    the only source of truth — the next ESP32/simulated reading verifies
    the emptying. Resolving the alert records the operational event; if the
    bin still reads >=80% on the next reading, a fresh alert + task appear.
    """
    from django.utils import timezone as tz

    from waste.models import CollectionTask
    if task.status != CollectionTask.Status.IN_TRANSIT:
        raise TaskTransitionError(
            f'Cannot complete a task with status {task.get_status_display()}. '
            'Expected In Transit.'
        )
    if by_user is not None and not _may_operate(task, by_user):
        raise TaskTransitionError('You are not assigned to this task.')
    task.status = CollectionTask.Status.COLLECTED
    task.completed_at = timezone.now()
    task.save(update_fields=['status', 'completed_at', 'updated_at'])
    _sync_pickup(task, 'collected')
    # Resolve the linked fill alert + any active fill alert for the bin.
    resolved = []
    candidates = []
    if task.created_from_alert_id is not None:
        candidates.append(task.created_from_alert)
    if task.smart_bin_id is not None:
        from core.models import Alert
        candidates.extend(
            Alert.objects.filter(
                bin_id=task.smart_bin_id,
                alert_type=Alert.AlertType.FILL_LEVEL, is_active=True,
            )
        )
    seen = set()
    for alert in candidates:
        if alert.pk in seen:
            continue
        seen.add(alert.pk)
        if alert.is_active:
            alert.is_active = False
            alert.resolved_at = tz.now()
            alert.save(update_fields=['is_active', 'resolved_at'])
            resolved.append(alert.pk)
    return task


def cancel_task(task):
    """Cancel an unfinished task. Pickup reverts to PENDING so it can retry."""
    from waste.models import CollectionTask, PickupRequest
    if task.status == CollectionTask.Status.COLLECTED:
        raise TaskTransitionError('Collected tasks cannot be cancelled.')
    if task.status == CollectionTask.Status.CANCELLED:
        return task
    task.status = CollectionTask.Status.CANCELLED
    task.save(update_fields=['status', 'updated_at'])
    if task.pickup_request_id is not None:
        pickup = task.pickup_request
        if pickup.status in (PickupRequest.Status.ASSIGNED,
                             PickupRequest.Status.IN_TRANSIT):
            pickup.status = PickupRequest.Status.PENDING
            pickup.save(update_fields=['status', 'updated_at'])
    # Bin fill alerts intentionally stay active on cancel — the bin still
    # needs collection, and ops can create a fresh task.
    return task


def _may_operate(task, user) -> bool:
    """Collector may operate only their own task; staff may operate any."""
    from core.models import is_ops_staff
    if is_ops_staff(user):
        return True
    return task.assigned_to_id is not None and task.assigned_to_id == user.pk


def may_view_task(task, user) -> bool:
    """Staff see all; collectors see their own; pickup owners see their own."""
    from core.models import is_collector, is_ops_staff
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    if is_ops_staff(user):
        return True
    if is_collector(user) and task.assigned_to_id == user.pk:
        return True
    if task.pickup_request_id is not None and task.pickup_request.user_id == user.pk:
        return True
    return False
