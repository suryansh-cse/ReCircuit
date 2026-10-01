"""Core pages: landing (Day 1) + auth/dashboard/submissions (Day 2)."""
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Count, Sum
from django.shortcuts import redirect, render

from core.models import Profile
from waste.models import EwasteSubmission, PickupRequest

from .forms import EwasteSubmissionForm, ProfileForm, RegisterForm


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
    pending_pickups = pickups.filter(status='pending').count()
    recycled_items = submissions.filter(status='recycled').count()

    status_breakdown = list(
        submissions.values('status').annotate(count=Count('id')).order_by('status')
    )
    recent_submissions = submissions.order_by('-created_at')[:5]
    recent_pickups = pickups.order_by('-created_at')[:5]

    return render(request, 'core/dashboard.html', {
        'total_submissions': total_submissions,
        'total_weight': round(total_weight, 2),
        'pending_pickups': pending_pickups,
        'recycled_items': recycled_items,
        'status_breakdown': status_breakdown,
        'recent_submissions': recent_submissions,
        'recent_pickups': recent_pickups,
        'profile': request.user.profile,
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
    """Real route so dashboard buttons work; full pickup system lands Day 3."""
    return render(request, 'core/placeholder.html', {
        'title': 'Schedule Pickup',
        'message': 'Doorstep pickup requests open on Day 3. Your submissions above are already saved and will be linkable to a pickup then.',
    })


@login_required
def find_bins_placeholder(request):
    """Real route so dashboard buttons work; smart-bin map lands Day 4/7."""
    return render(request, 'core/placeholder.html', {
        'title': 'Find Smart Bins',
        'message': 'The live smart-bin map opens on Day 4. Your dashboard stats already reflect real bin data via /api/dashboard/stats/.',
    })
