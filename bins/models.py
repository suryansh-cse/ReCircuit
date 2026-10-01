"""Smart bin + telemetry models.

Data flow:
    ESP32 → POST /api/telemetry/ → Telemetry row → SmartBin latest state updated.

- SmartBin holds the *current* state (fast dashboard reads).
- Telemetry holds the *history* (charts, analytics).
- `data_source` distinguishes REAL hardware from SIMULATED data (never mix them).
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class DataSource(models.TextChoices):
    REAL = 'real', 'Real Device'
    SIMULATED = 'simulated', 'Simulated'


class SmartBin(models.Model):
    """A physical (or simulated) e-waste collection bin."""

    bin_id = models.CharField(
        max_length=30, unique=True,
        help_text="Unique device ID, e.g. ECO-BIN-001 (matches ESP32 device_id)",
    )
    name = models.CharField(max_length=100)
    location = models.CharField(max_length=255)
    latitude = models.FloatField()
    longitude = models.FloatField()

    # Latest known state (updated on every telemetry POST)
    fill_percentage = models.FloatField(default=0.0)
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
        """Fill-based status rule from the spec."""
        warning_at = getattr(settings, 'RECIRCUIT_FILL_WARNING_AT', 60.0)
        critical_at = getattr(settings, 'RECIRCUIT_FILL_CRITICAL_AT', 80.0)
        if self.fill_percentage >= critical_at:
            return 'Collection Required'
        if self.fill_percentage >= warning_at:
            return 'Warning'
        return 'Normal'

    def mark_seen(self, *, fill, weight, temperature, data_source):
        """Update latest state from a telemetry payload."""
        self.fill_percentage = fill
        self.weight = weight
        self.temperature = temperature
        self.is_online = True
        self.last_seen = timezone.now()
        # Once a real device reports, promote the bin to REAL.
        if data_source == DataSource.REAL:
            self.data_source = DataSource.REAL
        self.save(update_fields=[
            'fill_percentage', 'weight', 'temperature',
            'is_online', 'last_seen', 'data_source', 'updated_at',
        ])


class Telemetry(models.Model):
    """One sensor reading from a bin (history for charts)."""

    bin = models.ForeignKey(
        SmartBin, on_delete=models.CASCADE, related_name='telemetry'
    )
    fill_level = models.FloatField(help_text='Fill % 0-100')
    weight = models.FloatField(help_text='Kilograms')
    temperature = models.FloatField(null=True, blank=True, help_text='°C')
    is_simulated = models.BooleanField(
        default=True,
        help_text='True = demo generator, False = real ESP32 hardware',
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-recorded_at']
        indexes = [
            models.Index(fields=['bin', '-recorded_at']),
        ]

    def __str__(self):
        src = 'SIM' if self.is_simulated else 'REAL'
        return f'{self.bin.bin_id} {self.fill_level}% [{src}] @ {self.recorded_at:%Y-%m-%d %H:%M}'
