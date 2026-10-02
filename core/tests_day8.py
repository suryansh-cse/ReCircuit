"""Day 8 tests: pickup->ops integration, role UX, navbar, cleanup, security.

Run: python manage.py test core
Covers spec Part 24 (1-14). Day 1-7 tests untouched (except one heading
assertion updated for the renamed ops control center).
"""
import datetime
import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase
from django.utils import timezone

from bins.models import SmartBin
from core.models import Profile
from waste.collections import ensure_pickup_task, orphan_pickups
from waste.models import CollectionTask, EwasteSubmission, PickupRequest


def make_bin(bin_id='ECO-D8-1', fill=30.0):
    return SmartBin.objects.create(
        bin_id=bin_id, name='D8 Bin', location='Block D', city='Test',
        latitude=31.25, longitude=75.70, fill_level=fill, weight=5.0,
        temperature=29.0, is_online=True, last_seen=timezone.now(),
    )


def make_user(name, password='pass12345', staff=False, collector=False):
    u = User.objects.create_user(name, f'{name}@t.com', password)
    if staff:
        u.is_staff = True
        u.save()
    p, _ = Profile.objects.get_or_create(user=u)
    if collector:
        p.role = Profile.Role.COLLECTOR
        p.employee_id = f'EMP-{name.upper()}'
        p.is_collector_active = True
        p.save()
    return u


def make_pickup(user, status='pending'):
    p = PickupRequest.objects.create(
        user=user, pickup_address='12 Green St', city='Test',
        e_waste_category='laptop', estimated_weight=2.4,
        preferred_date=datetime.date.today() + timedelta(days=1),
        preferred_time='Morning (9AM-12PM)')
    if status != 'pending':
        p.status = status
        p.save(update_fields=['status'])
    return p


class PickupToOpsTests(TestCase):
    def test_1_pickup_visible_in_ops_without_task(self):
        """Orphan PENDING pickups surface in Operations (the Day 8 fix)."""
        user = make_user('d8user1')
        pickup = make_pickup(user)
        self.assertEqual(list(orphan_pickups()), [pickup])
        staff = make_user('d8staff1', staff=True)
        c = Client()
        c.force_login(staff)
        r = c.get('/operations/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, pickup.display_id)
        self.assertContains(r, 'waiting for a task')
        self.assertContains(r, '12 Green St')

    def test_2_ensure_task_from_ops_no_duplicates(self):
        user = make_user('d8user2')
        pickup = make_pickup(user)
        staff = make_user('d8staff2', staff=True)
        c = Client()
        c.force_login(staff)
        r = c.post(f'/operations/pickup/{pickup.pk}/ensure-task/')
        self.assertEqual(r.status_code, 302)
        task = CollectionTask.objects.get(pickup_request=pickup)
        self.assertEqual(r.url, f'/tasks/{task.pk}/')
        # Second click is idempotent — still exactly one active task.
        c.post(f'/operations/pickup/{pickup.pk}/ensure-task/')
        self.assertEqual(
            CollectionTask.objects.filter(
                pickup_request=pickup,
                status__in=CollectionTask.ACTIVE_STATUSES).count(), 1)
        self.assertEqual(list(orphan_pickups()), [])

    def test_2b_backfill_command(self):
        user = make_user('d8user2b')
        pickup = make_pickup(user)
        call_command('backfill_pickup_tasks')
        pickup.refresh_from_db()
        self.assertTrue(
            CollectionTask.objects.filter(pickup_request=pickup).exists())
        # Idempotent on re-run.
        call_command('backfill_pickup_tasks')
        self.assertEqual(
            CollectionTask.objects.filter(pickup_request=pickup).count(), 1)

    def test_3_ops_pickup_table_columns(self):
        user = make_user('d8user3')
        make_pickup(user)
        staff = make_user('d8staff3', staff=True)
        c = Client()
        c.force_login(staff)
        content = c.get('/operations/').content.decode()
        for needle in ('Pickup requests', 'Collector', 'Preferred',
                       'All collection tasks'):
            self.assertIn(needle, content)

    def test_4_normal_user_cannot_see_ops_pickups(self):
        user = make_user('d8user4')
        other = make_user('d8other4')
        make_pickup(other)
        c = Client()
        c.force_login(user)
        self.assertEqual(c.get('/operations/').status_code, 403)
        # ...and the pickup list API stays owner-scoped (tasks API).
        self.assertEqual(c.get('/api/collection-tasks/').json(), [])


class RoleRedirectTests(TestCase):
    def login_redirects_to(self, username, password='pass12345'):
        c = Client()
        r = c.post('/login/', data={'username': username, 'password': password})
        self.assertEqual(r.status_code, 302)
        return r.url

    def test_5_user_goes_to_dashboard(self):
        make_user('d8u5')
        self.assertEqual(self.login_redirects_to('d8u5'), '/dashboard/')

    def test_5b_collector_goes_to_tasks(self):
        make_user('d8c5', collector=True)
        self.assertEqual(self.login_redirects_to('d8c5'), '/tasks/mine/')

    def test_5c_staff_goes_to_operations(self):
        make_user('d8s5', staff=True)
        self.assertEqual(self.login_redirects_to('d8s5'), '/operations/')

    def test_5d_dashboard_routes_roles(self):
        c = Client()
        staff = make_user('d8s5d', staff=True)
        c.force_login(staff)
        self.assertEqual(c.get('/dashboard/').status_code, 302)
        col = make_user('d8c5d', collector=True)
        c.force_login(col)
        r = c.get('/dashboard/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/tasks/mine/', r.url)


class NavbarTests(TestCase):
    def test_6_public_navbar(self):
        content = Client().get('/').content.decode()
        for needle in ('Home', 'How It Works', 'Smart Bins', 'About',
                       'Login', 'Register', 'nav-toggle'):
            self.assertIn(needle, content)
        self.assertNotIn('Operations', content)
        self.assertNotIn('My Tasks', content)

    def test_6b_user_navbar(self):
        user = make_user('d8u6')
        c = Client()
        c.force_login(user)
        content = c.get('/dashboard/').content.decode()
        for needle in ('Dispose E-Waste', 'Find a Bin', 'Request Pickup',
                       'My E-Waste', 'My Activity', 'My Pickups', 'nav-toggle'):
            self.assertIn(needle, content)
        self.assertNotIn('Operations', content)
        self.assertNotIn('My Tasks', content)
        self.assertNotIn('/admin/', content)

    def test_6c_ops_navbar(self):
        staff = make_user('d8s6', staff=True)
        c = Client()
        c.force_login(staff)
        content = c.get('/operations/').content.decode()
        for needle in ('ReCircuit', 'Operations', 'Pickups', 'Tasks',
                       'Smart Bins', 'Recycling', 'Team'):
            self.assertIn(needle, content)

    def test_6d_collector_navbar(self):
        col = make_user('d8c6', collector=True)
        c = Client()
        c.force_login(col)
        content = c.get('/tasks/mine/').content.decode()
        for needle in ('Collector dashboard', 'My Tasks', 'History'):
            self.assertIn(needle, content)
        self.assertNotIn('Operations', content)
        self.assertNotIn('Team', content)


class UserInterfaceCleanupTests(TestCase):
    def user_pages(self):
        make_bin()
        user = make_user('d8u7')
        c = Client()
        c.force_login(user)
        return [c.get(url).content.decode() for url in (
            '/', '/dashboard/', '/submit/', '/pickup/my/',
            '/pickup/request/', '/my-ewaste/', '/bins/', '/alerts/')]

    def test_7_no_technical_links_in_user_ui(self):
        for content in self.user_pages():
            self.assertNotIn('href="/api', content)
            self.assertNotIn('href="/admin/', content)
            self.assertNotIn('POST /api', content)
            self.assertNotIn('Telemetry', content)
            self.assertNotIn('ESP32', content)
            self.assertNotIn('Day 1', content)
            self.assertNotIn('Day 6', content)

    def test_7b_simulated_label_kept(self):
        """REAL/SIMULATED distinction must survive the cleanup (spec)."""
        contents = self.user_pages()
        self.assertTrue(any('SIMULATED' in p for p in contents))

    def test_7c_friendly_offline_label(self):
        user = make_user('d8u7c')
        c = Client()
        c.force_login(user)
        self.assertNotIn('Device Offline', c.get('/alerts/').content.decode())


class DashboardDataTests(TestCase):
    def test_8_stats_come_from_database(self):
        user = make_user('d8u8')
        EwasteSubmission.objects.create(
            user=user, category='laptop', quantity=1, estimated_weight=2.4,
            condition='damaged', status='recycled')
        make_pickup(user)
        c = Client()
        c.force_login(user)
        content = c.get('/dashboard/').content.decode()
        self.assertIn('Recent activity', content)
        self.assertIn('Laptop submitted', content)
        self.assertIn('requested', content)

    def test_8b_ops_control_stats(self):
        user = make_user('d8u8b')
        make_bin('ECO-D8-FULL', fill=91.0)
        make_pickup(user)
        staff = make_user('d8s8b', staff=True)
        c = Client()
        c.force_login(staff)
        content = c.get('/operations/').content.decode()
        for needle in ('total pickups', 'pending pickups', 'active collections',
                       'bins needing collection', 'active alerts',
                       'total e-waste', 'recycled weight'):
            self.assertIn(needle, content)

    def test_9_display_ids(self):
        user = make_user('d8u9')
        pickup = make_pickup(user)
        self.assertTrue(pickup.display_id.startswith('PR-'))
        task, _ = ensure_pickup_task(pickup)
        self.assertTrue(task.display_id.startswith('CT-'))
        self.assertEqual(task.type_label, 'User Pickup')


class CollectorVisibilityTests(TestCase):
    def test_10_collector_sees_pickup_job_details(self):
        user = make_user('d8u10')
        col = make_user('d8c10', collector=True)
        pickup = make_pickup(user)
        task, _ = ensure_pickup_task(pickup)
        from waste.collections import assign_task
        assign_task(task, col)
        c = Client()
        c.force_login(col)
        content = c.get('/tasks/mine/').content.decode()
        self.assertIn('User Pickup', content)
        self.assertIn('12 Green St', content)
        self.assertIn('Laptop', content)
        self.assertIn(task.display_id, content)
