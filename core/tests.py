"""Day 5 tests: alert engine, dedupe, recovery, offline, sources, API security.

Run: python manage.py test core
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from bins.models import SmartBin, Telemetry
from core.alerts import monitoring_summary, process_bin_alerts
from core.models import Alert


def make_bin(bin_id='ECO-TEST-1'):
    return SmartBin.objects.create(
        bin_id=bin_id, name='Test Bin', location='Lab', city='Test',
        latitude=0, longitude=0, fill_level=10, weight=2.5,
        temperature=29.0, is_online=True, last_seen=timezone.now(),
    )


class AlertEngineTests(TestCase):
    def setUp(self):
        self.bin = make_bin()

    def post_telemetry(self, **payload):
        c = Client()
        body = {'device_id': self.bin.bin_id, 'fill_level': 10,
                'weight': 2.5, 'temperature': 29.0}
        body.update(payload)
        import json
        return c.post('/api/telemetry/', data=json.dumps(body),
                      content_type='application/json')

    def active(self, alert_type):
        return Alert.objects.filter(
            bin=self.bin, alert_type=alert_type, is_active=True)

    def test_1_fill_creates_critical(self):
        self.assertEqual(self.post_telemetry(fill_level=87).status_code, 201)
        a = self.active(Alert.AlertType.FILL_LEVEL)
        self.assertEqual(a.count(), 1)
        self.assertEqual(a.first().severity, Alert.Severity.CRITICAL)

    def test_2_no_duplicate_fill_alerts(self):
        self.post_telemetry(fill_level=87)
        self.post_telemetry(fill_level=91)
        self.post_telemetry(fill_level=88)
        self.assertEqual(self.active(Alert.AlertType.FILL_LEVEL).count(), 1)

    def test_3_fill_recovery_resolves(self):
        self.post_telemetry(fill_level=87)
        self.assertEqual(self.active(Alert.AlertType.FILL_LEVEL).count(), 1)
        self.post_telemetry(fill_level=30)
        self.assertEqual(self.active(Alert.AlertType.FILL_LEVEL).count(), 0)
        resolved = Alert.objects.filter(
            bin=self.bin, alert_type=Alert.AlertType.FILL_LEVEL,
            is_active=False)
        self.assertEqual(resolved.count(), 1)
        self.assertIsNotNone(resolved.first().resolved_at)

    def test_4_high_temp_creates_alert(self):
        self.assertEqual(self.post_telemetry(temperature=46).status_code, 201)
        a = self.active(Alert.AlertType.HIGH_TEMPERATURE)
        self.assertEqual(a.count(), 1)
        self.assertEqual(a.first().severity, Alert.Severity.CRITICAL)

    def test_4b_temp_warning_severity(self):
        self.post_telemetry(temperature=41)
        a = self.active(Alert.AlertType.HIGH_TEMPERATURE)
        self.assertEqual(a.count(), 1)
        self.assertEqual(a.first().severity, Alert.Severity.WARNING)

    def test_5_normal_temp_no_alert(self):
        self.post_telemetry(temperature=29)
        self.assertEqual(
            self.active(Alert.AlertType.HIGH_TEMPERATURE).count(), 0)

    def test_6_offline_detection(self):
        self.bin.last_seen = timezone.now() - timedelta(minutes=60)
        self.bin.save(update_fields=['last_seen'])
        c = Client()
        c.get('/api/bins/')  # lazy sweep path
        self.bin.refresh_from_db()
        self.assertFalse(self.bin.is_online)
        self.assertEqual(
            self.active(Alert.AlertType.DEVICE_OFFLINE).count(), 1)

    def test_7_telemetry_marks_online(self):
        self.bin.is_online = False
        self.bin.last_seen = timezone.now() - timedelta(minutes=60)
        self.bin.save()
        self.assertEqual(self.post_telemetry(fill_level=20).status_code, 201)
        self.bin.refresh_from_db()
        self.assertTrue(self.bin.is_online)

    def test_8_offline_resolves_on_return(self):
        from core.alerts import sweep_offline_alerts
        self.bin.last_seen = timezone.now() - timedelta(minutes=60)
        self.bin.save(update_fields=['last_seen'])
        sweep_offline_alerts()
        self.assertEqual(
            self.active(Alert.AlertType.DEVICE_OFFLINE).count(), 1)
        self.post_telemetry(fill_level=20)  # device back
        self.assertEqual(
            self.active(Alert.AlertType.DEVICE_OFFLINE).count(), 0)

    def test_9_simulate_is_simulated(self):
        import json
        c = Client()
        r = c.post('/api/telemetry/simulate/',
                   data=json.dumps({'device_id': self.bin.bin_id}),
                   content_type='application/json')
        self.assertEqual(r.status_code, 201)
        t = Telemetry.objects.filter(smart_bin=self.bin).latest('timestamp')
        self.assertEqual(t.data_source, 'simulated')

    def test_10_real_stays_real(self):
        self.post_telemetry(fill_level=50)
        t = Telemetry.objects.filter(smart_bin=self.bin).latest('timestamp')
        self.assertEqual(t.data_source, 'real')
        self.bin.refresh_from_db()
        self.assertEqual(self.bin.data_source, 'real')

    def test_11_resolve_requires_staff(self):
        self.post_telemetry(fill_level=87)
        alert = self.active(Alert.AlertType.FILL_LEVEL).first()
        c = Client()
        self.assertEqual(
            c.post(f'/api/alerts/{alert.pk}/resolve/').status_code, 403)
        user = User.objects.create_user('normal', 'n@t.com', 'pass12345')
        c.force_login(user)
        self.assertEqual(
            c.post(f'/api/alerts/{alert.pk}/resolve/').status_code, 403)
        staff = User.objects.create_user('staff', 's@t.com', 'pass12345',
                                         is_staff=True)
        c.force_login(staff)
        r = c.post(f'/api/alerts/{alert.pk}/resolve/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['is_active'])

    def test_12_invalid_telemetry_rejected(self):
        import json
        c = Client()
        for body in [{'device_id': self.bin.bin_id, 'weight': 1},  # no fill
                     {'device_id': self.bin.bin_id, 'fill_level': 120, 'weight': 1},
                     {'device_id': 'NOPE', 'fill_level': 10, 'weight': 1}]:
            r = c.post('/api/telemetry/', data=json.dumps(body),
                       content_type='application/json')
            self.assertIn(r.status_code, (400, 404))
        self.assertIn('error', r.json())

    def test_13_alert_api_data(self):
        self.post_telemetry(fill_level=87)
        c = Client()
        r = c.get('/api/alerts/?active=true')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(all(a['is_active'] for a in r.json()))
        alert = Alert.objects.filter(is_active=True).first()
        r = c.get(f'/api/alerts/{alert.pk}/')
        self.assertEqual(r.json()['bin_id'], self.bin.bin_id)
        r = c.get('/api/alerts/999999/')
        self.assertEqual(r.status_code, 404)

    def test_14_summary_correct(self):
        self.post_telemetry(fill_level=87)
        s = monitoring_summary()
        self.assertGreaterEqual(s['total_bins'], 1)
        self.assertEqual(s['critical_bins'],
                         SmartBin.objects.filter(fill_level__gte=80).count())
        self.assertEqual(s['active_alerts'],
                         Alert.objects.filter(is_active=True).count())

    def test_process_bin_alerts_reusable(self):
        process_bin_alerts(self.bin, online_now=True)
        self.assertEqual(Alert.objects.filter(is_active=True).count(), 0)
