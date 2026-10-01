"""E-waste lifecycle models: submission → pickup → collection → recycling."""
from django.conf import settings
from django.db import models


class EwasteCategory(models.TextChoices):
    SMARTPHONE = 'smartphone', 'Smartphone'
    LAPTOP = 'laptop', 'Laptop'
    TABLET = 'tablet', 'Tablet'
    BATTERY = 'battery', 'Battery'
    CHARGER = 'charger', 'Charger'
    CABLE = 'cable', 'Cable'
    MONITOR = 'monitor', 'Monitor'
    TELEVISION = 'television', 'Television'
    OTHER = 'other', 'Other'


class EwasteSubmission(models.Model):
    """What a user declares they want to recycle."""

    class Condition(models.TextChoices):
        WORKING = 'working', 'Working'
        DAMAGED = 'damaged', 'Damaged'
        NON_FUNCTIONAL = 'non_functional', 'Non-functional'
        UNKNOWN = 'unknown', 'Unknown'

    class Status(models.TextChoices):
        SUBMITTED = 'submitted', 'Submitted'
        COLLECTED = 'collected', 'Collected'
        PROCESSING = 'processing', 'Processing'
        RECYCLED = 'recycled', 'Recycled'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='submissions'
    )
    category = models.CharField(max_length=20, choices=EwasteCategory.choices)
    quantity = models.PositiveIntegerField(default=1)
    estimated_weight = models.FloatField(help_text='Estimated kg')
    condition = models.CharField(max_length=20, choices=Condition.choices)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SUBMITTED
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', '-created_at'])]

    def __str__(self):
        return f'{self.category} x{self.quantity} ({self.user})'


class PickupRequest(models.Model):
    """A user requests doorstep pickup of e-waste."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        ASSIGNED = 'assigned', 'Assigned'
        IN_TRANSIT = 'in_transit', 'In Transit'
        COLLECTED = 'collected', 'Collected'
        PROCESSING = 'processing', 'Processing'
        RECYCLED = 'recycled', 'Recycled'
        CANCELLED = 'cancelled', 'Cancelled'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='pickups'
    )
    pickup_address = models.TextField()
    city = models.CharField(max_length=100)
    e_waste_category = models.CharField(
        max_length=20, choices=EwasteCategory.choices, default=EwasteCategory.OTHER
    )
    estimated_weight = models.FloatField(help_text='Estimated kg')
    preferred_date = models.DateField()
    preferred_time = models.CharField(
        max_length=50, default='Morning (9AM-12PM)',
        help_text='e.g. Morning (9AM-12PM)',
    )
    additional_notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f'Pickup #{self.pk} {self.status} ({self.user})'


class Collection(models.Model):
    """An operational collection event — from a pickup and/or a smart bin."""

    class Status(models.TextChoices):
        ASSIGNED = 'assigned', 'Assigned'
        IN_TRANSIT = 'in_transit', 'In Transit'
        COLLECTED = 'collected', 'Collected'
        PROCESSING = 'processing', 'Processing'
        RECYCLED = 'recycled', 'Recycled'

    pickup = models.ForeignKey(
        PickupRequest, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='collections',
    )
    bin = models.ForeignKey(
        'bins.SmartBin', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='collections',
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ASSIGNED
    )
    collector_name = models.CharField(max_length=100, blank=True)
    collected_weight = models.FloatField(null=True, blank=True, help_text='Actual kg')
    collected_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        src = f'pickup#{self.pickup_id}' if self.pickup_id else f'bin {self.bin_id}'
        return f'Collection {self.pk} ({src}) {self.status}'


class RecyclingRecord(models.Model):
    """Material breakdown after a collection is processed."""

    class ProcessingStatus(models.TextChoices):
        RECEIVED = 'received', 'Received'
        SORTING = 'sorting', 'Sorting'
        DISMANTLING = 'dismantling', 'Dismantling'
        PROCESSING = 'processing', 'Processing'
        COMPLETED = 'completed', 'Completed'

    collection = models.OneToOneField(
        Collection, on_delete=models.CASCADE, related_name='recycling'
    )
    received_weight = models.FloatField(help_text='kg received at facility')
    category = models.CharField(
        max_length=20, choices=EwasteCategory.choices, default=EwasteCategory.OTHER
    )
    processing_status = models.CharField(
        max_length=20, choices=ProcessingStatus.choices,
        default=ProcessingStatus.RECEIVED,
    )
    recyclable_material = models.FloatField(default=0.0)
    reusable_material = models.FloatField(default=0.0)
    hazardous_material = models.FloatField(default=0.0)
    residual_waste = models.FloatField(default=0.0)
    completion_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Recycling for collection #{self.collection_id} ({self.processing_status})'
