"""Smart bin + telemetry models.

Data flow (Day 4 adds the POST endpoint):
    ESP32 → POST /api/telemetry/ → Telemetry row → SmartBin latest state updated.

- SmartBin holds the *current* state (fast dashboard reads).
- Telemetry holds the *history* (charts, analytics).
- `data_source` distinguishes REAL hardware from SIMULATED data (never mix them).

Demo values in SmartBin are placeholders until ESP32 telemetry arrives —
the UI must label SIMULATED bins as such.
"""
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class DataSource(models.TextChoices):
    REAL = 'real', 'Real Device'
    SIMULATED = 'simulated', 'Simulated'


# ---------- Reusable helpers (single source of truth — do not duplicate) ----------

def fill_status_for(value: float) -> str:
    """Fill status rule: 0-59 Normal, 60-79 Warning, 80-100 Collection Required."""
    warning_at = getattr(settings, 'RECIRCUIT_FILL_WARNING_AT', 60.0)
    critical_at = getattr(settings, 'RECIRCUIT_FILL_CRITICAL_AT', 80.0)
    if value >= critical_at:
        return 'Collection Required'
    if value >= warning_at:
        return 'Warning'
    return 'Normal'


def fill_status_code_for(value: float) -> str:
    """CSS-friendly code for fill_status_for: normal | warning | critical."""
    return {
        'Normal': 'normal',
        'Warning': 'warning',
        'Collection Required': 'critical',
    }[fill_status_for(value)]


def is_online_for(last_seen, now=None) -> bool:
    """A bin is ONLINE if last_seen is within the configured threshold."""
    if last_seen is None:
        return False
    now = now or timezone.now()
    threshold = timedelta(
        minutes=getattr(settings, 'RECIRCUIT_OFFLINE_AFTER_MINUTES', 15)
    )
    return last_seen >= now - threshold


def refresh_online_flags() -> int:
    """Mark stale bins OFFLINE in one query. Returns rows updated.

    Called lazily from bin GET views/APIs so the dashboard never shows a
    silent bin as online. ESP32 POSTs set is_online=True via mark_seen().
    """
    cutoff = timezone.now() - timedelta(
        minutes=getattr(settings, 'RECIRCUIT_OFFLINE_AFTER_MINUTES', 15)
    )
    return SmartBin.objects.filter(is_online=True).exclude(
        last_seen__gte=cutoff
    ).update(is_online=False)


class SmartBin(models.Model):
    """A physical (or simulated) e-waste collection bin."""

    bin_id = models.CharField(
        max_length=30, unique=True,
        help_text="Unique device ID, e.g. ECO-BIN-001 (matches ESP32 device_id)",
    )
    name = models.CharField(max_length=100)
    location = models.CharField(max_length=255)
    city = models.CharField(max_length=100, blank=True, default='')
    latitude = models.FloatField()
    longitude = models.FloatField()

    # Latest known state (updated on every telemetry POST from Day 4)
    fill_level = models.FloatField(default=0.0, help_text='Fill % 0-100')
    weight = models.FloatField(default=0.0, help_text='Kilograms')
    temperature = models.FloatField(null=True, blank=True, help_text='°C')

    is_online = models.BooleanField(default=True)
    data_source = models.CharField(
        max_length=10, choices=DataSource.choices, default=DataSource.SIMULATED,
        help_text='REAL = ESP32 hardware, SIMULATED = demo generator',
    )
    last_seen = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['bin_id']
        indexes = [
            models.Index(fields=['bin_id']),
            models.Index(fields=['is_online']),
        ]

    def __str__(self):
        return f'{self.bin_id} — {self.name}'

    @property
    def status(self) -> str:
        """Human-readable fill status (uses the shared helper)."""
        return fill_status_for(self.fill_level)

    @property
    def status_code(self) -> str:
        """CSS-friendly status: normal | warning | critical."""
        return fill_status_code_for(self.fill_level)

    @property
    def computed_online(self) -> bool:
        """Live online check from last_seen (does not hit the DB)."""
        return is_online_for(self.last_seen)

    def mark_seen(self, *, fill, weight, temperature, data_source):
        """Update latest state from a telemetry payload (Day 4 caller)."""
        self.fill_level = fill
        self.weight = weight
        self.temperature = temperature
        self.is_online = True
        self.last_seen = timezone.now()
        # Once a real device reports, promote the bin to REAL.
        if data_source == DataSource.REAL:
            self.data_source = DataSource.REAL
        self.save(update_fields=[
            'fill_level', 'weight', 'temperature',
            'is_online', 'last_seen', 'data_source', 'updated_at',
        ])


class Telemetry(models.Model):
    """One sensor reading from a bin (history for charts)."""

    smart_bin = models.ForeignKey(
        SmartBin, on_delete=models.CASCADE, related_name='telemetry'
    )
    fill_level = models.FloatField(help_text='Fill % 0-100')
    weight = models.FloatField(help_text='Kilograms')
    temperature = models.FloatField(null=True, blank=True, help_text='°C')
    data_source = models.CharField(
        max_length=10, choices=DataSource.choices, default=DataSource.SIMULATED,
        help_text='REAL = ESP32 hardware, SIMULATED = demo generator',
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['smart_bin', '-timestamp']),
        ]

    def __str__(self):
        src = 'SIM' if self.data_source == DataSource.SIMULATED else 'REAL'
        return f'{self.smart_bin.bin_id} {self.fill_level}% [{src}] @ {self.timestamp:%Y-%m-%d %H:%M}'

    @property
    def is_simulated(self) -> bool:
        """Back-compat helper for templates (prefer data_source)."""
        return self.data_source == DataSource.SIMULATED
