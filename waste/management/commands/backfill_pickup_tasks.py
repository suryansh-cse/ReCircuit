"""Backfill CollectionTasks for PENDING pickups that have none.

Day 8 repair companion for the pickup -> operations visibility fix:
pickups created before the Day 6 auto-task hook (or whose creation hit a
transient error) never appeared in Operations. Idempotent — pickups that
already have an active task are skipped (dedupe inside ensure_pickup_task).

Usage: python manage.py backfill_pickup_tasks
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Create CollectionTasks for PENDING pickups missing an active task.'

    def handle(self, *args, **options):
        from waste.collections import ensure_pickup_task, orphan_pickups
        orphans = list(orphan_pickups())
        created = 0
        for pickup in orphans:
            _task, was_created = ensure_pickup_task(pickup)
            if was_created:
                created += 1
        self.stdout.write(
            self.style.SUCCESS(
                f'Checked {len(orphans)} orphan pickup(s), '
                f'created {created} task(s).'
            )
        )
