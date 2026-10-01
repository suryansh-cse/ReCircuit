"""Core models: user profile + system alerts.

Why these live in `core`:
- Profile extends Django's built-in User without replacing it (simplest auth).
- Alert is cross-cutting (bins, pickups, system) so it belongs in the shared app.
"""
from django.conf import settings
from django.db import models


class Profile(models.Model):
    """One-to-one extension of Django's User for ReCircuit users."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile'
    )
    full_name = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Profile({self.user.username})'


class Alert(models.Model):
    """System alert from the Day 5 alert engine (fill / temperature / offline).

    One active alert per (bin, alert_type) — the service updates severity in
    place instead of creating duplicates. pickup stays for Day 6 collections.
    """

    class AlertType(models.TextChoices):
        FILL_LEVEL = 'fill_level', 'Fill Level (80%+)'
        DEVICE_OFFLINE = 'device_offline', 'Device Offline'
        HIGH_TEMPERATURE = 'high_temperature', 'High Temperature'
        SYSTEM = 'system', 'System'

    class Severity(models.TextChoices):
        INFO = 'info', 'Info'
        WARNING = 'warning', 'Warning'
        CRITICAL = 'critical', 'Critical'

    alert_type = models.CharField(max_length=20, choices=AlertType.choices)
    severity = models.CharField(
        max_length=10, choices=Severity.choices, default=Severity.INFO
    )
    # Nullable links — an alert may relate to a bin and/or a pickup.
    # String references avoid circular imports between apps.
    bin = models.ForeignKey(
        'bins.SmartBin',
        null=True, blank=True,
        on_delete=models.SET_NULL, related_name='alerts',
    )
    pickup = models.ForeignKey(
        'waste.PickupRequest',
        null=True, blank=True,
        on_delete=models.SET_NULL, related_name='alerts',
    )
    message = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['is_active']),
            models.Index(fields=['bin', 'is_active']),
        ]

    def __str__(self):
        state = 'ACTIVE' if self.is_active else 'resolved'
        return f'[{self.severity}/{state}] {self.alert_type}: {self.message[:50]}'
