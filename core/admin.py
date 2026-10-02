"""Admin registrations — Day 1: everything visible, no custom logic yet."""
from django.contrib import admin

from .models import Alert, Profile
from bins.models import SmartBin, Telemetry
from waste.models import (
    Collection, CollectionTask, DepositSession, EwasteSubmission,
    PickupRequest, RecyclingRecord,
)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'full_name', 'city', 'phone', 'role',
                    'employee_id', 'is_collector_active', 'created_at')
    list_filter = ('role', 'is_collector_active')
    search_fields = ('user__username', 'full_name', 'phone', 'city', 'employee_id')


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
    list_display = ('id', 'user', 'category', 'quantity', 'estimated_weight',
                    'smart_bin', 'submission_method', 'verification_status',
                    'status', 'created_at')
    list_filter = ('category', 'status', 'submission_method',
                   'verification_status')
    search_fields = ('user__username', 'smart_bin__bin_id', 'category')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(DepositSession)
class DepositSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'smart_bin', 'is_completed',
                    'created_at', 'expires_at', 'submission')
    list_filter = ('is_completed',)
    search_fields = ('user__username', 'smart_bin__bin_id', 'token')
    readonly_fields = ('token', 'created_at')


@admin.register(PickupRequest)
class PickupRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'e_waste_category', 'city', 'status', 'preferred_date', 'created_at')
    list_filter = ('status', 'e_waste_category')


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ('id', 'pickup', 'bin', 'status', 'collected_weight', 'created_at')
    list_filter = ('status',)


@admin.register(CollectionTask)
class CollectionTaskAdmin(admin.ModelAdmin):
    list_display = ('id', 'source_label', 'smart_bin', 'pickup_request',
                    'priority', 'status', 'assigned_to',
                    'created_at', 'completed_at')
    list_filter = ('status', 'priority')
    search_fields = ('smart_bin__bin_id', 'pickup_request__id',
                     'assigned_to__username')
    readonly_fields = ('created_at', 'assigned_at', 'started_at',
                       'completed_at', 'updated_at')


@admin.register(RecyclingRecord)
class RecyclingRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'submission', 'collection', 'collection_task',
                    'processing_status', 'received_weight', 'recycling_partner',
                    'created_at')
    list_filter = ('processing_status',)
    search_fields = ('submission__user__username', 'recycling_partner')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ('id', 'bin', 'alert_type', 'severity', 'is_active', 'created_at', 'resolved_at')
    list_filter = ('alert_type', 'severity', 'is_active')
    search_fields = ('bin__bin_id', 'message')
