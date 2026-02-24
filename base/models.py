import uuid

from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
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

	CHOICES = (
		(PENDING, PENDING),
		(APPROVED, APPROVED),
		(REJECTED, REJECTED),
		(SCHEDULED, SCHEDULED),
		(COMPLETED, COMPLETED),
	)


class ProtectedSacramentModel(UUIDTimestampModel):
	class Meta:
		abstract = True

	def delete(self, *args, **kwargs):
		raise ValidationError("Historical sacramental records cannot be deleted.")


class Baptism(ProtectedSacramentModel):
	person = models.OneToOneField(Person, on_delete=models.PROTECT, related_name="baptism")
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


class BabyDedication(ProtectedSacramentModel):
	child = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="child_dedications")
	father = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="father_dedications")
	mother = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="mother_dedications")
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


class Wedding(ProtectedSacramentModel):
	groom = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="groom_weddings")
	bride = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="bride_weddings")
	wedding_date = models.DateField()
	officiant = models.CharField(max_length=120)
	groom_health_document = models.FileField(upload_to="wedding_health_documents/", blank=True)
	bride_health_document = models.FileField(upload_to="wedding_health_documents/", blank=True)
	status = models.CharField(max_length=20, choices=SacramentStatus.CHOICES, default=SacramentStatus.SCHEDULED)
	certificate_generated = models.BooleanField(default=False)
	admin_comment = models.TextField(blank=True)

	class Meta:
		ordering = ["-wedding_date"]

	def __str__(self):
		return f"Wedding - {self.groom} & {self.bride}"


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
@receiver(pre_delete, sender=Certificate)
def prevent_sacrament_delete(sender, instance, **kwargs):
	raise ValidationError("Historical sacramental records cannot be deleted.")
