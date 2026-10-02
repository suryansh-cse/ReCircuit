"""Template context: live active-alert counts for nav/dashboard (DB-backed)."""


def alert_counts(request):
    from .models import Alert, is_collector, is_ops_staff
    active = Alert.objects.filter(is_active=True)
    user = getattr(request, 'user', None)
    authed = bool(user is not None and getattr(user, 'is_authenticated', False))
    collector = is_collector(user) if authed else False
    staff = is_ops_staff(user) if authed else False
    my_tasks = 0
    if collector and not staff:
        from waste.models import CollectionTask
        my_tasks = CollectionTask.objects.filter(
            assigned_to=user,
            status__in=CollectionTask.ACTIVE_STATUSES,
        ).count()
    return {
        'active_alert_count': active.count(),
        'active_critical_count': active.filter(severity='critical').count(),
        'is_collector_user': collector,
        'is_ops_staff': staff,
        'my_active_tasks': my_tasks,
    }
