import uuid

from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone


class UUIDTimestampModel(models.Model):
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		abstract = True


class Person(UUIDTimestampModel):
	GENDER_CHOICES = (
		("Male", "Male"),
		("Female", "Female"),
		("Other", "Other"),
	)
	MARITAL_STATUS_CHOICES = (
		("Single", "Single"),
		("Married", "Married"),
		("Widowed", "Widowed"),
		("Divorced", "Divorced"),
	)

	first_name = models.CharField(max_length=100)
	last_name = models.CharField(max_length=100)
	gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
	date_of_birth = models.DateField()
	nationality = models.CharField(max_length=80, blank=True)
	country = models.CharField(max_length=80, blank=True)
	province = models.CharField(max_length=80, blank=True)
	district = models.CharField(max_length=80, blank=True)
	sector = models.CharField(max_length=80, blank=True)
	cell = models.CharField(max_length=80, blank=True)
	village = models.CharField(max_length=80, blank=True)
	phone = models.CharField(max_length=30, blank=True)
	email = models.EmailField(blank=True)
	address = models.TextField(blank=True)
	marital_status = models.CharField(max_length=20, choices=MARITAL_STATUS_CHOICES, default="Single")
	spouse_name = models.CharField(max_length=200, blank=True)
	occupation = models.CharField(max_length=120, blank=True)
	emergency_contact_name = models.CharField(max_length=200, blank=True)
	emergency_contact_phone = models.CharField(max_length=30, blank=True)
	is_member = models.BooleanField(default=False)
	is_child_profile = models.BooleanField(default=False)
	is_visitor = models.BooleanField(default=False)
	first_visit_date = models.DateField(null=True, blank=True)
	visit_count = models.PositiveIntegerField(default=1)
	visitor_notes = models.TextField(blank=True)
	date_joined = models.DateField(null=True, blank=True)
	is_active = models.BooleanField(default=True)

	class Meta:
		ordering = ["last_name", "first_name"]

	def __str__(self):
		return f"{self.first_name} {self.last_name}".strip()


class MemberAccount(UUIDTimestampModel):
	user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="member_account")
	person = models.OneToOneField(Person, on_delete=models.CASCADE, related_name="member_account")
	profile_photo = models.ImageField(upload_to="member_profiles/", blank=True)

	def __str__(self):
		return self.user.username


class AdminProfile(UUIDTimestampModel):
	user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="admin_profile")
	profile_photo = models.ImageField(upload_to="admin_profiles/", blank=True)

	class Meta:
		ordering = ["user__username"]

	def __str__(self):
		return f"Admin Profile - {self.user.username}"


class Officiant(UUIDTimestampModel):
	name = models.CharField(max_length=150, unique=True)
	title = models.CharField(max_length=80, blank=True)
	signature_image = models.ImageField(upload_to="officiant_signatures/", blank=True)
	is_active = models.BooleanField(default=True)

	class Meta:
		ordering = ["name"]

	def __str__(self):
		return f"{self.title} {self.name}".strip()


class SacramentStatus:
	PENDING = "Pending"
	APPROVED = "Approved"
	REJECTED = "Rejected"
	SCHEDULED = "Scheduled"
	COMPLETED = "Completed"
	CANCELLED = "Cancelled"
	MARRIED = "Married"

	CHOICES = (
		(PENDING, PENDING),
		(APPROVED, APPROVED),
		(REJECTED, REJECTED),
		(SCHEDULED, SCHEDULED),
		(COMPLETED, COMPLETED),
		(CANCELLED, CANCELLED),
		(MARRIED, MARRIED),
	)


class ProtectedSacramentModel(UUIDTimestampModel):
	class Meta:
		abstract = True

	def delete(self, *args, **kwargs):
		raise ValidationError("Historical sacramental records cannot be deleted.")


class BlackoutDate(UUIDTimestampModel):
	"""Dates blocked off for sacraments (holidays, maintenance, etc.)"""
	ACTIVITY_BAPTISM = "Baptism"
	ACTIVITY_DEDICATION = "Dedication"
	ACTIVITY_WEDDING = "Wedding"
	ACTIVITY_ALL = "All"

	ACTIVITY_CHOICES = (
		(ACTIVITY_ALL, ACTIVITY_ALL),
		(ACTIVITY_BAPTISM, ACTIVITY_BAPTISM),
		(ACTIVITY_DEDICATION, ACTIVITY_DEDICATION),
		(ACTIVITY_WEDDING, ACTIVITY_WEDDING),
	)

	date = models.DateField()
	reason = models.CharField(max_length=200, blank=True)
	activity_type = models.CharField(max_length=20, choices=ACTIVITY_CHOICES, default=ACTIVITY_ALL)

	class Meta:
		ordering = ["date"]
		unique_together = ["date", "activity_type"]

	def __str__(self):
		prefix = f"[{self.activity_type}] " if self.activity_type != self.ACTIVITY_ALL else ""
		return f"{prefix}{self.date} - {self.reason or 'Blackout'}"


class AvailableSlot(UUIDTimestampModel):
	"""Available date/time slots for sacraments"""
	ACTIVITY_BAPTISM = "Baptism"
	ACTIVITY_DEDICATION = "Dedication"
	ACTIVITY_WEDDING = "Wedding"
	
	ACTIVITY_CHOICES = (
		(ACTIVITY_BAPTISM, ACTIVITY_BAPTISM),
		(ACTIVITY_DEDICATION, ACTIVITY_DEDICATION),
		(ACTIVITY_WEDDING, ACTIVITY_WEDDING),
	)
	
	activity_type = models.CharField(max_length=20, choices=ACTIVITY_CHOICES)
	date = models.DateField()
	time = models.TimeField(null=True, blank=True)  # For weddings: 12:00, 14:00, 16:00
	is_available = models.BooleanField(default=True)
	
	class Meta:
		ordering = ["date", "time"]
		unique_together = ["activity_type", "date", "time"]
	
	def __str__(self):
		if self.time:
			return f"{self.activity_type} - {self.date} at {self.time.strftime('%H:%M')}"
		return f"{self.activity_type} - {self.date}"


class Baptism(ProtectedSacramentModel):
	person = models.OneToOneField(Person, on_delete=models.PROTECT, related_name="baptism")
	available_slot = models.ForeignKey(AvailableSlot, on_delete=models.SET_NULL, null=True, blank=True, related_name="baptisms")
	request_date = models.DateField(default=timezone.localdate)
	status = models.CharField(max_length=20, choices=SacramentStatus.CHOICES, default=SacramentStatus.PENDING)
	baptism_date = models.DateField(null=True, blank=True)
	officiant = models.CharField(max_length=120, blank=True)
	admin_comment = models.TextField(blank=True)
	certificate_generated = models.BooleanField(default=False)

	class Meta:
		ordering = ["-created_at"]

	def __str__(self):
		return f"Baptism - {self.person}"
	
	def save(self, *args, **kwargs):
		# Sync baptism_date from available_slot
		if self.available_slot:
			self.baptism_date = self.available_slot.date
		super().save(*args, **kwargs)


class BabyDedication(ProtectedSacramentModel):
	child = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="child_dedications")
	father = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="father_dedications")
	mother = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="mother_dedications")
	available_slot = models.ForeignKey(AvailableSlot, on_delete=models.SET_NULL, null=True, blank=True, related_name="dedications")
	scripture_reference = models.CharField(max_length=120, blank=True)
	scripture_text = models.TextField(blank=True)
	request_date = models.DateField(default=timezone.localdate)
	status = models.CharField(max_length=20, choices=SacramentStatus.CHOICES, default=SacramentStatus.PENDING)
	dedication_date = models.DateField(null=True, blank=True)
	officiant = models.CharField(max_length=120, blank=True)
	admin_comment = models.TextField(blank=True)
	certificate_generated = models.BooleanField(default=False)

	class Meta:
		ordering = ["-created_at"]

	def __str__(self):
		return f"Dedication - {self.child}"
	
	def save(self, *args, **kwargs):
		# Sync dedication_date from available_slot
		if self.available_slot:
			self.dedication_date = self.available_slot.date
		super().save(*args, **kwargs)


class Wedding(ProtectedSacramentModel):
	"""
	LEGACY MODEL — Kept for backward compatibility with existing data.
	New code should use WeddingRequest + WeddingCeremony instead.
	"""
	RESOLUTION_DIVORCED = "Divorced"
	RESOLUTION_ANNULLED = "Annulled"
	RESOLUTION_CHOICES = (
		(RESOLUTION_DIVORCED, RESOLUTION_DIVORCED),
		(RESOLUTION_ANNULLED, RESOLUTION_ANNULLED),
	)

	groom = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="groom_weddings")
	bride = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="bride_weddings")
	groom_church_name = models.CharField(max_length=200, blank=True)
	bride_church_name = models.CharField(max_length=200, blank=True)
	available_slot = models.ForeignKey(AvailableSlot, on_delete=models.SET_NULL, null=True, blank=True, related_name="weddings")
	wedding_date = models.DateField(null=True, blank=True)
	officiant = models.CharField(max_length=120, blank=True)
	couple_photo = models.ImageField(upload_to="wedding_photos/", blank=True, verbose_name="Couple Photo")
	groom_health_document = models.FileField(upload_to="wedding_health_documents/", blank=True)
	bride_health_document = models.FileField(upload_to="wedding_health_documents/", blank=True)
	status = models.CharField(max_length=20, choices=SacramentStatus.CHOICES, default=SacramentStatus.SCHEDULED)
	marriage_resolution = models.CharField(max_length=20, choices=RESOLUTION_CHOICES, blank=True)
	resolution_date = models.DateField(null=True, blank=True)
	certificate_generated = models.BooleanField(default=False)
	admin_comment = models.TextField(blank=True)
	# Link to new model for migration
	ceremony_link = models.OneToOneField(
		"WeddingCeremony", on_delete=models.SET_NULL, null=True, blank=True,
		related_name="legacy_wedding",
	)

	class Meta:
		ordering = ["-wedding_date"]

	def __str__(self):
		return f"Wedding - {self.groom} & {self.bride}"
	
	def save(self, *args, **kwargs):
		# Sync wedding_date from available_slot
		if self.available_slot:
			self.wedding_date = self.available_slot.date
		super().save(*args, **kwargs)


class WeddingRequest(ProtectedSacramentModel):
	"""
	The application/request submitted by a member.
	Supports dual-consent: the submitter creates the request,
	then the partner confirms via an invite code.
	"""
	submitter = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="submitted_wedding_requests")
	partner = models.ForeignKey(
		Person, on_delete=models.PROTECT, related_name="partner_wedding_requests",
		null=True, blank=True,
	)
	partner_consented = models.BooleanField(default=False)
	partner_consented_at = models.DateTimeField(null=True, blank=True)
	partner_invite_code = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
	partner_is_member = models.BooleanField(default=False)
	partner_non_member_data = models.JSONField(default=dict, blank=True)
	partner_gender_expected = models.CharField(max_length=10, blank=True)
	available_slot = models.ForeignKey(
		AvailableSlot, on_delete=models.SET_NULL, null=True, blank=True, related_name="wedding_requests",
	)
	couple_photo = models.ImageField(upload_to="wedding_photos/", blank=True, verbose_name="Couple Photo")
	submitter_role = models.CharField(max_length=10, choices=[("groom", "Groom"), ("bride", "Bride")])
	submitter_health_document = models.FileField(upload_to="wedding_health_documents/", blank=True)
	partner_health_document = models.FileField(upload_to="wedding_health_documents/", blank=True)
	status = models.CharField(max_length=20, choices=SacramentStatus.CHOICES, default=SacramentStatus.PENDING)
	admin_comment = models.TextField(blank=True)

	VALID_TRANSITIONS = {
		SacramentStatus.PENDING: [SacramentStatus.APPROVED, SacramentStatus.REJECTED, SacramentStatus.CANCELLED],
		SacramentStatus.APPROVED: [SacramentStatus.REJECTED],
		SacramentStatus.REJECTED: [SacramentStatus.PENDING],
		SacramentStatus.CANCELLED: [SacramentStatus.PENDING],
	}

	class Meta:
		ordering = ["-created_at"]

	def __str__(self):
		return f"Wedding Request - {self.submitter} & {self.partner or '(pending partner)'}"

	def transition_to(self, new_status):
		allowed = self.VALID_TRANSITIONS.get(self.status, [])
		if new_status not in allowed:
			raise ValidationError(
				f"Cannot transition WeddingRequest from {self.status} to {new_status}."
			)
		self.status = new_status
		self.save()

	def clean(self):
		super().clean()
		if self.partner and self.partner_id == self.submitter_id:
			raise ValidationError("Submitter and partner must be different people.")

	def delete(self, *args, **kwargs):
		if self.status == SacramentStatus.PENDING:
			from django.db.models import Model as _BaseModel
			_BaseModel.delete(self, *args, **kwargs)
		else:
			raise ValidationError("Historical sacramental records cannot be deleted.")

	def save(self, *args, **kwargs):
		self.full_clean()
		super().save(*args, **kwargs)


class WeddingCeremony(ProtectedSacramentModel):
	"""The actual ceremony record — created when a request is approved and scheduled."""
	RESOLUTION_DIVORCED = "Divorced"
	RESOLUTION_ANNULLED = "Annulled"
	RESOLUTION_CHOICES = (
		(RESOLUTION_DIVORCED, RESOLUTION_DIVORCED),
		(RESOLUTION_ANNULLED, RESOLUTION_ANNULLED),
	)

	wedding_request = models.OneToOneField(
		WeddingRequest, on_delete=models.PROTECT, related_name="ceremony",
		null=True, blank=True,
	)
	groom = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="groom_ceremonies")
	bride = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="bride_ceremonies")
	groom_church_name = models.CharField(max_length=200, blank=True)
	bride_church_name = models.CharField(max_length=200, blank=True)
	available_slot = models.ForeignKey(
		AvailableSlot, on_delete=models.SET_NULL, null=True, blank=True, related_name="ceremonies",
	)
	wedding_date = models.DateField()
	officiant = models.CharField(max_length=120, blank=True)
	officiant_obj = models.ForeignKey(
		Officiant, on_delete=models.SET_NULL, null=True, blank=True,
	)
	witnesses = models.JSONField(default=list, blank=True)
	marriage_resolution = models.CharField(max_length=20, choices=RESOLUTION_CHOICES, blank=True)
	resolution_date = models.DateField(null=True, blank=True)
	certificate_generated = models.BooleanField(default=False)

	class Meta:
		ordering = ["-wedding_date"]

	def __str__(self):
		return f"Wedding Ceremony - {self.groom} & {self.bride}"

	def save(self, *args, **kwargs):
		if self.available_slot:
			self.wedding_date = self.available_slot.date
		super().save(*args, **kwargs)

	def person_has_active_marriage(self, person):
		"""Check if a person has an active (unresolved) marriage."""
		return WeddingCeremony.objects.filter(
			models.Q(groom=person) | models.Q(bride=person),
			marriage_resolution="",
		).exclude(id=self.id if self.pk else None).exists()


class WeddingCertificateExtra(ProtectedSacramentModel):
	"""Extra fields specific to wedding certificates."""
	ceremony = models.OneToOneField(
		WeddingCeremony, on_delete=models.PROTECT, related_name="certificate_extra",
	)
	couple_photo_used = models.ImageField(upload_to="wedding_cert_photos/", blank=True)
	witness_names_display = models.TextField(blank=True)
	gospel_reading = models.CharField(max_length=200, blank=True)
	officiant_title = models.CharField(max_length=120, blank=True)

	class Meta:
		verbose_name = "Wedding Certificate Extra"
		verbose_name_plural = "Wedding Certificate Extras"

	def __str__(self):
		return f"Cert extras - {self.ceremony}"


class Certificate(ProtectedSacramentModel):
	BAPTISM = "Baptism"
	DEDICATION = "Dedication"
	WEDDING = "Wedding"
	SERVICE_CHOICES = ((BAPTISM, BAPTISM), (DEDICATION, DEDICATION), (WEDDING, WEDDING))

	certificate_number = models.CharField(max_length=40, unique=True)
	service_type = models.CharField(max_length=20, choices=SERVICE_CHOICES)
	content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
	object_id = models.UUIDField()
	linked_object = GenericForeignKey("content_type", "object_id")
	issued_date = models.DateField(default=timezone.localdate)
	design_template = models.CharField(max_length=60)
	qr_code_image = models.ImageField(upload_to="qr_codes/", blank=True)
	certificate_file = models.FileField(upload_to="certificates/", blank=True)
	is_valid = models.BooleanField(default=True)
	revoked_reason = models.TextField(blank=True)

	class Meta:
		ordering = ["-issued_date", "-created_at"]

	def save(self, *args, **kwargs):
		if not self.certificate_number:
			self.certificate_number = f"CHR-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
		super().save(*args, **kwargs)

	def __str__(self):
		return self.certificate_number


@receiver(pre_delete, sender=Baptism)
@receiver(pre_delete, sender=BabyDedication)
@receiver(pre_delete, sender=Wedding)
@receiver(pre_delete, sender=WeddingRequest)
@receiver(pre_delete, sender=WeddingCeremony)
@receiver(pre_delete, sender=WeddingCertificateExtra)
@receiver(pre_delete, sender=Certificate)
def prevent_sacrament_delete(sender, instance, **kwargs):
	if sender is WeddingRequest and instance.status == SacramentStatus.PENDING:
		return
	raise ValidationError("Historical sacramental records cannot be deleted.")


class ActivityLog(UUIDTimestampModel):
	CAT_AUTH = "auth"
	CAT_MEMBER = "member"
	CAT_BAPTISM = "baptism"
	CAT_DEDICATION = "dedication"
	CAT_WEDDING = "wedding"
	CAT_CERTIFICATE = "certificate"
	CAT_SYSTEM = "system"

	CATEGORY_CHOICES = [
		(CAT_AUTH, "Login / Auth"),
		(CAT_MEMBER, "Members"),
		(CAT_BAPTISM, "Baptism"),
		(CAT_DEDICATION, "Dedication"),
		(CAT_WEDDING, "Wedding"),
		(CAT_CERTIFICATE, "Certificates"),
		(CAT_SYSTEM, "System"),
	]

	actor = models.ForeignKey(
		User, null=True, blank=True, on_delete=models.SET_NULL, related_name="activity_logs"
	)
	action = models.CharField(max_length=40)
	category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default=CAT_SYSTEM)
	description = models.CharField(max_length=400)
	is_read = models.BooleanField(default=False)

	class Meta:
		ordering = ["-created_at"]

	def __str__(self):
		return self.description


class MemberNotification(UUIDTimestampModel):
	CAT_BAPTISM = "baptism"
	CAT_DEDICATION = "dedication"
	CAT_WEDDING = "wedding"
	CAT_SYSTEM = "system"

	CATEGORY_CHOICES = [
		(CAT_BAPTISM, "Baptism"),
		(CAT_DEDICATION, "Dedication"),
		(CAT_WEDDING, "Wedding"),
		(CAT_SYSTEM, "System"),
	]

	user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="member_notifications")
	category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default=CAT_SYSTEM)
	message = models.CharField(max_length=500)
	is_read = models.BooleanField(default=False)

	class Meta:
		ordering = ["-created_at"]

	def __str__(self):
		return self.message
