"""Core models: user profile + system alerts.

Why these live in `core`:
- Profile extends Django's built-in User without replacing it (simplest auth).
- Alert is cross-cutting (bins, pickups, system) so it belongs in the shared app.
"""
from django.conf import settings
from django.db import models


class Profile(models.Model):
    """One-to-one extension of Django's User for ReCircuit users."""

    class Role(models.TextChoices):
        USER = 'user', 'User'
        COLLECTOR = 'collector', 'Collector'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile'
    )
    full_name = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    # --- Day 6: collector role (reuses existing auth, no second login system) ---
    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.USER,
        help_text='USER = normal resident, COLLECTOR = collection team member',
    )
    employee_id = models.CharField(
        max_length=30, blank=True,
        help_text='Collector/employee ID, e.g. COL-001',
    )
    is_collector_active = models.BooleanField(
        default=True,
        help_text='Inactive collectors cannot receive new tasks.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['role']),
        ]

    def __str__(self):
        return f'Profile({self.user.username})'

    @property
    def is_collector(self) -> bool:
        """Active collector account (role + flag)."""
        return self.role == self.Role.COLLECTOR and self.is_collector_active

    @property
    def is_collector_account(self) -> bool:
        """Has collector role regardless of active flag (for admin lists)."""
        return self.role == self.Role.COLLECTOR


def is_collector(user) -> bool:
    """True if user has an active collector profile. Never trusts client input."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    try:
        profile = user.profile
    except Profile.DoesNotExist:
        return False
    return profile.is_collector


def is_ops_staff(user) -> bool:
    """Admin/operations = Django staff (existing architecture, no new auth)."""
    return bool(
        user is not None
        and getattr(user, 'is_authenticated', False)
        and (user.is_staff or user.is_superuser)
    )


def ensure_profile(user):
    """Get-or-create helper so admin-created users always have a profile."""
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


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
