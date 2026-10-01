"""Admin registrations — Day 1: everything visible, no custom logic yet."""
from django.contrib import admin

from .models import Alert, Profile
from bins.models import SmartBin, Telemetry
from waste.models import Collection, EwasteSubmission, PickupRequest, RecyclingRecord


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone', 'created_at')
    search_fields = ('user__username', 'phone')


@admin.register(SmartBin)
class SmartBinAdmin(admin.ModelAdmin):
    list_display = (
        'bin_id', 'name', 'location', 'fill_percentage',
        'weight', 'temperature', 'is_online', 'data_source', 'last_seen',
    )
    list_filter = ('is_online', 'data_source')
    search_fields = ('bin_id', 'name', 'location')


@admin.register(Telemetry)
class TelemetryAdmin(admin.ModelAdmin):
    list_display = ('bin', 'fill_level', 'weight', 'temperature', 'is_simulated', 'recorded_at')
    list_filter = ('is_simulated',)
    date_hierarchy = 'recorded_at'


@admin.register(EwasteSubmission)
class EwasteSubmissionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'category', 'quantity', 'estimated_weight', 'status', 'created_at')
    list_filter = ('category', 'status')


@admin.register(PickupRequest)
class PickupRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'category', 'status', 'preferred_date', 'created_at')
    list_filter = ('status', 'category')


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ('id', 'pickup', 'bin', 'status', 'collected_weight', 'created_at')
    list_filter = ('status',)


@admin.register(RecyclingRecord)
class RecyclingRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'collection', 'processing_status', 'received_weight', 'created_at')
    list_filter = ('processing_status',)


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ('id', 'alert_type', 'severity', 'bin', 'is_resolved', 'created_at')
    list_filter = ('alert_type', 'severity', 'is_resolved')
