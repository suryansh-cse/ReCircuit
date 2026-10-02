"""Day 7 tests: traceable submissions, QR sessions, recycling, analytics.

Run: python manage.py test waste
Covers spec Part 18 (1-14). Existing Day 1-6 tests are untouched.
"""
import datetime
import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from bins.models import SmartBin
from core.models import Profile
from waste.models import DepositSession, EwasteSubmission, RecyclingRecord
from waste.recycling import (
    SubmissionTransitionError,
    advance_submission,
    get_valid_session,
    recycling_summary,
    start_deposit_session,
)


def make_bin(bin_id='ECO-BIN-007', fill=72.0):
    return SmartBin.objects.create(
        bin_id=bin_id, name='Test Bin 7', location='Hostel Block C',
        city='Test', latitude=31.2552, longitude=75.7037,
        fill_level=fill, weight=18.0, temperature=29.0,
        is_online=True, last_seen=timezone.now(),
    )


def make_user(name, password='pass12345', staff=False):
    u = User.objects.create_user(name, f'{name}@t.com', password)
    if staff:
        u.is_staff = True
        u.save()
    Profile.objects.get_or_create(user=u)
    return u


def submit_form(client, **overrides):
    body = {'category': 'laptop', 'quantity': 1, 'estimated_weight': 2.4,
            'condition': 'damaged', 'description': 'Old laptop',
            'submission_method': 'pickup'}
    body.update(overrides)
    return client.post('/submit/', data=body)


class SubmissionOwnershipTests(TestCase):
    def test_1_authenticated_user_creates_submission(self):
        user = make_user('u1')
        c = Client()
        c.force_login(user)
        r = submit_form(c)
        self.assertEqual(r.status_code, 302)
        sub = EwasteSubmission.objects.get(user=user)
        self.assertEqual(sub.category, 'laptop')
        self.assertEqual(sub.status, 'submitted')

    def test_2_owner_is_request_user(self):
        user = make_user('u2')
        c = Client()
        c.force_login(user)
        submit_form(c)
        sub = EwasteSubmission.objects.get(user=user)
        self.assertEqual(sub.user_id, user.pk)

    def test_3_cannot_claim_another_user(self):
        alice = make_user('alice')
        bob = make_user('bob')
        c = Client()
        c.force_login(alice)
        # No user field exists on the form; even a forged one is ignored.
        submit_form(c, user=bob.pk)
        self.assertEqual(EwasteSubmission.objects.filter(user=alice).count(), 1)
        self.assertEqual(EwasteSubmission.objects.filter(user=bob).count(), 0)
        # ...and someone else's pickup cannot be attached either.
        pickup_owner = bob
        from waste.models import PickupRequest
        pickup = PickupRequest.objects.create(
            user=pickup_owner, pickup_address='X', city='T',
            e_waste_category='laptop', estimated_weight=1.0,
            preferred_date=datetime.date.today() + timedelta(days=1))
        r = submit_form(c, pickup_request=pickup.pk)
        self.assertEqual(r.status_code, 200)  # re-rendered with errors
        sub = EwasteSubmission.objects.get(user=alice)
        self.assertIsNone(sub.pickup_request)


class BinAssociationTests(TestCase):
    def setUp(self):
        self.bin = make_bin()

    def test_4_smart_bin_association(self):
        user = make_user('u4')
        c = Client()
        c.force_login(user)
        r = submit_form(c, submission_method='smart_bin', bin_id=self.bin.bin_id)
        self.assertEqual(r.status_code, 302)
        sub = EwasteSubmission.objects.get(user=user)
        self.assertEqual(sub.smart_bin_id, self.bin.pk)
        self.assertEqual(sub.submission_method, 'smart_bin')
        self.assertEqual(sub.verification_status, 'pending')

    def test_6_invalid_bin_rejected(self):
        user = make_user('u6')
        c = Client()
        c.force_login(user)
        r = submit_form(c, submission_method='smart_bin', bin_id='NOPE-999')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(EwasteSubmission.objects.filter(user=user).count(), 0)

    def test_6b_smart_bin_without_bin_rejected(self):
        user = make_user('u6b')
        c = Client()
        c.force_login(user)
        r = submit_form(c, submission_method='smart_bin', bin_id='')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(EwasteSubmission.objects.filter(user=user).count(), 0)


class QRSessionTests(TestCase):
    def setUp(self):
        self.bin = make_bin()
        self.other = make_bin('ECO-BIN-008', fill=20.0)
        self.user = make_user('qruser')

    def start(self):
        return start_deposit_session(self.user, self.bin)

    def test_5_qr_verified_flow(self):
        session = self.start()
        c = Client()
        c.force_login(self.user)
        r = submit_form(c, submission_method='smart_bin',
                        bin_id=self.bin.bin_id, session_token=session.token)
        self.assertEqual(r.status_code, 302)
        sub = EwasteSubmission.objects.get(user=self.user)
        self.assertEqual(sub.verification_status, 'qr_verified')
        self.assertEqual(sub.deposit_session_id, session.pk)
        session.refresh_from_db()
        self.assertTrue(session.is_completed)

    def test_5b_session_single_use(self):
        session = self.start()
        c = Client()
        c.force_login(self.user)
        submit_form(c, submission_method='smart_bin',
                    bin_id=self.bin.bin_id, session_token=session.token)
        r = submit_form(c, submission_method='smart_bin',
                        bin_id=self.bin.bin_id, session_token=session.token)
        self.assertEqual(r.status_code, 200)  # rejected, form error
        self.assertEqual(EwasteSubmission.objects.filter(user=self.user).count(), 1)

    def test_5c_session_locked_to_its_bin(self):
        session = self.start()  # for ECO-BIN-007
        c = Client()
        c.force_login(self.user)
        r = submit_form(c, submission_method='smart_bin',
                        bin_id=self.other.bin_id, session_token=session.token)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(EwasteSubmission.objects.filter(user=self.user).count(), 0)

    def test_5d_foreign_user_token_rejected(self):
        session = self.start()
        stranger = make_user('stranger')
        c = Client()
        c.force_login(stranger)
        r = submit_form(c, submission_method='smart_bin',
                        bin_id=self.bin.bin_id, session_token=session.token)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(EwasteSubmission.objects.count(), 0)

    def test_7_expired_session_cannot_verify(self):
        session = self.start()
        session.expires_at = timezone.now() - timedelta(seconds=1)
        session.save(update_fields=['expires_at'])
        self.assertIsNone(get_valid_session(self.user, session.token))
        c = Client()
        c.force_login(self.user)
        r = submit_form(c, submission_method='smart_bin',
                        bin_id=self.bin.bin_id, session_token=session.token)
        self.assertEqual(r.status_code, 200)
        # Nothing verified was created from the expired session.
        self.assertEqual(
            EwasteSubmission.objects.filter(verification_status='qr_verified').count(), 0)


class VisibilityTests(TestCase):
    def test_8_user_sees_only_own(self):
        a, b = make_user('va'), make_user('vb')
        EwasteSubmission.objects.create(
            user=a, category='laptop', quantity=1, estimated_weight=1.0,
            condition='damaged')
        EwasteSubmission.objects.create(
            user=b, category='battery', quantity=2, estimated_weight=0.5,
            condition='working')
        c = Client()
        c.force_login(a)
        r = c.get('/my-ewaste/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Laptop')
        self.assertNotContains(r, 'Battery')
        r = c.get('/api/ewaste/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), 1)
        other_id = EwasteSubmission.objects.get(user=b).pk
        self.assertEqual(c.get(f'/api/ewaste/{other_id}/').status_code, 404)

    def test_9_admin_sees_all(self):
        a = make_user('wa')
        staff = make_user('wstaff', staff=True)
        EwasteSubmission.objects.create(
            user=a, category='laptop', quantity=1, estimated_weight=1.0,
            condition='damaged')
        c = Client()
        c.force_login(staff)
        r = c.get('/api/ewaste/?scope=all')
        self.assertEqual(len(r.json()), 1)
        r = c.get('/recycling/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Recycling operations')
        # Normal users are locked out of recycling ops.
        c.force_login(a)
        self.assertEqual(c.get('/recycling/').status_code, 403)
        self.assertEqual(c.get('/api/recycling/').status_code, 403)


class LifecycleTests(TestCase):
    def setUp(self):
        self.user = make_user('lc')
        self.staff = make_user('lstaff', staff=True)
        self.sub = EwasteSubmission.objects.create(
            user=self.user, category='laptop', quantity=1,
            estimated_weight=2.4, condition='damaged')

    def test_10_recycling_record_created_on_collect(self):
        advance_submission(self.sub, 'collected', by_user=self.staff)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, 'collected')
        rec = RecyclingRecord.objects.filter(submission=self.sub)
        self.assertEqual(rec.count(), 1)
        self.assertEqual(rec.first().processing_status, 'awaiting_processing')

    def test_11_forward_only_transitions(self):
        with self.assertRaises(SubmissionTransitionError):
            advance_submission(self.sub, 'processing', by_user=self.staff)  # skip
        with self.assertRaises(SubmissionTransitionError):
            advance_submission(self.sub, 'recycled', by_user=self.staff)  # skip
        advance_submission(self.sub, 'collected', by_user=self.staff)
        with self.assertRaises(SubmissionTransitionError):
            advance_submission(self.sub, 'submitted', by_user=self.staff)  # back
        advance_submission(self.sub, 'processing', by_user=self.staff)
        advance_submission(self.sub, 'recycled', by_user=self.staff,
                           actual_weight=2.1, partner='Campus Facility',
                           notes='Boards recovered')
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, 'recycled')
        self.assertAlmostEqual(self.sub.actual_weight, 2.1)
        rec = RecyclingRecord.objects.get(submission=self.sub)
        self.assertEqual(rec.processing_status, 'recycled')
        self.assertEqual(rec.recycling_partner, 'Campus Facility')
        self.assertIsNotNone(rec.recycled_at)

    def test_11b_non_staff_cannot_advance(self):
        with self.assertRaises(SubmissionTransitionError):
            advance_submission(self.sub, 'collected', by_user=self.user)
        c = Client()
        c.force_login(self.user)
        self.assertEqual(
            c.post(f'/api/ewaste/{self.sub.pk}/advance/',
                   data=json.dumps({'action': 'collected'}),
                   content_type='application/json').status_code, 403)

    def test_day6_task_completion_collects_submissions(self):
        """Part 16: pickup task COLLECTED pulls linked submissions along."""
        from waste.collections import assign_task, complete_task, start_task
        from waste.models import PickupRequest
        pickup = PickupRequest.objects.create(
            user=self.user, pickup_address='X', city='T',
            e_waste_category='laptop', estimated_weight=2.4,
            preferred_date=datetime.date.today() + timedelta(days=1))
        self.sub.pickup_request = pickup
        self.sub.save(update_fields=['pickup_request'])
        from waste.collections import ensure_pickup_task
        task, _ = ensure_pickup_task(pickup)
        col = make_user('day6col')
        col.profile.role = Profile.Role.COLLECTOR
        col.profile.save()
        assign_task(task, col)
        start_task(task)
        complete_task(task)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, 'collected')
        self.assertTrue(
            RecyclingRecord.objects.filter(submission=self.sub).exists())


class AnalyticsTests(TestCase):
    def test_12_summary_uses_database(self):
        u = make_user('an')
        EwasteSubmission.objects.create(
            user=u, category='laptop', quantity=1, estimated_weight=2.4,
            condition='damaged')
        EwasteSubmission.objects.create(
            user=u, category='battery', quantity=2, estimated_weight=0.5,
            condition='working')
        s = recycling_summary()
        self.assertEqual(s['total_submissions'], 2)
        self.assertAlmostEqual(s['total_weight'], 2.9)
        laptop = [c for c in s['by_category'] if c['category'] == 'laptop'][0]
        self.assertEqual(laptop['count'], 1)
        self.assertAlmostEqual(laptop['weight'], 2.4)
        self.assertEqual(s['today'], 2)
        c = Client()
        r = c.get('/api/analytics/recycling/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['total_submissions'], 2)

    def test_12b_empty_db_is_zeros(self):
        s = recycling_summary()
        self.assertEqual(s['total_submissions'], 0)
        self.assertEqual(s['total_weight'], 0.0)

    def test_13_map_data_correct(self):
        make_bin('ECO-MAP-1', fill=35.0)
        c = Client()
        r = c.get('/api/bins/')
        self.assertEqual(r.status_code, 200)
        row = [b for b in r.json() if b['bin_id'] == 'ECO-MAP-1'][0]
        self.assertIn('latitude', row)
        self.assertIn('longitude', row)
        self.assertIn('fill_status', row)
        self.assertIn('data_source', row)
        self.assertEqual(c.get('/bins/map/').status_code, 200)
        # QR endpoint exposes the static deposit URL.
        r = c.get('/api/bins/ECO-MAP-1/qr/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['deposit_url'].endswith('/bins/ECO-MAP-1/deposit/'))
        self.assertEqual(c.get('/api/bins/NOPE/qr/').status_code, 404)


class DepositApiTests(TestCase):
    def test_deposit_start_and_qr_verified_api(self):
        make_bin()
        user = make_user('api7')
        c = Client()
        c.force_login(user)
        r = c.post('/api/deposit/start/',
                   data=json.dumps({'bin_id': 'ECO-BIN-007'}),
                   content_type='application/json')
        self.assertEqual(r.status_code, 201)
        token = r.json()['token']
        r = c.post('/api/ewaste/', data=json.dumps({
            'category': 'laptop', 'quantity': 1, 'estimated_weight': 2.4,
            'condition': 'damaged', 'description': '',
            'submission_method': 'smart_bin', 'bin_id': 'ECO-BIN-007',
            'session_token': token,
        }), content_type='application/json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['verification_status'], 'qr_verified')
        self.assertEqual(r.json()['bin_id'], 'ECO-BIN-007')

    def test_deposit_unknown_bin_404(self):
        user = make_user('api7b')
        c = Client()
        c.force_login(user)
        r = c.post('/api/deposit/start/',
                   data=json.dumps({'bin_id': 'NOPE'}),
                   content_type='application/json')
        self.assertEqual(r.status_code, 404)

    def test_ewaste_api_requires_auth(self):
        c = Client()
        self.assertEqual(c.get('/api/ewaste/').status_code, 403)
        self.assertEqual(c.post('/api/ewaste/', data=json.dumps({}),
                               content_type='application/json').status_code, 403)
