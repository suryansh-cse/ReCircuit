"""Day 7 traceability views — campus map, QR deposit flow, recycling ops.

Auth model (backend-enforced):
- Map: public (bin locations are public infrastructure, same as /bins/).
- Deposit: login required; sessions bind to request.user.
- Recycling dashboard + advance actions: staff only.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from bins.models import SmartBin
from core.models import is_ops_staff
from waste.models import EwasteSubmission
from waste.recycling import (
    SubmissionTransitionError,
    advance_submission,
    recycling_summary,
    start_deposit_session,
)


def _require_staff(request):
    if not is_ops_staff(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('Staff permission required.')
    return None


# ---------- Campus map ----------

def bin_map(request):
    """Public Leaflet/OpenStreetMap campus map — markers from live DB state.

    Uses existing SmartBin lat/lng + shared status logic (no duplication).
    Browser geolocation is optional and client-side only (never stored).
    """
    from core.alerts import sweep_offline_alerts
    sweep_offline_alerts()
    bins = SmartBin.objects.order_by('bin_id')
    return render(request, 'core/bin_map.html', {'bins': bins})


# ---------- QR deposit flow ----------

@login_required
def bin_deposit(request, bin_id):
    """QR landing: the bin's static QR encodes this URL (printable sticker).

    GET shows bin info + [Start deposit] (POST creates a 5-minute session
    bound to request.user, then redirects to /submit/ with the token).
    QR proves association with THIS bin through the QR flow — not physical
    deposit (documented on the page, no false claims).
    """
    smart_bin = get_object_or_404(SmartBin, bin_id=bin_id)
    if request.method == 'POST':
        session = start_deposit_session(request.user, smart_bin)
        messages.info(
            request,
            f'Deposit session {session.display_id} started for '
            f'{smart_bin.bin_id} — expires in 5 minutes.')
        return redirect(f'/submit/?bin={smart_bin.bin_id}&session={session.token}')
    return render(request, 'core/bin_deposit.html', {'bin': smart_bin})


# ---------- Recycling operations (staff) ----------

@login_required
def recycling_dashboard(request):
    """Staff recycling pipeline: DB-driven stats + advance actions."""
    denied = _require_staff(request)
    if denied is not None:
        return denied
    status_f = request.GET.get('status', '')
    submissions = EwasteSubmission.objects.select_related(
        'user', 'smart_bin', 'pickup_request').order_by('-created_at')
    if status_f in dict(EwasteSubmission.Status.choices):
        submissions = submissions.filter(status=status_f)
    return render(request, 'core/recycling.html', {
        'summary': recycling_summary(),
        'submissions': submissions[:100],
        'status_f': status_f,
        'status_choices': EwasteSubmission.Status.choices,
        'next_step': {'submitted': 'collected', 'collected': 'processing',
                      'processing': 'recycled'},
    })


@login_required
@require_POST
def submission_advance(request, pk):
    """Staff moves a submission one lifecycle step forward."""
    denied = _require_staff(request)
    if denied is not None:
        return denied
    submission = get_object_or_404(EwasteSubmission, pk=pk)
    action = request.POST.get('action', '').strip()
    if action not in ('collected', 'processing', 'recycled'):
        messages.error(request, 'Unknown action.')
        return redirect('recycling-dash')
    try:
        weight_raw = (request.POST.get('actual_weight') or '').strip()
        advance_submission(
            submission, action, by_user=request.user,
            actual_weight=float(weight_raw) if weight_raw else None,
            partner=request.POST.get('partner', '').strip(),
            notes=request.POST.get('notes', '').strip(),
        )
    except (SubmissionTransitionError, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect('recycling-dash')
    messages.success(
        request,
        f'Submission {submission.display_id} → '
        f'{submission.get_status_display()}.')
    return redirect('recycling-dash')
