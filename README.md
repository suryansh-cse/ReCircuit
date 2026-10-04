# RE-CIRCUIT — Smart E-Waste Collection, Monitoring & Recycling Platform

**Track. Collect. Recycle.**

IoT-powered e-waste management connecting users, smart bins, collections and recycling in one Django web app.

## Day 1 — Foundation (this commit)
- Django 6 + DRF + SQLite project scaffold (`config/`, `core/`, `bins/`, `waste/`)
- Full database models: Profile, Alert, SmartBin, Telemetry, EwasteSubmission, PickupRequest, Collection, RecyclingRecord
- Landing page with **live stats from `/api/dashboard/stats/`** (zero hardcoding)
- Custom eco-tech UI (no generic Bootstrap template)
- Admin registrations for all models

## Quickstart
```powershell
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open:
- Landing: http://127.0.0.1:8000/
- Stats API: http://127.0.0.1:8000/api/dashboard/stats/
- Admin: http://127.0.0.1:8000/admin/

## 9-day plan
- Day 1: setup + landing ✅
- Day 2: auth + user dashboard + submissions ✅
- Day 3: pickups + smart-bin foundation ✅
- Day 4: ESP32 telemetry API + bin monitoring ✅
- Day 5: live monitoring + alerts ✅
- Day 6: collections + pickup lifecycle ✅
- Day 7: recycling + analytics + maps ✅
- Day 8: polish + responsive + errors ✅
- Day 9: testing + docs + demo ✅

## Day 5 — live monitoring & alerts
- Alert engine (`core/alerts.py`): fill / temperature / offline rules, one active
  alert per (bin, type), severity escalates in place, recovery resolves.
- Thresholds (central, `config/settings.py`): fill warning 60%, critical 80%;
  temperature warning 40°C, critical 45°C; offline after 15 min silence.
- Pages: `/bins/` (5 s polling, summary counts, per-bin alert badges),
  `/bins/<id>/` (10 s polling + Chart.js history + staff simulate presets),
  `/alerts/` (Active/All/Resolved + severity groups).
- APIs: `GET /api/alerts/` (`?active=&severity=&bin=`), `GET /api/alerts/<id>/`,
  `POST /api/alerts/<id>/resolve/` (staff only), `GET /api/bins/<id>/history/`.
- Simulate accepts explicit values for scenario testing, always SIMULATED:
  `{"device_id":"ECO-BIN-001","fill_level":90,"weight":22.5,"temperature":32}`
- Tests: `python manage.py test core` (16 tests).

## Migrating to PostgreSQL later
Swap `DATABASES` in `config/settings.py` — no model changes needed.
