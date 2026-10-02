"""Day 5 alert engine — single home for all alert rules.

Reuse rule: views and APIs never contain threshold logic; they call
process_bin_alerts() / sweep_offline_alerts() here. Thresholds come only
from config.settings (RECIRCUIT_*), never hardcoded.

Dedupe rule: one active alert per (bin, alert_type). Rising severity updates
the existing row in place; recovery resolves it. No alert storms.
"""
from django.conf import settings
from django.utils import timezone

from .models import Alert


def temp_thresholds():
    """(warning_at, critical_at) in °C from central settings."""
    return (
        getattr(settings, 'RECIRCUIT_TEMP_WARNING_AT', 40.0),
        getattr(settings, 'RECIRCUIT_TEMP_CRITICAL_AT', 45.0),
    )


def _get_active(smart_bin, alert_type):
    return Alert.objects.filter(
        bin=smart_bin, alert_type=alert_type, is_active=True
    ).first()


def _raise(smart_bin, alert_type, severity, message):
    """Create the active alert, or update severity/message if one exists."""
    existing = _get_active(smart_bin, alert_type)
    if existing:
        if existing.severity != severity or existing.message != message:
            existing.severity = severity
            existing.message = message
            existing.save(update_fields=['severity', 'message'])
        return existing, False
    return Alert.objects.create(
        bin=smart_bin, alert_type=alert_type,
        severity=severity, message=message, is_active=True,
    ), True


def _resolve(smart_bin, alert_type):
    """Resolve the active alert of this type, if any. Returns bool resolved."""
    existing = _get_active(smart_bin, alert_type)
    if existing:
        existing.is_active = False
        existing.resolved_at = timezone.now()
        existing.save(update_fields=['is_active', 'resolved_at'])
        return True
    return False


def check_fill_alert(smart_bin):
    """Fill >= 80% → active CRITICAL FILL_LEVEL; below → resolve.

    Day 6: an active fill alert also ensures exactly one active
    CollectionTask (dedupe lives in waste.collections.ensure_bin_task).
    """
    critical_at = getattr(settings, 'RECIRCUIT_FILL_CRITICAL_AT', 80.0)
    if smart_bin.fill_level >= critical_at:
        alert, _ = _raise(
            smart_bin, Alert.AlertType.FILL_LEVEL, Alert.Severity.CRITICAL,
            f'{smart_bin.bin_id} fill level has reached '
            f'{smart_bin.fill_level:.0f}%. Collection required.',
        )
        # Operational follow-through — never let telemetry failures break
        # monitoring, so task creation must not raise.
        try:
            from waste.collections import ensure_bin_task
            ensure_bin_task(smart_bin, alert=alert)
        except Exception:
            pass
        return alert, False
    _resolve(smart_bin, Alert.AlertType.FILL_LEVEL)
    return None, False


def check_temperature_alert(smart_bin):
    """Temp >= warn/crit → active HIGH_TEMPERATURE (severity escalates in place)."""
    warn_at, critical_at = temp_thresholds()
    temp = smart_bin.temperature
    if temp is None:
        return None, False
    if temp >= critical_at:
        return _raise(
            smart_bin, Alert.AlertType.HIGH_TEMPERATURE, Alert.Severity.CRITICAL,
            f'{smart_bin.bin_id} temperature {temp:.1f}°C is at/above the critical '
            f'threshold ({critical_at:.0f}°C).',
        )
    if temp >= warn_at:
        return _raise(
            smart_bin, Alert.AlertType.HIGH_TEMPERATURE, Alert.Severity.WARNING,
            f'{smart_bin.bin_id} temperature {temp:.1f}°C is above the warning '
            f'threshold ({warn_at:.0f}°C).',
        )
    _resolve(smart_bin, Alert.AlertType.HIGH_TEMPERATURE)
    return None, False


def check_offline_alert(smart_bin, online_now):
    """No recent telemetry → active DEVICE_OFFLINE; telemetry back → resolve."""
    if online_now:
        _resolve(smart_bin, Alert.AlertType.DEVICE_OFFLINE)
        return None, False
    return _raise(
        smart_bin, Alert.AlertType.DEVICE_OFFLINE, Alert.Severity.WARNING,
        f'{smart_bin.bin_id} has not sent telemetry recently.',
    )


def process_bin_alerts(smart_bin, *, online_now=True):
    """Run fill + temperature + offline checks for one bin.

    Called by the telemetry ingest and simulate endpoints after every reading.
    Returns the list of currently-active alerts for the bin.
    """
    check_fill_alert(smart_bin)
    check_temperature_alert(smart_bin)
    check_offline_alert(smart_bin, online_now)
    return list(Alert.objects.filter(bin=smart_bin, is_active=True))


def sweep_offline_alerts():
    """Idempotent background-style sweep for bins with NO fresh telemetry.

    Called lazily from bin monitoring views/APIs (same pattern as
    refresh_online_flags): raises DEVICE_OFFLINE for stale bins, resolves it
    for bins that are currently online.
    """
    from bins.models import SmartBin, is_online_for, refresh_online_flags
    refresh_online_flags()
    now = timezone.now()
    for smart_bin in SmartBin.objects.all().only(
            'id', 'bin_id', 'fill_level', 'temperature', 'last_seen'):
        check_offline_alert(smart_bin, is_online_for(smart_bin.last_seen, now))


def monitoring_summary():
    """DB-backed monitoring numbers for dashboards (bins + alerts).

    Returns dict: total_bins, online_bins, offline_bins, normal_bins,
    warning_bins, critical_bins, active_alerts, critical_alerts, warning_alerts.
    """
    from bins.models import SmartBin, refresh_online_flags
    refresh_online_flags()
    bins = list(SmartBin.objects.all())
    summary = {
        'total_bins': len(bins),
        'online_bins': sum(1 for b in bins if b.is_online),
        'offline_bins': sum(1 for b in bins if not b.is_online),
        'normal_bins': 0, 'warning_bins': 0, 'critical_bins': 0,
    }
    for b in bins:
        summary[f'{b.status_code}_bins'] += 1
    active = Alert.objects.filter(is_active=True)
    summary['active_alerts'] = active.count()
    summary['critical_alerts'] = active.filter(severity=Alert.Severity.CRITICAL).count()
    summary['warning_alerts'] = active.filter(severity=Alert.Severity.WARNING).count()
    return summary
