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
    """What a user declares they want to recycle.

    Day 7 traceability: every row knows WHO (user, server-set), WHAT
    (category/quantity), HOW MUCH (estimated + actual weight), WHICH BIN
    (smart_bin, for SMART_BIN method) or WHICH PICKUP (pickup_request),
    WHEN (created_at == submitted_at), HOW verified (verification_status),
    and WHERE in the lifecycle (status SUBMITTED → COLLECTED → PROCESSING
    → RECYCLED — the same choices as Days 2-3, no duplicate field).
    """

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

    class SubmissionMethod(models.TextChoices):
        SMART_BIN = 'smart_bin', 'Smart Bin'
        PICKUP = 'pickup', 'Pickup'

    class VerificationStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        QR_VERIFIED = 'qr_verified', 'QR Verified'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='submissions'
    )
    category = models.CharField(max_length=20, choices=EwasteCategory.choices)
    quantity = models.PositiveIntegerField(default=1)
    estimated_weight = models.FloatField(help_text='Estimated kg')
    # Verified/final weight recorded during collection/recycling (nullable:
    # unknown until physically handled — never fabricated).
    actual_weight = models.FloatField(
        null=True, blank=True, help_text='Verified kg (set by operations)')
    condition = models.CharField(max_length=20, choices=Condition.choices)
    description = models.TextField(blank=True)
    # --- Day 7 traceability (all nullable/additive — old rows stay valid) ---
    submission_method = models.CharField(
        max_length=10, choices=SubmissionMethod.choices,
        default=SubmissionMethod.PICKUP,
        help_text='SMART_BIN = deposited at a bin, PICKUP = doorstep collection',
    )
    smart_bin = models.ForeignKey(
        'bins.SmartBin', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='submissions',
        help_text='Bin used for SMART_BIN submissions (null for PICKUP).',
    )
    pickup_request = models.ForeignKey(
        'waste.PickupRequest', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='submissions',
        help_text='Pickup this submission rides along with, if any.',
    )
    deposit_session = models.ForeignKey(
        'waste.DepositSession', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='submissions',
        help_text='QR deposit session this submission was created from, if any.',
    )
    verification_status = models.CharField(
        max_length=15, choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
        help_text='QR_VERIFIED only via a valid QR deposit session.',
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SUBMITTED
    )
    created_at = models.DateTimeField(auto_now_add=True)  # == submitted_at
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['status']),
            models.Index(fields=['verification_status']),
        ]

    def __str__(self):
        return f'{self.category} x{self.quantity} ({self.user})'

    @property
    def submitted_at(self):
        """Alias — spec name for the submission timestamp."""
        return self.created_at

    @property
    def display_id(self):
        return f'EW-{self.pk:04d}'

    def clean(self):
        from django.core.exceptions import ValidationError
        if (self.submission_method == self.SubmissionMethod.SMART_BIN
                and self.smart_bin_id is None):
            raise ValidationError(
                'SMART_BIN submissions must reference a SmartBin.')


class DepositSession(models.Model):
    """Day 7 lightweight QR deposit session (anti-spoofing for bin claims).

    Flow: user scans a bin's static QR (the deposit URL) → an active
    session is created (5-minute expiry) → the e-waste form consumes the
    session token → submission is marked QR_VERIFIED and the session is
    completed (single-use). Expired/completed sessions can never verify.

    QR verification proves the submission was associated with that
    specific bin through the QR flow — it does NOT prove physical deposit
    (that needs weight-sensor confirmation, out of scope for Day 7).
    """

    SESSION_TTL_MINUTES = 5

    token = models.CharField(
        max_length=64, unique=True,
        help_text='Secret single-use token embedded in the submit step.',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='deposit_sessions',
    )
    smart_bin = models.ForeignKey(
        'bins.SmartBin', on_delete=models.CASCADE,
        related_name='deposit_sessions',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_completed = models.BooleanField(default=False)
    submission = models.OneToOneField(
        EwasteSubmission, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='used_session',
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['token']),
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f'DS-{self.pk} {self.smart_bin.bin_id} ({self.user})'

    @property
    def display_id(self):
        return f'DS-{self.pk:05d}'

    def is_expired(self, now=None):
        from django.utils import timezone
        return (now or timezone.now()) >= self.expires_at

    def is_valid(self, now=None):
        """Usable for verification: unused, unexpired, no submission yet."""
        return (not self.is_completed
                and self.submission_id is None
                and not self.is_expired(now))

    def mark_used(self, submission):
        self.submission = submission
        self.is_completed = True
        self.save(update_fields=['submission', 'is_completed'])


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
    city = models.CharField(max_length=100, default='')
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

    @property
    def display_id(self):
        """Friendly ops ID, e.g. PR-1042 (code-only, no migration)."""
        return f'PR-{self.pk:04d}' if self.pk else 'PR-…'


class CollectionTask(models.Model):
    """Day 6 operational task — one row per real collection job.

    A task originates from EITHER a smart-bin fill alert OR a user
    pickup request (both nullable, never both mandatory). Admin assigns a
    collector; the collector moves ASSIGNED -> IN_TRANSIT -> COLLECTED.
    PENDING = created but unassigned. CANCELLED = terminal, allows retry.
    """

    class Priority(models.TextChoices):
        NORMAL = 'normal', 'Normal'
        HIGH = 'high', 'High'
        CRITICAL = 'critical', 'Critical'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        ASSIGNED = 'assigned', 'Assigned'
        IN_TRANSIT = 'in_transit', 'In Transit'
        COLLECTED = 'collected', 'Collected'
        CANCELLED = 'cancelled', 'Cancelled'

    #: Statuses that block a duplicate task for the same source.
    ACTIVE_STATUSES = (
        Status.PENDING, Status.ASSIGNED, Status.IN_TRANSIT,
    )
    TERMINAL_STATUSES = (Status.COLLECTED, Status.CANCELLED)

    smart_bin = models.ForeignKey(
        'bins.SmartBin', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='collection_tasks',
        help_text='Set when the task came from a smart-bin fill alert.',
    )
    pickup_request = models.ForeignKey(
        PickupRequest, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='collection_tasks',
        help_text='Set when the task came from a user pickup request.',
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='collection_tasks',
        help_text='Collector user (must have collector role).',
    )
    created_from_alert = models.ForeignKey(
        'core.Alert', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='collection_tasks',
        help_text='Fill alert that triggered this task, if any.',
    )
    priority = models.CharField(
        max_length=10, choices=Priority.choices, default=Priority.NORMAL,
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING,
    )
    notes = models.TextField(blank=True)
    # Snapshot at creation for history (sensor state may change later).
    fill_level_at_creation = models.FloatField(null=True, blank=True)
    weight_at_creation = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    assigned_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['priority']),
            models.Index(fields=['assigned_to', 'status']),
            models.Index(fields=['smart_bin', 'status']),
            models.Index(fields=['pickup_request', 'status']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        if self.smart_bin_id:
            src = f'bin {self.smart_bin.bin_id}' if hasattr(self.smart_bin, 'bin_id') else f'bin#{self.smart_bin_id}'
        elif self.pickup_request_id:
            src = f'pickup#{self.pickup_request_id}'
        else:
            src = 'manual'
        who = f' -> {self.assigned_to}' if self.assigned_to_id else ''
        return f'Task #{self.pk} ({src}) {self.status}{who}'

    @property
    def is_active(self) -> bool:
        return self.status in (
            self.Status.PENDING, self.Status.ASSIGNED, self.Status.IN_TRANSIT,
        )

    @property
    def display_id(self):
        """Friendly ops ID, e.g. CT-1042 (code-only, no migration)."""
        return f'CT-{self.pk:04d}' if self.pk else 'CT-…'

    @property
    def type_label(self):
        """Collector-friendly job type (no jargon)."""
        if self.smart_bin_id:
            return 'Smart Bin Collection'
        if self.pickup_request_id:
            return 'User Pickup'
        return 'Collection'

    @property
    def source_label(self) -> str:
        if self.smart_bin_id:
            return 'Smart Bin Alert'
        if self.pickup_request_id:
            return 'User Pickup'
        return 'Manual'

    def clean(self):
        from django.core.exceptions import ValidationError
        if not self.smart_bin_id and not self.pickup_request_id:
            raise ValidationError(
                'A task needs either a smart_bin or a pickup_request.'
            )


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
    """Material breakdown after a collection is processed.

    Day 7: also the per-submission recycling ledger. New nullable links
    (submission / collection_task) keep the legacy `collection` rows valid;
    new Day-7 statuses are additive to the existing choices.
    """

    class ProcessingStatus(models.TextChoices):
        RECEIVED = 'received', 'Received'
        SORTING = 'sorting', 'Sorting'
        DISMANTLING = 'dismantling', 'Dismantling'
        PROCESSING = 'processing', 'Processing'
        COMPLETED = 'completed', 'Completed'
        # --- Day 7 MVP pipeline (submission-level) ---
        AWAITING_PROCESSING = 'awaiting_processing', 'Awaiting Processing'
        RECYCLED = 'recycled', 'Recycled'

    collection = models.OneToOneField(
        Collection, null=True, blank=True, on_delete=models.CASCADE,
        related_name='recycling',
    )
    # --- Day 7 links (nullable — legacy rows have neither) ---
    submission = models.ForeignKey(
        EwasteSubmission, null=True, blank=True,
        on_delete=models.CASCADE, related_name='recycling_records',
        help_text='Submission being recycled (Day 7 pipeline).',
    )
    collection_task = models.ForeignKey(
        CollectionTask, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='recycling_records',
        help_text='Collection task that brought the material in, if any.',
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
    # --- Day 7 MVP operations fields ---
    recycling_partner = models.CharField(
        max_length=120, blank=True, default='',
        help_text='Internal facility/team handling recycling (no external claims).',
    )
    notes = models.TextField(blank=True, default='')
    processed_at = models.DateTimeField(null=True, blank=True)
    recycled_at = models.DateTimeField(null=True, blank=True)
    completion_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['processing_status']),
            models.Index(fields=['submission', '-created_at']),
        ]

    def __str__(self):
        if self.submission_id:
            return f'Recycling for submission #{self.submission_id} ({self.processing_status})'
        return f'Recycling for collection #{self.collection_id} ({self.processing_status})'
