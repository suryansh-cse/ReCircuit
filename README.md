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
- Day 2: auth + user dashboard + submissions
- Day 3: pickups + admin foundations
- Day 4: ESP32 telemetry API + bin monitoring
- Day 5: simulation mode + alerts
- Day 6: collections + pickup lifecycle
- Day 7: recycling + analytics + maps
- Day 8: polish + responsive + errors
- Day 9: testing + docs + demo

## Migrating to PostgreSQL later
Swap `DATABASES` in `config/settings.py` — no model changes needed.
