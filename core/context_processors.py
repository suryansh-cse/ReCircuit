"""Template context: live active-alert counts for nav/dashboard (DB-backed)."""


def alert_counts(request):
    from .models import Alert
    active = Alert.objects.filter(is_active=True)
    return {
        'active_alert_count': active.count(),
        'active_critical_count': active.filter(severity='critical').count(),
    }
