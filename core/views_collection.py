"""Day 6 collection operations views — admin ops + collector dashboards.

Auth model (backend-enforced, never trust the frontend):
- Operations dashboard / assign / cancel / collector management → staff only.
- My tasks / start / complete → the assigned collector (staff may also act).
- Task detail → staff, assigned collector, or pickup owner.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.models import Profile, is_collector, is_ops_staff
from waste.collections import (
    TaskTransitionError,
    assign_task,
    cancel_task,
    complete_task,
    ensure_pickup_task,
    may_view_task,
    start_task,
)
from waste.models import CollectionTask, PickupRequest


def _require_staff(request):
    if not is_ops_staff(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('Staff permission required.')
    return None


def _collectors_qs():
    return User.objects.filter(
        profile__role=Profile.Role.COLLECTOR
    ).select_related('profile').order_by('username')


# ---------- Admin / operations ----------

@login_required
def ops_dashboard(request):
    """Staff-only operations control center (Day 8: central, DB-driven).

    Sections: pickup requests (incl. orphans missing tasks), collection
    tasks (existing filterable queue, unchanged), bins needing collection,
    active alerts, recent submissions, recycling summary. Every number is a
    live database aggregate.
    """
    denied = _require_staff(request)
    if denied is not None:
        return denied
    from bins.models import SmartBin
    from core.alerts import monitoring_summary
    from core.models import Alert
    from waste.collections import orphan_pickups
    from waste.models import EwasteSubmission
    from waste.recycling import recycling_summary

    tasks = CollectionTask.objects.select_related(
        'smart_bin', 'pickup_request', 'pickup_request__user',
        'assigned_to', 'assigned_to__profile', 'created_from_alert',
    ).order_by('-created_at')
    status_f = request.GET.get('status', '')
    priority_f = request.GET.get('priority', '')
    source_f = request.GET.get('source', '')
    if status_f in dict(CollectionTask.Status.choices):
        tasks = tasks.filter(status=status_f)
    if priority_f in dict(CollectionTask.Priority.choices):
        tasks = tasks.filter(priority=priority_f)
    if source_f == 'bin':
        tasks = tasks.filter(smart_bin__isnull=False)
    elif source_f == 'pickup':
        tasks = tasks.filter(pickup_request__isnull=False)
    counts = {
        row['status']: row['n']
        for row in CollectionTask.objects.values('status').annotate(n=Count('id'))
    }
    stats = {
        'pending': counts.get('pending', 0),
        'assigned': counts.get('assigned', 0),
        'in_transit': counts.get('in_transit', 0),
        'collected': counts.get('collected', 0),
        'cancelled': counts.get('cancelled', 0),
        'total': sum(counts.values()),
    }
    paginator = Paginator(tasks, 25)
    page = paginator.get_page(request.GET.get('page'))
    collectors = list(_collectors_qs())

    # --- Day 8 control-center context (all live DB rows) ---
    orphans = list(orphan_pickups()[:10])
    recent_pickups = list(PickupRequest.objects.select_related('user').order_by('-created_at')[:10])
    active_task_by_pickup = {
        t.pickup_request_id: t
        for t in CollectionTask.objects.filter(
            pickup_request__in=[p.pk for p in recent_pickups] + [p.pk for p in orphans],
            status__in=CollectionTask.ACTIVE_STATUSES,
        ).select_related('assigned_to')
    }
    for p in list(recent_pickups) + orphans:
        p.active_task = active_task_by_pickup.get(p.pk)
    full_bins = list(SmartBin.objects.filter(fill_level__gte=80.0).order_by('-fill_level')[:8])
    active_alerts = list(
        Alert.objects.filter(is_active=True).select_related('bin').order_by('-created_at')[:8])
    recent_submissions = list(
        EwasteSubmission.objects.select_related('user', 'smart_bin').order_by('-created_at')[:8])
    recycling = recycling_summary()
    monitoring = monitoring_summary()
    control_stats = {
        'total_pickups': PickupRequest.objects.count(),
        'pending_pickups': PickupRequest.objects.filter(
            status=PickupRequest.Status.PENDING).count(),
        'active_collections': CollectionTask.objects.filter(
            status__in=CollectionTask.ACTIVE_STATUSES).count(),
        'bins_needing': SmartBin.objects.filter(fill_level__gte=80.0).count(),
        'active_alerts': monitoring['active_alerts'],
        'total_ewaste': recycling['total_weight'],
        'recycled_weight': recycling['by_status']['recycled']['weight'],
    }
    return render(request, 'core/collections_ops.html', {
        'stats': stats, 'page': page,
        'status_f': status_f, 'priority_f': priority_f, 'source_f': source_f,
        'status_choices': CollectionTask.Status.choices,
        'priority_choices': CollectionTask.Priority.choices,
        'collectors': collectors,
        'control_stats': control_stats,
        'orphans': orphans,
        'recent_pickups': recent_pickups,
        'full_bins': full_bins,
        'active_alerts': active_alerts,
        'recent_submissions': recent_submissions,
        'recycling': recycling,
    })


@login_required
def task_detail(request, pk):
    """History/detail page — staff, assigned collector, or pickup owner."""
    task = get_object_or_404(
        CollectionTask.objects.select_related(
            'smart_bin', 'pickup_request', 'pickup_request__user',
            'assigned_to', 'assigned_to__profile', 'created_from_alert',
        ), pk=pk,
    )
    if not may_view_task(task, request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('You cannot view this task.')
    collectors = list(_collectors_qs()) if is_ops_staff(request.user) else []
    return render(request, 'core/collections_detail.html', {
        'task': task, 'collectors': collectors,
        'is_staff': is_ops_staff(request.user),
        'is_collector': is_collector(request.user),
    })


@login_required
@require_POST
def task_assign(request, pk):
    """Staff assigns/reassigns a collector (validates collector role)."""
    denied = _require_staff(request)
    if denied is not None:
        return denied
    task = get_object_or_404(CollectionTask, pk=pk)
    collector_id = request.POST.get('collector_id', '').strip()
    try:
        collector = User.objects.select_related('profile').get(pk=collector_id)
    except (User.DoesNotExist, ValueError):
        messages.error(request, 'Select a valid collector.')
        return redirect('collection-task-detail', pk=pk)
    try:
        assign_task(task, collector)
    except TaskTransitionError as exc:
        messages.error(request, str(exc))
        return redirect('collection-task-detail', pk=pk)
    messages.success(
        request, f'Task #{task.pk} assigned to {collector.username}.')
    return redirect('collection-task-detail', pk=pk)


@login_required
@require_POST
def task_cancel(request, pk):
    """Staff cancels an unfinished task."""
    denied = _require_staff(request)
    if denied is not None:
        return denied
    task = get_object_or_404(CollectionTask, pk=pk)
    try:
        cancel_task(task)
    except TaskTransitionError as exc:
        messages.error(request, str(exc))
        return redirect('collection-task-detail', pk=pk)
    messages.info(request, f'Task #{task.pk} cancelled.')
    return redirect('collection-task-detail', pk=pk)


@login_required
@require_POST
def task_ensure_pickup(request, pickup_id):
    """Staff creates the (idempotent) task for a pickup that lacks one."""
    denied = _require_staff(request)
    if denied is not None:
        return denied
    pickup = get_object_or_404(PickupRequest, pk=pickup_id)
    task, created = ensure_pickup_task(pickup)
    if created:
        messages.success(
            request, f'Collection task #{task.pk} created for pickup #{pickup.pk}.')
    else:
        messages.info(
            request, f'Pickup #{pickup.pk} already has active task #{task.pk}.')
    return redirect('collection-task-detail', pk=task.pk)


# ---------- Collector ----------

@login_required
def my_tasks(request):
    """Collector sees ONLY their assigned tasks (staff see hint to ops)."""
    if is_ops_staff(request.user) and not is_collector(request.user):
        messages.info(request, 'Staff view: operations dashboard shows all tasks.')
        return redirect('collections-ops')
    if not is_collector(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('Collector account required.')
    tasks = CollectionTask.objects.select_related(
        'smart_bin', 'pickup_request', 'pickup_request__user',
        'created_from_alert',
    ).filter(assigned_to=request.user).order_by('-created_at')
    status_f = request.GET.get('status', '')
    if status_f in dict(CollectionTask.Status.choices):
        tasks = tasks.filter(status=status_f)
    active = tasks.filter(status__in=CollectionTask.ACTIVE_STATUSES)
    done = tasks.filter(status__in=CollectionTask.TERMINAL_STATUSES)
    return render(request, 'core/collections_mine.html', {
        'active_tasks': active, 'done_tasks': done,
        'status_f': status_f,
    })


def _operate(request, pk, action):
    """Shared start/complete handler: ownership enforced in service layer."""
    task = get_object_or_404(CollectionTask, pk=pk)
    if not (is_collector(request.user) or is_ops_staff(request.user)):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('Collector account required.')
    try:
        if action == 'start':
            start_task(task, by_user=request.user)
            messages.success(request, f'Task #{task.pk} is now In Transit.')
        else:
            complete_task(task, by_user=request.user)
            messages.success(
                request,
                f'Task #{task.pk} marked Collected. Alert resolved — '
                'bin level will be verified by the next sensor reading.')
    except TaskTransitionError as exc:
        messages.error(request, str(exc))
    # Collectors return to their list; staff return to the detail page.
    if is_ops_staff(request.user) and not (
            is_collector(request.user) and task.assigned_to_id == request.user.pk):
        return redirect('collection-task-detail', pk=pk)
    return redirect('my-tasks')


@login_required
@require_POST
def task_start(request, pk):
    return _operate(request, pk, 'start')


@login_required
@require_POST
def task_complete(request, pk):
    return _operate(request, pk, 'complete')


# ---------- Collector accounts (staff) ----------

@login_required
def collectors_manage(request):
    """Staff creates/deactivates collector accounts (reuses User + Profile)."""
    denied = _require_staff(request)
    if denied is not None:
        return denied
    collectors = list(_collectors_qs())
    for c in collectors:
        c.task_counts = {
            'active': c.collection_tasks.filter(
                status__in=CollectionTask.ACTIVE_STATUSES).count(),
            'done': c.collection_tasks.filter(
                status__in=CollectionTask.TERMINAL_STATUSES).count(),
        }
    return render(request, 'core/collectors_manage.html', {
        'collectors': collectors,
    })


@login_required
@require_POST
def collectors_create(request):
    denied = _require_staff(request)
    if denied is not None:
        return denied
    username = request.POST.get('username', '').strip()
    password = request.POST.get('password', '').strip()
    full_name = request.POST.get('full_name', '').strip()
    phone = request.POST.get('phone', '').strip()
    employee_id = request.POST.get('employee_id', '').strip()
    if not username or not password or len(password) < 8:
        messages.error(request, 'Username and a password of 8+ characters are required.')
        return redirect('collectors-manage')
    if User.objects.filter(username__iexact=username).exists():
        messages.error(request, f'Username "{username}" is already taken.')
        return redirect('collectors-manage')
    user = User.objects.create_user(username=username, password=password)
    Profile.objects.update_or_create(
        user=user,
        defaults={'full_name': full_name, 'phone': phone,
                  'role': Profile.Role.COLLECTOR,
                  'employee_id': employee_id, 'is_collector_active': True},
    )
    messages.success(request, f'Collector "{username}" created.')
    return redirect('collectors-manage')


@login_required
@require_POST
def collectors_toggle(request, pk):
    denied = _require_staff(request)
    if denied is not None:
        return denied
    user = get_object_or_404(User, pk=pk)
    profile = getattr(user, 'profile', None)
    if profile is None or profile.role != Profile.Role.COLLECTOR:
        messages.error(request, 'Not a collector account.')
        return redirect('collectors-manage')
    profile.is_collector_active = not profile.is_collector_active
    profile.save(update_fields=['is_collector_active'])
    state = 'activated' if profile.is_collector_active else 'deactivated'
    messages.info(request, f'Collector "{user.username}" {state}.')
    return redirect('collectors-manage')
