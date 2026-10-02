"""Day 7 recycling service — single home for submission lifecycle rules.

Reuse rule: views and APIs never contain transition/analytics logic;
they call these helpers. Mirrors the Day 6 `waste/collections.py` pattern.

Lifecycle (drives the existing EwasteSubmission.status — no duplicate field):
    SUBMITTED -> COLLECTED -> PROCESSING -> RECYCLED
Only forward, one step at a time, staff-only (creation itself is the
user's SUBMITTED step). Each step keeps the RecyclingRecord ledger in sync.
"""
import secrets
from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone


class SubmissionTransitionError(ValueError):
    """Invalid lifecycle change — views/APIs translate this to 400/messages."""


# Linear pipeline order (index comparison enforces forward-only flow).
_LIFECYCLE = ('submitted', 'collected', 'processing', 'recycled')


# ---------- Deposit sessions (QR flow) ----------

def start_deposit_session(user, smart_bin):
    """Create a 5-minute single-use session for this user + bin."""
    from waste.models import DepositSession
    ttl = timedelta(minutes=DepositSession.SESSION_TTL_MINUTES)
    return DepositSession.objects.create(
        token=secrets.token_urlsafe(32),
        user=user,
        smart_bin=smart_bin,
        expires_at=timezone.now() + ttl,
    )


def get_valid_session(user, token):
    """Return the session iff it is usable by this user — else None.

    Never trusts the token alone: must belong to the user, be unexpired,
    uncompleted, and unused. Expired sessions can never verify (spec test 7).
    """
    if not token:
        return None
    from waste.models import DepositSession
    try:
        session = DepositSession.objects.select_related('smart_bin').get(
            token=token, user=user)
    except DepositSession.DoesNotExist:
        return None
    return session if session.is_valid() else None


# ---------- Recycling ledger ----------

def ensure_recycling_record(submission, collection_task=None):
    """Idempotent ledger row for a submission (one active row per submission)."""
    from waste.models import RecyclingRecord
    record = RecyclingRecord.objects.filter(
        submission=submission,
        processing_status__in=(
            RecyclingRecord.ProcessingStatus.AWAITING_PROCESSING,
            RecyclingRecord.ProcessingStatus.PROCESSING,
        ),
    ).order_by('-created_at').first()
    if record is not None:
        if (collection_task is not None
                and record.collection_task_id is None):
            record.collection_task = collection_task
            record.save(update_fields=['collection_task'])
        return record, False
    return RecyclingRecord.objects.create(
        submission=submission,
        collection_task=collection_task,
        category=submission.category,
        received_weight=submission.actual_weight or submission.estimated_weight,
        processing_status=RecyclingRecord.ProcessingStatus.AWAITING_PROCESSING,
    ), True


def advance_submission(submission, to_status, *, by_user=None,
                       actual_weight=None, partner='', notes=''):
    """Move a submission one step forward. Staff-only, forward-only.

    to_status: 'collected' | 'processing' | 'recycled'.
    - COLLECTED: opens the AWAITING_PROCESSING ledger row.
    - PROCESSING: ledger -> PROCESSING (+processed_at).
    - RECYCLED: ledger -> RECYCLED (+recycled_at, weights, partner, notes).
    """
    from core.models import is_ops_staff

    from waste.models import EwasteSubmission, RecyclingRecord
    if by_user is not None and not is_ops_staff(by_user):
        raise SubmissionTransitionError('Staff permission required.')
    if to_status not in _LIFECYCLE:
        raise SubmissionTransitionError(f'Unknown status {to_status!r}.')
    try:
        cur_idx = _LIFECYCLE.index(submission.status)
        new_idx = _LIFECYCLE.index(to_status)
    except ValueError:
        raise SubmissionTransitionError(
            f'Cannot move submission from {submission.status!r}.')
    if new_idx != cur_idx + 1:
        raise SubmissionTransitionError(
            f'Cannot move submission from {submission.get_status_display()} '
            f'to {dict(EwasteSubmission.Status.choices).get(to_status, to_status)} — '
            'move one step forward at a time.')
    now = timezone.now()
    if to_status == 'collected':
        submission.status = EwasteSubmission.Status.COLLECTED
        submission.save(update_fields=['status', 'updated_at'])
        ensure_recycling_record(submission)
        return submission
    record, _ = ensure_recycling_record(submission)
    if to_status == 'processing':
        submission.status = EwasteSubmission.Status.PROCESSING
        submission.save(update_fields=['status', 'updated_at'])
        record.processing_status = RecyclingRecord.ProcessingStatus.PROCESSING
        record.processed_at = now
        if notes:
            record.notes = (record.notes + '\n' + notes).strip() if record.notes else notes
        record.save(update_fields=['processing_status', 'processed_at', 'notes'])
        return submission
    # recycled — terminal step, captures verified outputs.
    if actual_weight is not None and actual_weight <= 0:
        raise SubmissionTransitionError('Recycled weight must be positive.')
    submission.status = EwasteSubmission.Status.RECYCLED
    if actual_weight is not None:
        submission.actual_weight = actual_weight
    submission.save(update_fields=['status', 'actual_weight', 'updated_at'])
    record.processing_status = RecyclingRecord.ProcessingStatus.RECYCLED
    record.recycled_at = now
    if actual_weight is not None:
        record.received_weight = actual_weight
    if partner:
        record.recycling_partner = partner
    if notes:
        record.notes = (record.notes + '\n' + notes).strip() if record.notes else notes
    record.save(update_fields=['processing_status', 'recycled_at',
                               'received_weight', 'recycling_partner', 'notes'])
    return submission


def advance_pickup_submissions(task):
    """Day 6 integration: completing a pickup task collects its submissions.

    Called (failure-safe) from collections.complete_task. Only touches
    SUBMITTED rows linked to this task's pickup — nothing else moves.
    Returns the number of submissions advanced.
    """
    from waste.models import EwasteSubmission
    if task.pickup_request_id is None:
        return 0
    moved = 0
    subs = EwasteSubmission.objects.filter(
        pickup_request_id=task.pickup_request_id,
        status=EwasteSubmission.Status.SUBMITTED,
    )
    for sub in subs:
        try:
            advance_submission(sub, 'collected')
            moved += 1
        except SubmissionTransitionError:
            continue
    return moved


# ---------- Analytics (DB-driven, no hardcoding) ----------

def _weight_for(submissions):
    """Prefer verified actual_weight, fall back to estimates."""
    from django.db.models import Case, F, FloatField, When
    return submissions.aggregate(total=Sum(
        Case(When(actual_weight__isnull=False, then=F('actual_weight')),
             default=F('estimated_weight'), output_field=FloatField())
    ))['total'] or 0.0


def recycling_summary():
    """Aggregate numbers for the recycling dashboard, APIs and analytics.

    All values come from the database; empty DB -> zeros (never fake data).
    Keys: total_submissions, total_weight, by_status {status: {count, weight}},
    by_category [{category, label, count, weight}], today/week/month counts,
    qr_verified, pending_verification.
    """
    from waste.models import EwasteCategory, EwasteSubmission
    subs = EwasteSubmission.objects.all()
    by_status = {}
    for value, _label in EwasteSubmission.Status.choices:
        qs = subs.filter(status=value)
        by_status[value] = {'count': qs.count(), 'weight': round(_weight_for(qs), 2)}
    by_category = []
    for value, label in EwasteCategory.choices:
        qs = subs.filter(category=value)
        by_category.append({
            'category': value, 'label': label,
            'count': qs.count(), 'weight': round(_weight_for(qs), 2),
        })
    now = timezone.now()
    start_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_week = start_day - timedelta(days=start_day.weekday())
    start_month = start_day.replace(day=1)
    return {
        'total_submissions': subs.count(),
        'total_weight': round(_weight_for(subs), 2),
        'by_status': by_status,
        'by_category': by_category,
        'today': subs.filter(created_at__gte=start_day).count(),
        'this_week': subs.filter(created_at__gte=start_week).count(),
        'this_month': subs.filter(created_at__gte=start_month).count(),
        'qr_verified': subs.filter(
            verification_status=EwasteSubmission.VerificationStatus.QR_VERIFIED
        ).count(),
        'pending_verification': subs.filter(
            verification_status=EwasteSubmission.VerificationStatus.PENDING
        ).count(),
        'smart_bin_method': subs.filter(
            submission_method=EwasteSubmission.SubmissionMethod.SMART_BIN
        ).count(),
        'pickup_method': subs.filter(
            submission_method=EwasteSubmission.SubmissionMethod.PICKUP
        ).count(),
    }


def submission_payload(sub):
    """Manual serializer — explicit fields, owner-safe (no PII beyond username)."""
    return {
        'id': sub.pk,
        'display_id': sub.display_id,
        'user': sub.user.username if sub.user_id else None,
        'category': sub.category,
        'category_display': sub.get_category_display(),
        'quantity': sub.quantity,
        'estimated_weight': sub.estimated_weight,
        'actual_weight': sub.actual_weight,
        'condition': sub.condition,
        'condition_display': sub.get_condition_display(),
        'description': sub.description,
        'submission_method': sub.submission_method,
        'submission_method_display': sub.get_submission_method_display(),
        'bin_id': sub.smart_bin.bin_id if sub.smart_bin else None,
        'bin_location': sub.smart_bin.location if sub.smart_bin else None,
        'pickup_id': sub.pickup_request_id,
        'verification_status': sub.verification_status,
        'verification_display': sub.get_verification_status_display(),
        'status': sub.status,
        'status_display': sub.get_status_display(),
        'submitted_at': sub.created_at.isoformat(),
        'updated_at': sub.updated_at.isoformat(),
    }
