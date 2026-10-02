"""Day 6 tests: CollectionTask lifecycle, dedupe, auth, transitions.

Run: python manage.py test waste core
Covers spec Step 14 (1-14) incl. duplicate-alert scenario.
"""
import datetime
import json

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from bins.models import SmartBin
from core.models import Alert, Profile
from waste.collections import (
    TaskTransitionError,
    assign_task,
    cancel_task,
    complete_task,
    ensure_bin_task,
    ensure_pickup_task,
    priority_for_fill,
    start_task,
)
from waste.models import CollectionTask, PickupRequest


def make_bin(bin_id='ECO-TASK-1', fill=10.0):
    return SmartBin.objects.create(
        bin_id=bin_id, name='Task Bin', location='Block C', city='Test',
        latitude=0, longitude=0, fill_level=fill, weight=5.0,
        temperature=29.0, is_online=True, last_seen=timezone.now(),
    )


def make_user(name, password='pass12345', staff=False):
    u = User.objects.create_user(name, f'{name}@t.com', password)
    if staff:
        u.is_staff = True
        u.save()
    Profile.objects.get_or_create(user=u)
    return u


def make_collector(name, active=True):
    u = make_user(name)
    p = u.profile
    p.role = Profile.Role.COLLECTOR
    p.employee_id = f'EMP-{name.upper()}'
    p.is_collector_active = active
    p.save()
    return u


def make_pickup(user):
    return PickupRequest.objects.create(
        user=user, pickup_address='Hostel C', city='Test',
        e_waste_category='laptop', estimated_weight=5.0,
        preferred_date=datetime.date.today() + datetime.timedelta(days=1),
    )


def post_telemetry(bin_id, fill, weight=10.0, temp=29.0):
    c = Client()
    return c.post('/api/telemetry/', data=json.dumps({
        'device_id': bin_id, 'fill_level': fill,
        'weight': weight, 'temperature': temp,
    }), content_type='application/json')


class PriorityTests(TestCase):
    def test_priority_bands(self):
        self.assertEqual(priority_for_fill(85), 'high')
        self.assertEqual(priority_for_fill(95), 'critical')
        self.assertEqual(priority_for_fill(90), 'critical')
        self.assertEqual(priority_for_fill(50), 'normal')


class AlertToTaskTests(TestCase):
    def setUp(self):
        self.bin = make_bin()

    def test_1_task_created_on_fill_alert(self):
        r = post_telemetry(self.bin.bin_id, 87)
        self.assertEqual(r.status_code, 201)
        tasks = CollectionTask.objects.filter(smart_bin=self.bin)
        self.assertEqual(tasks.count(), 1)
        self.assertEqual(tasks.first().priority, 'high')
        self.assertEqual(tasks.first().status, 'pending')

    def test_2_critical_priority_at_90(self):
        post_telemetry(self.bin.bin_id, 93)
        task = CollectionTask.objects.get(smart_bin=self.bin)
        self.assertEqual(task.priority, 'critical')

    def test_3_no_duplicate_tasks(self):
        # 87% -> 90% -> 95%: still exactly ONE active task.
        post_telemetry(self.bin.bin_id, 87)
        post_telemetry(self.bin.bin_id, 90)
        post_telemetry(self.bin.bin_id, 95)
        self.assertEqual(
            CollectionTask.objects.filter(
                smart_bin=self.bin,
                status__in=CollectionTask.ACTIVE_STATUSES).count(), 1)
        self.assertEqual(CollectionTask.objects.filter(smart_bin=self.bin).count(), 1)

    def test_4_new_task_after_completion(self):
        post_telemetry(self.bin.bin_id, 87)
        task = CollectionTask.objects.get(smart_bin=self.bin)
        col = make_collector('cola')
        assign_task(task, col)
        start_task(task)
        complete_task(task)
        # Bin fills again later -> new task allowed.
        task2, created = ensure_bin_task(self.bin)
        # complete resolved the alert; re-raise via telemetry path
        post_telemetry(self.bin.bin_id, 88)
        self.assertEqual(
            CollectionTask.objects.filter(smart_bin=self.bin).count(), 2)

    def test_below_threshold_no_task(self):
        task, created = ensure_bin_task(self.bin)
        self.assertIsNone(task)
        self.assertFalse(created)


class PickupWorkflowTests(TestCase):
    def test_pickup_creates_task_and_syncs(self):
        user = make_user('resident1')
        pickup = make_pickup(user)
        task, created = ensure_pickup_task(pickup)
        self.assertTrue(created)
        self.assertEqual(task.priority, 'normal')
        # Duplicate prevention
        task2, created2 = ensure_pickup_task(pickup)
        self.assertFalse(created2)
        self.assertEqual(task.pk, task2.pk)
        # Assignment syncs pickup
        col = make_collector('colpick')
        assign_task(task, col)
        pickup.refresh_from_db()
        self.assertEqual(pickup.status, 'assigned')
        start_task(task)
        pickup.refresh_from_db()
        self.assertEqual(pickup.status, 'in_transit')
        complete_task(task)
        pickup.refresh_from_db()
        self.assertEqual(pickup.status, 'collected')

    def test_pickup_post_view_creates_task(self):
        user = make_user('resident2')
        c = Client()
        c.force_login(user)
        r = c.post('/pickup/request/', data={
            'pickup_address': 'Hostel C', 'city': 'Test',
            'e_waste_category': 'laptop', 'estimated_weight': 3,
            'preferred_date': str(datetime.date.today() + datetime.timedelta(days=1)),
            'preferred_time': 'Morning (9AM-12PM)', 'additional_notes': '',
        })
        self.assertEqual(r.status_code, 302)
        pickup = PickupRequest.objects.filter(user=user).latest('created_at')
        self.assertTrue(CollectionTask.objects.filter(pickup_request=pickup).exists())


class TransitionTests(TestCase):
    def setUp(self):
        self.bin = make_bin('ECO-T-9')
        self.col = make_collector('coltrans')
        post_telemetry(self.bin.bin_id, 85)
        self.task = CollectionTask.objects.get(smart_bin=self.bin)

    def test_assign_start_complete_happy_path(self):
        assign_task(self.task, self.col)
        self.assertIsNotNone(CollectionTask.objects.get(pk=self.task.pk).assigned_at)
        start_task(self.task)
        self.assertIsNotNone(CollectionTask.objects.get(pk=self.task.pk).started_at)
        complete_task(self.task)
        done = CollectionTask.objects.get(pk=self.task.pk)
        self.assertEqual(done.status, 'collected')
        self.assertIsNotNone(done.completed_at)

    def test_invalid_transitions_rejected(self):
        # PENDING -> start directly is invalid
        with self.assertRaises(TaskTransitionError):
            start_task(self.task)
        # PENDING -> complete directly is invalid
        with self.assertRaises(TaskTransitionError):
            complete_task(self.task)
        assign_task(self.task, self.col)
        # ASSIGNED -> complete directly is invalid
        with self.assertRaises(TaskTransitionError):
            complete_task(self.task)

    def test_cancel_and_reassign_rules(self):
        assign_task(self.task, self.col)
        start_task(self.task)
        with self.assertRaises(TaskTransitionError):
            assign_task(self.task, self.col)  # in-transit: must cancel first
        cancelled = cancel_task(CollectionTask.objects.get(pk=self.task.pk))
        # cancelled task cannot complete
        with self.assertRaises(TaskTransitionError):
            complete_task(cancelled)
        # collected tasks cannot be cancelled
        post_telemetry(self.bin.bin_id, 86)
        t2 = CollectionTask.objects.filter(
            smart_bin=self.bin,
            status__in=CollectionTask.ACTIVE_STATUSES).latest('created_at')
        assign_task(t2, self.col)
        start_task(t2)
        complete_task(t2)
        with self.assertRaises(TaskTransitionError):
            cancel_task(t2)

    def test_complete_resolves_alert_but_keeps_fill(self):
        fill_before = SmartBin.objects.get(pk=self.bin.pk).fill_level
        self.assertGreaterEqual(fill_before, 80)
        assign_task(self.task, self.col)
        start_task(self.task)
        complete_task(self.task)
        self.bin.refresh_from_db()
        # Fill NOT fabricated — sensor remains the source of truth.
        self.assertAlmostEqual(self.bin.fill_level, fill_before)
        active_fill = Alert.objects.filter(
            bin=self.bin, alert_type=Alert.AlertType.FILL_LEVEL, is_active=True)
        self.assertEqual(active_fill.count(), 0)

    def test_assign_requires_active_collector(self):
        normal = make_user('plainuser')
        with self.assertRaises(TaskTransitionError):
            assign_task(self.task, normal)
        inactive = make_collector('offcol', active=False)
        with self.assertRaises(TaskTransitionError):
            assign_task(self.task, inactive)


class AuthTests(TestCase):
    def setUp(self):
        self.bin = make_bin('ECO-AUTH-1')
        post_telemetry(self.bin.bin_id, 85)
        self.task = CollectionTask.objects.get(smart_bin=self.bin)
        self.col_a = make_collector('cola2')
        self.col_b = make_collector('colb2')
        self.staff = make_user('ops1', staff=True)
        self.normal = make_user('normal1')
        assign_task(self.task, self.col_a)

    def test_collector_cannot_touch_others_task_page(self):
        c = Client()
        c.force_login(self.col_b)
        # Detail hidden
        self.assertEqual(c.get(f'/tasks/{self.task.pk}/').status_code, 403)
        # Start rejected (goes through service ownership check)
        r = c.post(f'/tasks/{self.task.pk}/start/')
        self.assertIn(r.status_code, (302, 403))
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'assigned')

    def test_collector_cannot_use_admin_ops(self):
        c = Client()
        c.force_login(self.col_a)
        self.assertEqual(c.get('/operations/').status_code, 403)

    def test_normal_user_cannot_access_ops_or_apis(self):
        c = Client()
        c.force_login(self.normal)
        self.assertEqual(c.get('/operations/').status_code, 403)
        self.assertEqual(c.get('/tasks/mine/').status_code, 403)
        self.assertEqual(c.get('/api/collection-tasks/').status_code, 200)
        # Normal user sees only own pickup tasks (none here)
        self.assertEqual(c.get('/api/collection-tasks/').json(), [])

    def test_anon_api_denied(self):
        c = Client()
        self.assertEqual(c.get('/api/collection-tasks/').status_code, 403)

    def test_collector_sees_only_own_tasks_api(self):
        other_bin = make_bin('ECO-AUTH-2')
        post_telemetry(other_bin.bin_id, 86)
        other = CollectionTask.objects.get(smart_bin=other_bin)
        assign_task(other, self.col_b)
        c = Client()
        c.force_login(self.col_a)
        ids = [t['id'] for t in c.get('/api/collection-tasks/').json()]
        self.assertIn(self.task.pk, ids)
        self.assertNotIn(other.pk, ids)
        # Cross-collector detail is 404 (no ID-oracle leak)
        self.assertEqual(c.get(f'/api/collection-tasks/{other.pk}/').status_code, 404)
        # Cross-collector start is 404 or 400, never success
        r = c.post(f'/api/collection-tasks/{other.pk}/start/')
        self.assertIn(r.status_code, (400, 404))

    def test_collector_full_api_flow(self):
        c = Client()
        c.force_login(self.col_a)
        r = c.post(f'/api/collection-tasks/{self.task.pk}/start/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'in_transit')
        r = c.post(f'/api/collection-tasks/{self.task.pk}/complete/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'collected')

    def test_assign_api_staff_only(self):
        c = Client()
        c.force_login(self.col_a)
        self.assertEqual(
            c.post(f'/api/collection-tasks/{self.task.pk}/assign/',
                   data=json.dumps({'collector_id': self.col_b.pk}),
                   content_type='application/json').status_code, 403)
        c.force_login(self.staff)
        r = c.post(
            f'/api/collection-tasks/{self.task.pk}/assign/',
            data=json.dumps({'collector_id': self.col_b.pk}),
            content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['assigned_to'], self.col_b.username)

    def test_collector_dashboard_page_lists_own(self):
        c = Client()
        c.force_login(self.col_a)
        r = c.get('/tasks/mine/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.bin.bin_id)

    def test_ops_dashboard_requires_staff(self):
        c = Client()
        c.force_login(self.staff)
        r = c.get('/operations/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Operations control center')
