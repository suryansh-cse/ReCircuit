"""Core pages: landing (Day 1) + auth/dashboard/submissions (Day 2) + pickups/bins (Day 3)."""
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render

from bins.models import SmartBin
from core.models import Alert, Profile
from waste.models import EwasteSubmission, PickupRequest

from .forms import EwasteSubmissionForm, PickupRequestForm, ProfileForm, RegisterForm


def landing(request):
    """Public landing page — stats are loaded live via /api/dashboard/stats/."""
    return render(request, 'core/landing.html')


# ---------- Auth ----------

def register_view(request):
    """Create a real User (hashed password) + Profile, then log them in."""
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        profile_form = ProfileForm(request.POST)
        if form.is_valid() and profile_form.is_valid():
            user = form.save()  # password hashed by UserCreationForm
            Profile.objects.create(
                user=user,
                full_name=profile_form.cleaned_data['full_name'].strip(),
                phone=profile_form.cleaned_data['phone'].strip(),
                address=profile_form.cleaned_data['address'].strip(),
                city=profile_form.cleaned_data['city'].strip(),
            )
            login(request, user)
            messages.success(request, f'Welcome to ReCircuit, {user.username}!')
            return redirect('dashboard')
    else:
        form = RegisterForm()
        profile_form = ProfileForm()
    return render(
        request, 'core/register.html', {'form': form, 'profile_form': profile_form}
    )


def login_view(request):
    """Log in with username + password. Honors ?next= for protected pages."""
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            # Ensure a profile exists for users created via admin/createsuperuser.
            Profile.objects.get_or_create(user=user)
            messages.success(request, f'Welcome back, {user.username}!')
            return redirect(request.POST.get('next') or request.GET.get('next') or 'dashboard')
    else:
        form = AuthenticationForm()
    return render(request, 'core/login.html', {'form': form})


def logout_view(request):
    """Log out (GET or POST for student simplicity) and return home."""
    if request.user.is_authenticated:
        logout(request)
        messages.info(request, 'You have been logged out.')
    return redirect('landing')


# ---------- Protected user side ----------

@login_required
def dashboard(request):
    """User dashboard — every number comes from this user's own DB rows."""
    Profile.objects.get_or_create(user=request.user)
    submissions = EwasteSubmission.objects.filter(user=request.user)
    pickups = PickupRequest.objects.filter(user=request.user)

    total_submissions = submissions.count()
    total_weight = submissions.aggregate(total=Sum('estimated_weight'))['total'] or 0.0
    pending_pickups = pickups.filter(status=PickupRequest.Status.PENDING).count()
    active_pickups = pickups.filter(status__in=[
        PickupRequest.Status.ASSIGNED, PickupRequest.Status.IN_TRANSIT,
        PickupRequest.Status.COLLECTED, PickupRequest.Status.PROCESSING,
    ]).count()
    completed_pickups = pickups.filter(status=PickupRequest.Status.RECYCLED).count()
    recycled_items = submissions.filter(status='recycled').count()

    status_breakdown = list(
        submissions.values('status').annotate(count=Count('id')).order_by('status')
    )
    recent_submissions = submissions.order_by('-created_at')[:5]
    recent_pickups = pickups.order_by('-created_at')[:5]
    from .alerts import monitoring_summary

    return render(request, 'core/dashboard.html', {
        'total_submissions': total_submissions,
        'total_weight': round(total_weight, 2),
        'pending_pickups': pending_pickups,
        'active_pickups': active_pickups,
        'completed_pickups': completed_pickups,
        'recycled_items': recycled_items,
        'status_breakdown': status_breakdown,
        'recent_submissions': recent_submissions,
        'recent_pickups': recent_pickups,
        'profile': request.user.profile,
        'monitoring': monitoring_summary(),
    })


@login_required
def submit_ewaste(request):
    """Save a real EwasteSubmission row owned by request.user."""
    if request.method == 'POST':
        form = EwasteSubmissionForm(request.POST)
        if form.is_valid():
            submission = form.save(commit=False)
            submission.user = request.user  # never trust client for ownership
            submission.status = EwasteSubmission.Status.SUBMITTED
            submission.save()
            messages.success(
                request,
                f'E-waste submitted! ID EW-{submission.pk:04d} ({submission.get_category_display()}).',
            )
            return redirect('my-ewaste')
    else:
        form = EwasteSubmissionForm()
    return render(request, 'core/submit.html', {'form': form})


@login_required
def my_ewaste(request):
    """Owner-only list — users can never see another user's rows."""
    submissions = EwasteSubmission.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'core/my_ewaste.html', {'submissions': submissions})


@login_required
def schedule_pickup_placeholder(request):
    """Kept for backward-compat; /pickup/request/ is the real Day 3 route."""
    return redirect('pickup-request')


def find_bins_placeholder(request):
    """Kept for backward-compat; /bins/ is the real Day 3 public page."""
    return redirect('bin-list')


# ---------- Day 3: pickups ----------

# Canonical lifecycle order for the visual tracker (cancelled shown separately).
PICKUP_STAGES = [
    PickupRequest.Status.PENDING,
    PickupRequest.Status.ASSIGNED,
    PickupRequest.Status.IN_TRANSIT,
    PickupRequest.Status.COLLECTED,
    PickupRequest.Status.PROCESSING,
    PickupRequest.Status.RECYCLED,
]


@login_required
def pickup_request_view(request):
    """Create a real PickupRequest owned by request.user, always PENDING."""
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        form = PickupRequestForm(request.POST)
        if form.is_valid():
            pickup = form.save(commit=False)
            pickup.user = request.user  # never trust client for ownership
            pickup.status = PickupRequest.Status.PENDING  # users can't set status
            pickup.save()
            # Day 6: every pickup gets exactly one active CollectionTask
            # (dedupe inside ensure_pickup_task) so ops + collectors share
            # the same workflow as smart-bin alerts.
            try:
                from waste.collections import ensure_pickup_task
                ensure_pickup_task(pickup)
            except Exception:
                pass
            messages.success(
                request,
                f'Pickup requested! ID #{pickup.pk} is now Pending.',
            )
            return redirect('pickup-detail', pk=pickup.pk)
    else:
        form = PickupRequestForm(initial={
            'city': profile.city,
            'pickup_address': profile.address,
        })
    return render(request, 'core/pickup_request.html', {'form': form})


@login_required
def pickup_my(request):
    """Owner-only pickup list, split into active vs cancelled."""
    pickups = PickupRequest.objects.filter(user=request.user).order_by('-created_at')
    active = pickups.exclude(status=PickupRequest.Status.CANCELLED)
    cancelled = pickups.filter(status=PickupRequest.Status.CANCELLED)
    return render(request, 'core/pickup_my.html', {
        'active_pickups': active,
        'cancelled_pickups': cancelled,
    })


@login_required
def pickup_detail(request, pk):
    """Owner-only detail + visual timeline. Other users' IDs → 404."""
    pickup = get_object_or_404(PickupRequest, pk=pk, user=request.user)
    stages = [
        {'value': s.value, 'label': s.label,
         'done': PICKUP_STAGES.index(s) <= PICKUP_STAGES.index(pickup.status)
         if pickup.status in PICKUP_STAGES else False,
         'current': s == pickup.status}
        for s in PICKUP_STAGES
    ]
    # Day 6: show the linked operational task so users see collection progress.
    collection_task = pickup.collection_tasks.order_by('-created_at').first()
    return render(request, 'core/pickup_detail.html', {
        'pickup': pickup, 'stages': stages,
        'collection_task': collection_task,
    })


@login_required
def profile_view(request):
    """View + edit your own profile (Day 2 data, Day 3 page)."""
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        form = ProfileForm(request.POST)
        if form.is_valid():
            profile.full_name = form.cleaned_data['full_name'].strip()
            profile.phone = form.cleaned_data['phone'].strip()
            profile.address = form.cleaned_data['address'].strip()
            profile.city = form.cleaned_data['city'].strip()
            profile.save()
            messages.success(request, 'Profile updated.')
            return redirect('profile')
    else:
        form = ProfileForm(initial={
            'full_name': profile.full_name, 'phone': profile.phone,
            'address': profile.address, 'city': profile.city,
        })
    return render(request, 'core/profile.html', {'form': form, 'profile': profile})


# ---------- Day 3: smart bins (public) ----------

def bin_list(request):
    """Public live monitoring: DB-backed summary + per-bin state + active alerts."""
    from .alerts import monitoring_summary, sweep_offline_alerts
    sweep_offline_alerts()
    bins = SmartBin.objects.all().order_by('bin_id')
    active_alerts = Alert.objects.filter(is_active=True).select_related('bin')
    return render(request, 'core/bin_list.html', {
        'bins': bins,
        'summary': monitoring_summary(),
        'active_alerts': active_alerts,
    })


def bin_detail(request, bin_id):
    """Public bin detail + recent telemetry (empty state if none yet)."""
    from .alerts import sweep_offline_alerts
    sweep_offline_alerts()
    smart_bin = get_object_or_404(SmartBin, bin_id=bin_id)
    recent_telemetry = smart_bin.telemetry.all().order_by('-timestamp')[:10]
    bin_alerts = Alert.objects.filter(bin=smart_bin, is_active=True)
    return render(request, 'core/bin_detail.html', {
        'bin': smart_bin, 'recent_telemetry': recent_telemetry,
        'bin_alerts': bin_alerts,
    })


def alert_list_view(request):
    """Public alerts page: ACTIVE / ALL / RESOLVED filter, grouped by severity."""
    show = request.GET.get('show', 'active')
    if show not in ('active', 'all', 'resolved'):
        show = 'active'
    alerts = Alert.objects.select_related('bin').all().order_by('-created_at')
    if show == 'active':
        alerts = alerts.filter(is_active=True)
    elif show == 'resolved':
        alerts = alerts.filter(is_active=False)
    active = Alert.objects.filter(is_active=True)
    return render(request, 'core/alerts.html', {
        'show': show,
        'alerts': alerts[:100],
        'critical': active.filter(severity=Alert.Severity.CRITICAL).select_related('bin'),
        'warning': active.filter(severity=Alert.Severity.WARNING).select_related('bin'),
        'info': active.filter(severity=Alert.Severity.INFO).select_related('bin'),
    })
