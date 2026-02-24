from django.contrib import admin
from .models import AdminProfile, BabyDedication, Baptism, Certificate, MemberAccount, Officiant, Person, Wedding


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


@admin.register(Baptism)
class BaptismAdmin(admin.ModelAdmin):
	list_display = ("person", "status", "baptism_date", "certificate_generated")
	list_filter = ("status", "certificate_generated")
	search_fields = ("person__first_name", "person__last_name", "officiant")


@admin.register(BabyDedication)
class BabyDedicationAdmin(admin.ModelAdmin):
	list_display = ("child", "father", "mother", "status", "dedication_date", "certificate_generated")
	list_filter = ("status", "certificate_generated")
	search_fields = (
		"child__first_name",
		"child__last_name",
		"father__first_name",
		"mother__first_name",
	)


@admin.register(Wedding)
class WeddingAdmin(admin.ModelAdmin):
	list_display = ("groom", "bride", "wedding_date", "status", "certificate_generated")
	list_filter = ("status", "certificate_generated")
	search_fields = ("groom__first_name", "bride__first_name", "officiant")


@admin.register(Certificate)
class CertificateAdmin(admin.ModelAdmin):
	list_display = ("certificate_number", "service_type", "issued_date", "is_valid")
	list_filter = ("service_type", "is_valid")
	search_fields = ("certificate_number",)
