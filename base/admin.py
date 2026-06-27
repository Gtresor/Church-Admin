from django.contrib import admin
from django.utils.html import format_html
from .models import AdminProfile, AvailableSlot, BabyDedication, Baptism, BlackoutDate, Certificate, MemberAccount, Officiant, Person, Wedding


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
	list_display = ("first_name", "last_name", "gender", "is_member", "is_active")
	list_filter = ("gender", "is_member", "is_active")
	search_fields = ("first_name", "last_name", "email", "phone")


@admin.register(MemberAccount)
class MemberAccountAdmin(admin.ModelAdmin):
	list_display = ("user", "person", "created_at")
	search_fields = ("user__username", "person__first_name", "person__last_name")


@admin.register(AdminProfile)
class AdminProfileAdmin(admin.ModelAdmin):
	list_display = ("user", "created_at")
	search_fields = ("user__username", "user__email")


@admin.register(Officiant)
class OfficiantAdmin(admin.ModelAdmin):
	list_display = ("name", "title", "is_active")
	list_filter = ("is_active",)
	search_fields = ("name", "title")


@admin.register(BlackoutDate)
class BlackoutDateAdmin(admin.ModelAdmin):
	list_display = ("date", "reason", "activity_type")
	list_filter = ("activity_type", "date")
	search_fields = ("reason",)
	ordering = ("-date",)


@admin.register(AvailableSlot)
class AvailableSlotAdmin(admin.ModelAdmin):
	list_display = ("activity_type", "date", "time", "is_available")
	list_filter = ("activity_type", "date", "is_available")
	search_fields = ("activity_type", "date")
	ordering = ("-date", "time")


@admin.register(Baptism)
class BaptismAdmin(admin.ModelAdmin):
	list_display = ("person", "status", "available_slot", "baptism_date", "certificate_generated")
	list_filter = ("status", "certificate_generated")
	search_fields = ("person__first_name", "person__last_name", "officiant")
	readonly_fields = ("baptism_date",)
	fieldsets = (
		("Personal Details", {"fields": ("person",)}),
		("Scheduling", {"fields": ("available_slot",)}),
		("Status", {"fields": ("status", "baptism_date", "officiant", "admin_comment")}),
		("Certificate", {"fields": ("certificate_generated",)}),
	)


@admin.register(BabyDedication)
class BabyDedicationAdmin(admin.ModelAdmin):
	list_display = ("child", "father", "mother", "status", "available_slot", "dedication_date", "certificate_generated")
	list_filter = ("status", "certificate_generated")
	search_fields = (
		"child__first_name",
		"child__last_name",
		"father__first_name",
		"mother__first_name",
	)
	readonly_fields = ("dedication_date",)
	fieldsets = (
		("People", {"fields": ("child", "father", "mother")}),
		("Scripture", {"fields": ("scripture_reference", "scripture_text")}),
		("Scheduling", {"fields": ("available_slot",)}),
		("Status", {"fields": ("status", "dedication_date", "officiant", "admin_comment")}),
		("Certificate", {"fields": ("certificate_generated",)}),
	)


@admin.register(Wedding)
class WeddingAdmin(admin.ModelAdmin):
	list_display = ("groom", "bride", "status", "available_slot", "wedding_date", "certificate_generated")
	list_filter = ("status", "certificate_generated")
	search_fields = ("groom__first_name", "bride__first_name", "officiant")
	# Removed readonly_fields to make all fields editable
	fieldsets = (
		("People", {"fields": ("groom", "bride")}),
		("Church Names", {"fields": ("groom_church_name", "bride_church_name")}),
		("Scheduling", {"fields": ("available_slot", "wedding_date")}),
		("Status", {"fields": ("status", "officiant", "marriage_resolution", "admin_comment")}),
		("Health Documents", {"fields": ("groom_health_document", "bride_health_document")}),
		("Certificate", {"fields": ("certificate_generated",)}),
	)


@admin.register(Certificate)
class CertificateAdmin(admin.ModelAdmin):
	list_display = ("certificate_number", "service_type", "issued_date", "is_valid")
	list_filter = ("service_type", "is_valid")
	search_fields = ("certificate_number",)
