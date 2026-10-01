"""Admin registrations — Day 1: everything visible, no custom logic yet."""
from django.contrib import admin

from .models import Alert, Profile
from bins.models import SmartBin, Telemetry
from waste.models import Collection, EwasteSubmission, PickupRequest, RecyclingRecord


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'full_name', 'city', 'phone', 'created_at')
    search_fields = ('user__username', 'full_name', 'phone', 'city')


@admin.register(SmartBin)
class SmartBinAdmin(admin.ModelAdmin):
    list_display = (
        'bin_id', 'name', 'location', 'city', 'fill_level',
        'weight', 'temperature', 'is_online', 'data_source', 'last_seen',
    )
    list_filter = ('is_online', 'data_source')
    search_fields = ('bin_id', 'name', 'location', 'city')


@admin.register(Telemetry)
class TelemetryAdmin(admin.ModelAdmin):
    list_display = ('id', 'smart_bin', 'fill_level', 'weight', 'temperature', 'data_source', 'timestamp')
    list_filter = ('data_source',)
    search_fields = ('smart_bin__bin_id',)
    date_hierarchy = 'timestamp'


@admin.register(EwasteSubmission)
class EwasteSubmissionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'category', 'quantity', 'estimated_weight', 'status', 'created_at')
    list_filter = ('category', 'status')


@admin.register(PickupRequest)
class PickupRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'e_waste_category', 'city', 'status', 'preferred_date', 'created_at')
    list_filter = ('status', 'e_waste_category')


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
    list_display = ('id', 'bin', 'alert_type', 'severity', 'is_active', 'created_at', 'resolved_at')
    list_filter = ('alert_type', 'severity', 'is_active')
    search_fields = ('bin__bin_id', 'message')
