import calendar
import csv
import json
import re
from datetime import date, datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.db.models import Count, Q
from django.db.models.deletion import ProtectedError
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from . import notifications
from ._log import log, notify_member
from .decorators import member_required, staff_required
from .models import (
	ActivityLog, AdminProfile, AvailableSlot, BabyDedication, Baptism, BlackoutDate,
	Certificate, MemberAccount, MemberNotification, Officiant, Person, SacramentStatus, Wedding,
	WeddingCeremony, WeddingRequest, WeddingCertificateExtra,
)
from .services.certificates import (
	get_design_options,
	generate_baptism_certificate,
	generate_dedication_certificate,
	generate_wedding_certificate,
	render_baptism_preview_pdf,
	render_dedication_preview_pdf,
	render_wedding_preview_pdf,
)
from .services.ai_reports import CHAT_EXAMPLES, answer_system_chat, generate_ai_report


DEDICATION_FIXED_DESIGN_TEMPLATE = "dedication_new_life"
BAPTISM_FIXED_DESIGN_TEMPLATE = "baptism_og"
WEDDING_FIXED_DESIGN_TEMPLATE = "wedding_og"


def home(request):
	if request.user.is_authenticated:
		if request.user.is_staff:
			return redirect("admin_dashboard")
		return redirect("member_dashboard")
	return redirect("login")


def _parse_date(value, field_label):
	if not value:
		return None, f"{field_label} is required."
	try:
		return datetime.strptime(value, "%Y-%m-%d").date(), None
	except ValueError:
		return None, f"{field_label} must be a valid date."


def _calculate_age(date_of_birth):
	if not date_of_birth:
		return None
	today = timezone.localdate()
	age = today.year - date_of_birth.year
	if (today.month, today.day) < (date_of_birth.month, date_of_birth.day):
		age -= 1
	return max(age, 0)


def _validate_phone(phone_value):
	if not phone_value:
		return None
	if not re.fullmatch(r"[\d\s+\-()]{7,20}", phone_value):
		return "Phone must be 7-20 characters and contain only digits or + - ( ) symbols."
	return None


def _validate_email_value(email_value):
	if not email_value:
		return None
	try:
		validate_email(email_value)
	except ValidationError:
		return "Email address is invalid."
	return None


def _empty_member_form_data():
	return {
		"first_name": "",
		"last_name": "",
		"gender": "",
		"date_of_birth": "",
		"phone": "",
		"email": "",
		"address": "",
		"nationality": "",
		"country": "",
		"province": "",
		"district": "",
		"cell": "",
		"village": "",
		"marital_status": "Single",
		"spouse_name": "",
		"occupation": "",
		"emergency_contact_name": "",
		"emergency_contact_phone": "",
		"username": "",
	}


def _member_form_data_from_post(post_data):
	form_data = _empty_member_form_data()
	if post_data:
		form_data.update({key: value for key, value in post_data.items()})
	return form_data


def _validate_health_document(uploaded_file, role_label):
	if not uploaded_file:
		return f"{role_label} health document is required."
	allowed_types = {
		"application/pdf",
		"image/png",
		"image/jpeg",
		"image/jpg",
	}
	content_type = getattr(uploaded_file, "content_type", "")
	if content_type not in allowed_types:
		return f"{role_label} health document must be PDF, PNG, or JPG."
	if uploaded_file.size > 5 * 1024 * 1024:
		return f"{role_label} health document must be 5MB or smaller."
	return None


def _query_without_page(request):
	params = request.GET.copy()
	params.pop("page", None)
	return params.urlencode()


def _selected_int_ids(request, key="selected_ids"):
	values = request.POST.getlist(key)
	result = []
	for value in values:
		try:
			result.append(int(value))
		except (TypeError, ValueError):
			continue
	return result


def _delete_or_deactivate_member(person):
	member_account = getattr(person, "member_account", None)
	linked_user = member_account.user if member_account else None

	try:
		person.delete()
		if linked_user:
			linked_user.delete()
		return "deleted"
	except (ProtectedError, ValidationError):
		person.is_member = False
		person.is_active = False
		person.save(update_fields=["is_member", "is_active", "updated_at"])
		if linked_user:
			linked_user.is_active = False
			linked_user.save(update_fields=["is_active"])
		return "deactivated"


def login_view(request):
	if request.method == "POST":
		username = request.POST.get("username", "").strip()
		password = request.POST.get("password", "")
		if not username or not password:
			messages.error(request, "Username and password are required.")
			return render(request, "auth/login.html", {"login_error": True, "entered_username": username})

		user = authenticate(request, username=username, password=password)
		if user is None:
			messages.error(request, "Invalid credentials.")
			return render(request, "auth/login.html", {"login_error": True, "entered_username": username})

		login(request, user)
		if user.is_staff:
			AdminProfile.objects.get_or_create(user=user)
			return redirect("admin_dashboard")
		return redirect("member_dashboard")
	return render(request, "auth/login.html")


def member_register_view(request):
	if request.user.is_authenticated:
		if request.user.is_staff:
			return redirect("admin_dashboard")
		return redirect("member_dashboard")

	if request.method == "POST":
		first_name = request.POST.get("first_name", "").strip()
		last_name = request.POST.get("last_name", "").strip()
		date_of_birth_raw = request.POST.get("date_of_birth", "").strip()
		email = request.POST.get("email", "").strip()
		phone = request.POST.get("phone", "").strip()
		nationality = request.POST.get("nationality", "").strip()
		country = request.POST.get("country", "").strip()
		province = request.POST.get("province", "").strip()
		district = request.POST.get("district", "").strip()
		cell = request.POST.get("cell", "").strip()
		village = request.POST.get("village", "").strip()
		marital_status = request.POST.get("marital_status", "Single").strip() or "Single"
		spouse_name = request.POST.get("spouse_name", "").strip()
		occupation = request.POST.get("occupation", "").strip()
		emergency_contact_name = request.POST.get("emergency_contact_name", "").strip()
		emergency_contact_phone = request.POST.get("emergency_contact_phone", "").strip()
		username = request.POST.get("username", "").strip()
		password = request.POST.get("password", "")
		confirm_password = request.POST.get("confirm_password", "")

		date_of_birth, dob_error = _parse_date(date_of_birth_raw, "Date of birth")
		email_error = _validate_email_value(email)
		phone_error = _validate_phone(phone)
		emergency_phone_error = _validate_phone(emergency_contact_phone)

		if not first_name or not last_name or dob_error or not username:
			messages.error(request, dob_error or "First name, last name, date of birth, and username are required.")
			return render(request, "auth/member_register.html", {"form_data": request.POST})
		if not email and not phone:
			messages.error(request, "Provide at least your email or phone number for member verification.")
			return render(request, "auth/member_register.html", {"form_data": request.POST})
		if email_error or phone_error:
			messages.error(request, email_error or phone_error)
			return render(request, "auth/member_register.html", {"form_data": request.POST})
		if emergency_phone_error:
			messages.error(request, emergency_phone_error.replace("Phone", "Emergency contact phone"))
			return render(request, "auth/member_register.html", {"form_data": request.POST})
		if marital_status not in {"Single", "Married", "Widowed", "Divorced"}:
			messages.error(request, "Select a valid marital status.")
			return render(request, "auth/member_register.html", {"form_data": request.POST})
		if marital_status == "Married" and not spouse_name:
			messages.error(request, "Spouse name is required when marital status is married.")
			return render(request, "auth/member_register.html", {"form_data": request.POST})
		if len(password) < 8:
			messages.error(request, "Password must be at least 8 characters.")
			return render(request, "auth/member_register.html", {"form_data": request.POST})
		if password != confirm_password:
			messages.error(request, "Password confirmation does not match.")
			return render(request, "auth/member_register.html", {"form_data": request.POST})
		if User.objects.filter(username=username).exists():
			messages.error(request, "Username is already taken.")
			return render(request, "auth/member_register.html", {"form_data": request.POST})

		candidates = Person.objects.filter(
			is_member=True,
			is_active=True,
			first_name__iexact=first_name,
			last_name__iexact=last_name,
			date_of_birth=date_of_birth,
		)
		if email:
			candidates = candidates.filter(email__iexact=email)
		if phone:
			candidates = candidates.filter(phone=phone)

		match_count = candidates.count()
		if match_count == 0:
			messages.error(request, "No active church member record matches your details. Contact admin for assistance.")
			return render(request, "auth/member_register.html", {"form_data": request.POST})
		if match_count > 1:
			messages.error(request, "Multiple member records matched. Please contact admin to complete account setup.")
			return render(request, "auth/member_register.html", {"form_data": request.POST})

		person = candidates.first()
		if hasattr(person, "member_account"):
			messages.error(request, "A login account already exists for this member. Please sign in.")
			return redirect("login")

		person.nationality = nationality
		person.country = country
		person.province = province
		person.district = district
		person.cell = cell
		person.village = village
		person.marital_status = marital_status
		person.spouse_name = spouse_name if marital_status == "Married" else ""
		person.occupation = occupation
		person.emergency_contact_name = emergency_contact_name
		person.emergency_contact_phone = emergency_contact_phone
		person.save(
			update_fields=[
				"nationality",
				"country",
				"province",
				"district",
				"cell",
				"village",
				"marital_status",
				"spouse_name",
				"occupation",
				"emergency_contact_name",
				"emergency_contact_phone",
				"updated_at",
			]
		)

		user = User.objects.create_user(
			username=username,
			password=password,
			email=email or person.email,
			first_name=person.first_name,
			last_name=person.last_name,
		)
		MemberAccount.objects.create(user=user, person=person)
		notifications.send_welcome(person, username=user.username)
		log(user, "create", ActivityLog.CAT_MEMBER, f"{person.first_name} {person.last_name} created a member account.")
		login(request, user)
		messages.success(request, "Account created successfully. Welcome to your member portal.")
		return redirect("member_dashboard")

	return render(request, "auth/member_register.html")


@login_required
def logout_view(request):
	logout(request)
	return redirect("login")


@login_required
@staff_required
def admin_profile(request):
	user = request.user
	profile, _ = AdminProfile.objects.get_or_create(user=user)

	if request.method == "POST":
		action = request.POST.get("action", "profile")
		if action == "password":
			current_password = request.POST.get("current_password", "")
			new_password = request.POST.get("new_password", "")
			confirm_password = request.POST.get("confirm_password", "")

			if not current_password or not new_password or not confirm_password:
				messages.error(request, "All password fields are required.")
				return redirect("admin_profile")
			if not user.check_password(current_password):
				messages.error(request, "Current password is incorrect.")
				return redirect("admin_profile")
			if len(new_password) < 8:
				messages.error(request, "New password must be at least 8 characters.")
				return redirect("admin_profile")
			if new_password != confirm_password:
				messages.error(request, "New password and confirmation do not match.")
				return redirect("admin_profile")
			if current_password == new_password:
				messages.error(request, "New password must be different from current password.")
				return redirect("admin_profile")

			user.set_password(new_password)
			user.save(update_fields=["password"])
			update_session_auth_hash(request, user)
			messages.success(request, "Password updated successfully.")
			return redirect("admin_profile")

		username = request.POST.get("username", "").strip()
		first_name = request.POST.get("first_name", "").strip()
		last_name = request.POST.get("last_name", "").strip()
		email = request.POST.get("email", "").strip()
		remove_photo = request.POST.get("remove_photo") == "on"
		uploaded_photo = request.FILES.get("profile_photo")

		if not username:
			messages.error(request, "Username is required.")
			return render(request, "admin/profile.html", {"profile": profile})
		if User.objects.filter(username=username).exclude(id=user.id).exists():
			messages.error(request, "Username is already taken.")
			return render(request, "admin/profile.html", {"profile": profile})

		email_error = _validate_email_value(email)
		if email_error:
			messages.error(request, email_error)
			return render(request, "admin/profile.html", {"profile": profile})

		if uploaded_photo:
			if not getattr(uploaded_photo, "content_type", "").startswith("image/"):
				messages.error(request, "Profile picture must be an image file.")
				return render(request, "admin/profile.html", {"profile": profile})
			if uploaded_photo.size > 5 * 1024 * 1024:
				messages.error(request, "Profile picture must be 5MB or smaller.")
				return render(request, "admin/profile.html", {"profile": profile})

		user.username = username
		user.first_name = first_name
		user.last_name = last_name
		user.email = email
		user.save(update_fields=["username", "first_name", "last_name", "email"])

		if remove_photo and profile.profile_photo:
			profile.profile_photo.delete(save=False)
			profile.profile_photo = ""
		if uploaded_photo:
			if profile.profile_photo:
				profile.profile_photo.delete(save=False)
			profile.profile_photo = uploaded_photo
		profile.save()

		messages.success(request, "Admin profile updated.")
		return redirect("admin_profile")

	return render(request, "admin/profile.html", {"profile": profile})


@method_decorator([login_required, staff_required], name="dispatch")
class PersonListView(TemplateView):
    template_name = "admin/person_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        q = self.request.GET.get("q", "").strip()
        person_type = self.request.GET.get("type", "all")

        qs = Person.objects.select_related("member_account").all()
        if q:
            qs = qs.filter(
                Q(first_name__icontains=q) | Q(last_name__icontains=q) |
                Q(phone__icontains=q) | Q(email__icontains=q)
            )
        if person_type == "member":
            qs = qs.filter(is_member=True)
        elif person_type == "visitor":
            qs = qs.filter(is_visitor=True)
        elif person_type == "kid":
            qs = qs.filter(is_child_profile=True)
        elif person_type == "other":
            qs = qs.filter(is_member=False, is_visitor=False, is_child_profile=False)
        else:
            person_type = "all"

        paginator = Paginator(qs.order_by("first_name", "last_name"), 25)
        base = Person.objects.all()
        counts = {
            "all": base.count(),
            "member": base.filter(is_member=True).count(),
            "visitor": base.filter(is_visitor=True).count(),
            "kid": base.filter(is_child_profile=True).count(),
            "other": base.filter(is_member=False, is_visitor=False, is_child_profile=False).count(),
        }
        context["page_obj"] = paginator.get_page(self.request.GET.get("page"))
        context["q"] = q
        context["person_type"] = person_type
        context["counts"] = counts
        return context


@login_required
@staff_required
def admin_user_list(request):
	query = request.GET.get("q", "").strip()
	status = request.GET.get("status", "all").strip().lower()
	role = request.GET.get("role", "all").strip().lower()
	member_link = request.GET.get("member_link", "all").strip().lower()
	users = User.objects.select_related("member_account", "admin_profile").all().order_by("username")
	if query:
		users = users.filter(
			Q(username__icontains=query)
			| Q(email__icontains=query)
			| Q(first_name__icontains=query)
			| Q(last_name__icontains=query)
		)

	if status == "active":
		users = users.filter(is_active=True)
	elif status == "inactive":
		users = users.filter(is_active=False)

	if role == "superuser":
		users = users.filter(is_superuser=True)
	elif role == "staff":
		users = users.filter(is_staff=True, is_superuser=False)
	elif role == "member":
		users = users.filter(is_staff=False)

	if member_link == "linked":
		users = users.filter(member_account__isnull=False)
	elif member_link == "unlinked":
		users = users.filter(member_account__isnull=True)

	paginator = Paginator(users, 12)
	return render(
		request,
		"admin/user_list.html",
		{
			"page_obj": paginator.get_page(request.GET.get("page")),
			"q": query,
			"status": status,
			"role": role,
			"member_link": member_link,
			"page_query": _query_without_page(request),
		},
	)


@login_required
@staff_required
def admin_user_bulk_action(request):
	if request.method != "POST":
		raise Http404

	action = request.POST.get("bulk_action", "").strip().lower()
	selected_ids = _selected_int_ids(request)
	if not selected_ids:
		messages.error(request, "Select at least one user for bulk action.")
		return redirect("admin_user_list")

	users = User.objects.filter(id__in=selected_ids)
	if not users.exists():
		messages.error(request, "No valid users selected.")
		return redirect("admin_user_list")

	if action == "activate":
		updated_count = 0
		for user in users:
			if not user.is_active:
				user.is_active = True
				user.save(update_fields=["is_active"])
				member_account = getattr(user, "member_account", None)
				if member_account and member_account.person:
					member_account.person.is_active = True
					member_account.person.save(update_fields=["is_active", "updated_at"])
				updated_count += 1
		messages.success(request, f"{updated_count} user(s) activated.")
		return redirect("admin_user_list")

	if action == "deactivate":
		updated_count = 0
		skipped_self = 0
		for user in users:
			if user.id == request.user.id:
				skipped_self += 1
				continue
			if user.is_active:
				user.is_active = False
				user.save(update_fields=["is_active"])
				member_account = getattr(user, "member_account", None)
				if member_account and member_account.person:
					member_account.person.is_active = False
					member_account.person.save(update_fields=["is_active", "updated_at"])
				updated_count += 1
		if skipped_self:
			messages.warning(request, "Your own account was skipped for safety.")
		messages.success(request, f"{updated_count} user(s) deactivated.")
		return redirect("admin_user_list")

	if action == "delete":
		deleted_count = 0
		skipped_self = 0
		for user in users:
			if user.id == request.user.id:
				skipped_self += 1
				continue
			user.delete()
			deleted_count += 1
		if skipped_self:
			messages.warning(request, "Your own account was skipped for safety.")
		messages.success(request, f"{deleted_count} user(s) deleted.")
		return redirect("admin_user_list")

	if action == "export_excel":
		response = HttpResponse(content_type="application/vnd.ms-excel")
		response["Content-Disposition"] = 'attachment; filename="users_export.xls"'
		writer = csv.writer(response, delimiter="\t")
		writer.writerow(["Username", "First Name", "Last Name", "Email", "Role", "Status", "Linked Member"])
		for user in users.order_by("username"):
			role_label = "Superuser" if user.is_superuser else ("Staff" if user.is_staff else "Member")
			status_label = "Active" if user.is_active else "Inactive"
			member_account = getattr(user, "member_account", None)
			linked_member = str(member_account.person) if member_account and member_account.person else "-"
			writer.writerow([user.username, user.first_name, user.last_name, user.email, role_label, status_label, linked_member])
		return response

	if action == "export_pdf":
		response = HttpResponse(content_type="application/pdf")
		response["Content-Disposition"] = 'attachment; filename="users_export.pdf"'
		pdf = canvas.Canvas(response, pagesize=A4)
		width, height = A4
		y = height - 40
		pdf.setFont("Helvetica-Bold", 13)
		pdf.drawString(40, y, "Users Export")
		y -= 18
		pdf.setFont("Helvetica", 9)
		pdf.drawString(40, y, f"Generated On: {timezone.localdate().isoformat()}")
		y -= 18
		pdf.setFont("Helvetica-Bold", 9)
		pdf.drawString(40, y, "Username")
		pdf.drawString(150, y, "Role")
		pdf.drawString(220, y, "Status")
		pdf.drawString(290, y, "Email")
		y -= 12
		pdf.line(40, y, width - 40, y)
		y -= 12
		pdf.setFont("Helvetica", 8)
		for user in users.order_by("username"):
			if y < 50:
				pdf.showPage()
				y = height - 40
				pdf.setFont("Helvetica", 8)
			role_label = "Superuser" if user.is_superuser else ("Staff" if user.is_staff else "Member")
			status_label = "Active" if user.is_active else "Inactive"
			email = user.email or "-"
			if len(email) > 38:
				email = f"{email[:35]}..."
			pdf.drawString(40, y, user.username)
			pdf.drawString(150, y, role_label)
			pdf.drawString(220, y, status_label)
			pdf.drawString(290, y, email)
			y -= 11
		pdf.save()
		return response

	messages.error(request, "Select a valid bulk action.")
	return redirect("admin_user_list")


@login_required
@staff_required
def admin_user_edit(request, user_id):
	target_user = get_object_or_404(User, id=user_id)
	can_manage_roles = request.user.is_superuser
	linked_member = getattr(target_user, "member_account", None)
	member_person = linked_member.person if linked_member else None

	if request.method == "POST":
		action = request.POST.get("action", "account")

		if action == "account":
			username = request.POST.get("username", "").strip()
			email = request.POST.get("email", "").strip()
			new_password = request.POST.get("new_password", "")
			is_active = request.POST.get("is_active") == "on"
			is_staff = request.POST.get("is_staff") == "on" if can_manage_roles else target_user.is_staff
			is_superuser = request.POST.get("is_superuser") == "on" if can_manage_roles else target_user.is_superuser

			if not username:
				messages.error(request, "Username is required.")
				return redirect("admin_user_edit", user_id=target_user.id)
			if User.objects.filter(username=username).exclude(id=target_user.id).exists():
				messages.error(request, "Username is already taken.")
				return redirect("admin_user_edit", user_id=target_user.id)
			email_error = _validate_email_value(email)
			if email_error:
				messages.error(request, email_error)
				return redirect("admin_user_edit", user_id=target_user.id)
			if new_password and len(new_password) < 8:
				messages.error(request, "Password must be at least 8 characters.")
				return redirect("admin_user_edit", user_id=target_user.id)

			if target_user.id == request.user.id:
				if not is_active:
					messages.error(request, "You cannot deactivate your own account.")
					return redirect("admin_user_edit", user_id=target_user.id)
				if request.user.is_superuser and not is_superuser:
					messages.error(request, "You cannot remove your own superuser rights.")
					return redirect("admin_user_edit", user_id=target_user.id)

			target_user.username = username
			target_user.email = email
			target_user.is_active = is_active
			target_user.is_staff = is_staff
			target_user.is_superuser = is_superuser
			target_user.save(update_fields=["username", "email", "is_active", "is_staff", "is_superuser"])

			if new_password:
				target_user.set_password(new_password)
				target_user.save(update_fields=["password"])
				if target_user.id == request.user.id:
					update_session_auth_hash(request, target_user)
				messages.success(request, "Account details and password updated.")
			else:
				messages.success(request, "Account details updated.")
			return redirect("admin_user_edit", user_id=target_user.id)

		if action == "personal":
			first_name = request.POST.get("first_name", "").strip()
			last_name = request.POST.get("last_name", "").strip()
			if not first_name or not last_name:
				messages.error(request, "First and last name are required.")
				return redirect("admin_user_edit", user_id=target_user.id)

			if member_person:
				gender = request.POST.get("gender", "").strip()
				dob_raw = request.POST.get("date_of_birth", "").strip()
				dob_value, dob_error = _parse_date(dob_raw, "Date of birth")
				if not gender or dob_error:
					messages.error(request, dob_error or "Gender and date of birth are required.")
					return redirect("admin_user_edit", user_id=target_user.id)
				if dob_value and dob_value > timezone.localdate():
					messages.error(request, "Date of birth cannot be in the future.")
					return redirect("admin_user_edit", user_id=target_user.id)

				member_person.first_name = first_name
				member_person.last_name = last_name
				member_person.gender = gender
				member_person.date_of_birth = dob_value
				member_person.save(update_fields=["first_name", "last_name", "gender", "date_of_birth", "updated_at"])
			else:
				target_user.first_name = first_name
				target_user.last_name = last_name
				target_user.save(update_fields=["first_name", "last_name"])

			if target_user.first_name != first_name or target_user.last_name != last_name:
				target_user.first_name = first_name
				target_user.last_name = last_name
				target_user.save(update_fields=["first_name", "last_name"])

			messages.success(request, "Personal profile updated.")
			return redirect("admin_user_edit", user_id=target_user.id)

		if action == "contact":
			email = request.POST.get("email", "").strip()
			phone = request.POST.get("phone", "").strip()
			address = request.POST.get("address", "").strip()
			email_error = _validate_email_value(email)
			phone_error = _validate_phone(phone)
			if email_error or phone_error:
				messages.error(request, email_error or phone_error)
				return redirect("admin_user_edit", user_id=target_user.id)

			target_user.email = email
			target_user.save(update_fields=["email"])

			if member_person:
				member_person.email = email
				member_person.phone = phone
				member_person.address = address
				member_person.save(update_fields=["email", "phone", "address", "updated_at"])

			messages.success(request, "Contact information updated.")
			return redirect("admin_user_edit", user_id=target_user.id)

		messages.error(request, "Invalid action.")
		return redirect("admin_user_edit", user_id=target_user.id)

	baptism_record = Baptism.objects.filter(person=member_person).first() if member_person else None
	dedication_requests_count = (
		BabyDedication.objects.filter(Q(father=member_person) | Q(mother=member_person)).count() if member_person else 0
	)
	wedding_count = Wedding.objects.filter(Q(groom=member_person) | Q(bride=member_person)).count() if member_person else 0
	certificate_count = _member_certificates(member_person).count() if member_person else 0
	return render(
		request,
		"admin/user_edit.html",
		{
			"target_user": target_user,
			"linked_member": linked_member,
			"member_person": member_person,
			"baptism_record": baptism_record,
			"dedication_requests_count": dedication_requests_count,
			"wedding_count": wedding_count,
			"certificate_count": certificate_count,
			"gender_choices": Person.GENDER_CHOICES,
			"can_manage_roles": can_manage_roles,
		},
	)


@login_required
@staff_required
def admin_user_toggle_active(request, user_id):
	if request.method != "POST":
		raise Http404

	target_user = get_object_or_404(User, id=user_id)
	if target_user.id == request.user.id:
		messages.error(request, "You cannot deactivate your own account.")
		return redirect("admin_user_list")

	target_user.is_active = not target_user.is_active
	target_user.save(update_fields=["is_active"])

	member_account = getattr(target_user, "member_account", None)
	if member_account and member_account.person:
		member_account.person.is_active = target_user.is_active
		member_account.person.save(update_fields=["is_active", "updated_at"])

	if target_user.is_active:
		messages.success(request, f"User '{target_user.username}' has been activated.")
	else:
		messages.warning(request, f"User '{target_user.username}' has been deactivated.")

	return redirect("admin_user_list")


@method_decorator([login_required, staff_required], name="dispatch")
class AdminDashboardView(TemplateView):
	template_name = "admin/dashboard.html"

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		today = timezone.localdate()
		month_start = today.replace(day=1)

		# ── Stat cards ────────────────────────────────────────────────────────
		context["total_members"] = Person.objects.filter(is_member=True).count()
		context["pending_baptisms"] = Baptism.objects.filter(status=SacramentStatus.PENDING).count()
		context["pending_dedications"] = BabyDedication.objects.filter(status=SacramentStatus.PENDING).count()
		context["pending_weddings"] = Wedding.objects.filter(
			status__in=[SacramentStatus.PENDING, SacramentStatus.APPROVED]
		).count()
		context["total_weddings"] = Wedding.objects.count()
		context["certificates_issued"] = Certificate.objects.count()
		context["new_members_this_month"] = Person.objects.filter(
			is_member=True, date_joined__gte=month_start
		).count()
		context["active_officiants"] = Officiant.objects.filter(is_active=True).count()
		context["new_visitors_this_month"] = Person.objects.filter(
			is_visitor=True, first_visit_date__gte=month_start
		).count()
		context["total_visitors"] = Person.objects.filter(is_visitor=True).count()

		# ── Upcoming services (with days_away) ────────────────────────────────
		upcoming_services = []
		for item in Baptism.objects.select_related("person").filter(baptism_date__gte=today).order_by("baptism_date")[:10]:
			upcoming_services.append({
				"service": "Baptism",
				"name": str(item.person),
				"date": item.baptism_date,
				"days_away": (item.baptism_date - today).days,
				"url": reverse("admin_baptism_review", kwargs={"baptism_id": item.id}),
			})
		for item in BabyDedication.objects.select_related("child").filter(dedication_date__gte=today).order_by("dedication_date")[:10]:
			upcoming_services.append({
				"service": "Dedication",
				"name": str(item.child),
				"date": item.dedication_date,
				"days_away": (item.dedication_date - today).days,
				"url": reverse("admin_dedication_review", kwargs={"dedication_id": item.id}),
			})
		for item in Wedding.objects.select_related("groom", "bride").filter(wedding_date__gte=today).exclude(marriage_resolution=Wedding.RESOLUTION_ANNULLED).order_by("wedding_date")[:10]:
			upcoming_services.append({
				"service": "Wedding",
				"name": f"{item.groom} & {item.bride}",
				"date": item.wedding_date,
				"days_away": (item.wedding_date - today).days,
				"url": reverse("admin_wedding_review", kwargs={"wedding_id": item.id}),
			})
		context["upcoming_services"] = sorted(upcoming_services, key=lambda v: v["date"])[:8]

		# ── Pending actions (unified, sorted oldest-first) ────────────────────
		pending_actions = []
		for b in Baptism.objects.filter(status=SacramentStatus.PENDING).select_related("person").order_by("created_at")[:5]:
			pending_actions.append({
				"service": "Baptism",
				"name": str(b.person),
				"status": b.status,
				"age": (today - b.created_at.date()).days,
				"url": reverse("admin_baptism_review", kwargs={"baptism_id": b.id}),
			})
		for d in BabyDedication.objects.filter(status=SacramentStatus.PENDING).select_related("child").order_by("created_at")[:5]:
			pending_actions.append({
				"service": "Dedication",
				"name": str(d.child),
				"status": d.status,
				"age": (today - d.created_at.date()).days,
				"url": reverse("admin_dedication_review", kwargs={"dedication_id": d.id}),
			})
		for w in Wedding.objects.filter(
			status__in=[SacramentStatus.PENDING, SacramentStatus.APPROVED]
		).select_related("groom", "bride").order_by("created_at")[:5]:
			pending_actions.append({
				"service": "Wedding",
				"name": f"{w.groom} & {w.bride}",
				"status": w.status,
				"age": (today - w.created_at.date()).days,
				"url": reverse("admin_wedding_review", kwargs={"wedding_id": w.id}),
			})
		context["pending_actions"] = sorted(pending_actions, key=lambda x: x["age"], reverse=True)[:10]

		# ── 6-month activity chart data ───────────────────────────────────────
		chart_labels, chart_baptisms, chart_dedications, chart_weddings = [], [], [], []
		for offset in range(5, -1, -1):
			mo = today.month - offset
			yr = today.year
			if mo <= 0:
				mo += 12
				yr -= 1
			chart_labels.append(calendar.month_abbr[mo])
			chart_baptisms.append(Baptism.objects.filter(created_at__year=yr, created_at__month=mo).count())
			chart_dedications.append(BabyDedication.objects.filter(created_at__year=yr, created_at__month=mo).count())
			chart_weddings.append(Wedding.objects.filter(created_at__year=yr, created_at__month=mo).count())
		context["chart_labels"] = json.dumps(chart_labels)
		context["chart_baptisms"] = json.dumps(chart_baptisms)
		context["chart_dedications"] = json.dumps(chart_dedications)
		context["chart_weddings"] = json.dumps(chart_weddings)

		_seven_days_ago = timezone.now() - timedelta(days=7)
		context["recent_certificates"] = (
			Certificate.objects
			.filter(created_at__gte=_seven_days_ago)
			.order_by("-issued_date", "-created_at")[:5]
		)
		return context


@method_decorator([login_required, member_required], name="dispatch")
class MemberDashboardView(TemplateView):
	template_name = "member/dashboard.html"

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		member = self.request.user.member_account
		context["baptism"] = Baptism.objects.filter(person=member.person).first()
		context["dedications"] = BabyDedication.objects.filter(
			Q(father=member.person) | Q(mother=member.person)
		).order_by("-created_at")
		context["wedding_requests"] = WeddingRequest.objects.filter(
			submitter=member.person
		).order_by("-created_at")
		context["certificates"] = _member_certificates(member.person)
		context["recent_certificates"] = _member_certificates(member.person)[:5]
		context["pending_requests"] = Baptism.objects.filter(
			person=member.person, status__in=[SacramentStatus.PENDING, SacramentStatus.APPROVED, SacramentStatus.SCHEDULED]
		).count() + BabyDedication.objects.filter(
			Q(father=member.person) | Q(mother=member.person),
			status__in=[SacramentStatus.PENDING, SacramentStatus.APPROVED, SacramentStatus.SCHEDULED],
		).count() + WeddingRequest.objects.filter(
			submitter=member.person,
			status__in=[SacramentStatus.PENDING, SacramentStatus.APPROVED],
		).count()
		return context


@method_decorator([login_required, staff_required], name="dispatch")
class MemberListView(TemplateView):
	template_name = "admin/member_list.html"

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		query = self.request.GET.get("q", "").strip()
		status = self.request.GET.get("status", "all").strip().lower()
		members = Person.objects.select_related("member_account").filter(is_member=True)
		if query:
			members = members.filter(
				Q(first_name__icontains=query)
				| Q(last_name__icontains=query)
				| Q(email__icontains=query)
				| Q(phone__icontains=query)
			)
		if status == "active":
			members = members.filter(is_active=True)
		elif status == "inactive":
			members = members.filter(is_active=False)
		paginator = Paginator(members, 10)
		context["page_obj"] = paginator.get_page(self.request.GET.get("page"))
		context["q"] = query
		context["status"] = status
		context["page_query"] = _query_without_page(self.request)
		return context


@method_decorator([login_required, staff_required], name="dispatch")
class VisitorListView(TemplateView):
    template_name = "admin/visitor_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        q = self.request.GET.get("q", "").strip()
        visitors = Person.objects.filter(is_visitor=True).order_by("-first_visit_date", "-created_at")
        if q:
            visitors = visitors.filter(
                Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(phone__icontains=q)
                | Q(email__icontains=q)
            )
        paginator = Paginator(visitors, 25)
        page_number = self.request.GET.get("page")
        page_obj = paginator.get_page(page_number)
        context.update({"page_obj": page_obj, "q": q, "page_query": f"q={q}&"})
        return context


@login_required
@staff_required
def visitor_register(request):
    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        phone = request.POST.get("phone", "").strip()
        gender = request.POST.get("gender", "")
        dob_raw = request.POST.get("date_of_birth", "").strip()
        email = request.POST.get("email", "").strip()
        address = request.POST.get("address", "").strip()
        visitor_notes = request.POST.get("visitor_notes", "").strip()

        errors = []
        if not first_name:
            errors.append("First name is required.")
        if not last_name:
            errors.append("Last name is required.")
        if not phone:
            errors.append("Phone number is required.")

        dob = None
        if dob_raw:
            try:
                dob = date.fromisoformat(dob_raw)
            except ValueError:
                errors.append("Invalid date of birth format.")

        if not errors:
            Person.objects.create(
                first_name=first_name,
                last_name=last_name,
                gender=gender or "Other",
                date_of_birth=dob or date(2000, 1, 1),
                phone=phone,
                email=email,
                address=address,
                is_visitor=True,
                first_visit_date=date.today(),
                visit_count=1,
                visitor_notes=visitor_notes,
                is_active=True,
            )
            return redirect(reverse("admin_visitor_list") + "?registered=1")

        return render(request, "admin/visitor_register.html", {
            "errors": errors,
            "post": request.POST,
        })

    return render(request, "admin/visitor_register.html", {})


@login_required
@staff_required
def visitor_checkin(request, person_id):
    if request.method != "POST":
        return redirect("admin_visitor_list")
    visitor = get_object_or_404(Person, id=person_id, is_visitor=True)
    visitor.visit_count += 1
    visitor.save(update_fields=["visit_count", "updated_at"])
    return redirect(request.POST.get("next", reverse("admin_visitor_list")))


@login_required
@staff_required
def visitor_convert_to_member(request, person_id):
    if request.method != "POST":
        return redirect("admin_visitor_list")
    person = get_object_or_404(Person, id=person_id, is_visitor=True)
    base_username = f"{person.first_name.lower()}.{person.last_name.lower()}".replace(" ", "")
    username = base_username
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f"{base_username}{counter}"
        counter += 1
    temp_password = User.objects.make_random_password(length=12)
    user = User.objects.create_user(
        username=username,
        password=temp_password,
        email=person.email or "",
        first_name=person.first_name,
        last_name=person.last_name,
    )
    person.is_visitor = False
    person.is_member = True
    person.date_joined = date.today()
    person.save(update_fields=["is_visitor", "is_member", "date_joined", "updated_at"])
    MemberAccount.objects.create(user=user, person=person)
    notifications.send_welcome(person, username=user.username, temp_password=temp_password)
    log(request.user, "update", ActivityLog.CAT_MEMBER, f"{person.first_name} {person.last_name} converted from visitor to member.")
    return redirect(reverse("admin_member_edit", args=[person.id]))


@method_decorator([login_required, staff_required], name="dispatch")
class KidsListView(TemplateView):
	template_name = "admin/kid_list.html"

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		query = self.request.GET.get("q", "").strip()
		status = self.request.GET.get("status", "all").strip().lower()
		kids = Person.objects.filter(is_child_profile=True).order_by("last_name", "first_name")
		if query:
			kids = kids.filter(
				Q(first_name__icontains=query)
				| Q(last_name__icontains=query)
				| Q(email__icontains=query)
				| Q(phone__icontains=query)
			)
		if status == "active":
			kids = kids.filter(is_active=True)
		elif status == "inactive":
			kids = kids.filter(is_active=False)
		paginator = Paginator(kids, 10)
		context["page_obj"] = paginator.get_page(self.request.GET.get("page"))
		context["q"] = query
		context["status"] = status
		context["page_query"] = _query_without_page(self.request)
		context["today"] = timezone.localdate()
		return context


@login_required
@staff_required
def kid_create(request):
	if request.method == "POST":
		first_name = request.POST.get("first_name", "").strip()
		last_name = request.POST.get("last_name", "").strip()
		gender = request.POST.get("gender", "").strip()
		date_of_birth, dob_error = _parse_date(request.POST.get("date_of_birth", ""), "Date of birth")
		phone = request.POST.get("phone", "").strip()
		email = request.POST.get("email", "").strip()
		address = request.POST.get("address", "").strip()
		email_error = _validate_email_value(email)
		phone_error = _validate_phone(phone)

		if not first_name or not last_name or not gender or dob_error:
			messages.error(request, dob_error or "First name, last name, gender, and date of birth are required.")
			return render(request, "admin/kid_form.html")
		if date_of_birth and date_of_birth > timezone.localdate():
			messages.error(request, "Date of birth cannot be in the future.")
			return render(request, "admin/kid_form.html")
		if email_error or phone_error:
			messages.error(request, email_error or phone_error)
			return render(request, "admin/kid_form.html")

		Person.objects.create(
			first_name=first_name,
			last_name=last_name,
			gender=gender,
			date_of_birth=date_of_birth,
			phone=phone,
			email=email,
			address=address,
			is_member=False,
			is_child_profile=True,
			is_active=True,
		)
		messages.success(request, "Kid profile created successfully.")
		return redirect("admin_kid_list")
	return render(request, "admin/kid_form.html")


@login_required
@staff_required
def kid_edit(request, person_id):
	person = get_object_or_404(Person, id=person_id, is_child_profile=True)
	if request.method == "POST":
		first_name = request.POST.get("first_name", "").strip()
		last_name = request.POST.get("last_name", "").strip()
		gender = request.POST.get("gender", "").strip()
		date_of_birth, dob_error = _parse_date(request.POST.get("date_of_birth", ""), "Date of birth")
		email = request.POST.get("email", "").strip()
		phone = request.POST.get("phone", "").strip()
		email_error = _validate_email_value(email)
		phone_error = _validate_phone(phone)

		if not first_name or not last_name or not gender or dob_error:
			messages.error(request, dob_error or "Required fields are missing.")
			return render(request, "admin/kid_form.html", {"person": person})
		if date_of_birth and date_of_birth > timezone.localdate():
			messages.error(request, "Date of birth cannot be in the future.")
			return render(request, "admin/kid_form.html", {"person": person})
		if email_error or phone_error:
			messages.error(request, email_error or phone_error)
			return render(request, "admin/kid_form.html", {"person": person})

		person.first_name = first_name
		person.last_name = last_name
		person.gender = gender
		person.date_of_birth = date_of_birth
		person.phone = phone
		person.email = email
		person.address = request.POST.get("address", "").strip()
		person.is_active = request.POST.get("is_active") == "on"
		person.is_child_profile = True
		person.save()
		messages.success(request, "Kid profile updated.")
		return redirect("admin_kid_list")
	return render(request, "admin/kid_form.html", {"person": person})


@login_required
@staff_required
def kid_delete(request, person_id):
	if request.method != "POST":
		raise Http404

	person = get_object_or_404(Person, id=person_id, is_child_profile=True)
	try:
		person.delete()
		messages.success(request, "Kid profile deleted.")
	except (ProtectedError, ValidationError):
		person.is_active = False
		person.save(update_fields=["is_active", "updated_at"])
		messages.warning(request, "Kid profile has sacramental references and cannot be deleted. Profile was deactivated instead.")

	return redirect("admin_kid_list")


@login_required
@staff_required
def member_create(request):
	base_context = {
		"person": _empty_member_form_data(),
		"form_data": _empty_member_form_data(),
		"marital_status_choices": Person.MARITAL_STATUS_CHOICES,
		"is_edit": False,
	}
	if request.method == "POST":
		form_data = _member_form_data_from_post(request.POST)
		first_name = request.POST.get("first_name", "").strip()
		last_name = request.POST.get("last_name", "").strip()
		gender = request.POST.get("gender", "").strip()
		date_of_birth, dob_error = _parse_date(request.POST.get("date_of_birth", ""), "Date of birth")
		phone = request.POST.get("phone", "").strip()
		email = request.POST.get("email", "").strip()
		address = request.POST.get("address", "").strip()
		nationality = request.POST.get("nationality", "").strip()
		country = request.POST.get("country", "").strip()
		province = request.POST.get("province", "").strip()
		district = request.POST.get("district", "").strip()
		cell = request.POST.get("cell", "").strip()
		village = request.POST.get("village", "").strip()
		marital_status = request.POST.get("marital_status", "Single").strip() or "Single"
		spouse_name = request.POST.get("spouse_name", "").strip()
		occupation = request.POST.get("occupation", "").strip()
		emergency_contact_name = request.POST.get("emergency_contact_name", "").strip()
		emergency_contact_phone = request.POST.get("emergency_contact_phone", "").strip()
		username = request.POST.get("username", "").strip()
		password = request.POST.get("password", "")
		email_error = _validate_email_value(email)
		phone_error = _validate_phone(phone)
		emergency_phone_error = _validate_phone(emergency_contact_phone)

		if date_of_birth and date_of_birth > timezone.localdate():
			messages.error(request, "Date of birth cannot be in the future.")
			return render(request, "admin/member_form.html", {**base_context, "form_data": form_data})
		if not first_name or not last_name or not gender or dob_error or not username or len(password) < 8:
			messages.error(request, dob_error or "Fill all required fields and use a password with at least 8 characters.")
			return render(request, "admin/member_form.html", {**base_context, "form_data": form_data})
		if email_error or phone_error:
			messages.error(request, email_error or phone_error)
			return render(request, "admin/member_form.html", {**base_context, "form_data": form_data})
		if emergency_phone_error:
			messages.error(request, emergency_phone_error.replace("Phone", "Emergency contact phone"))
			return render(request, "admin/member_form.html", {**base_context, "form_data": form_data})
		if marital_status not in {"Single", "Married", "Widowed", "Divorced"}:
			messages.error(request, "Select a valid marital status.")
			return render(request, "admin/member_form.html", {**base_context, "form_data": form_data})
		if marital_status == "Married" and not spouse_name:
			messages.error(request, "Spouse name is required when marital status is married.")
			return render(request, "admin/member_form.html", {**base_context, "form_data": form_data})
		if User.objects.filter(username=username).exists():
			messages.error(request, "Username already exists.")
			return render(request, "admin/member_form.html", {**base_context, "form_data": form_data})

		person = Person.objects.create(
			first_name=first_name,
			last_name=last_name,
			gender=gender,
			date_of_birth=date_of_birth,
			phone=phone,
			email=email,
			address=address,
			nationality=nationality,
			country=country,
			province=province,
			district=district,
			cell=cell,
			village=village,
			marital_status=marital_status,
			spouse_name=spouse_name if marital_status == "Married" else "",
			occupation=occupation,
			emergency_contact_name=emergency_contact_name,
			emergency_contact_phone=emergency_contact_phone,
			is_member=True,
			date_joined=timezone.localdate(),
			is_active=True,
		)
		user = User.objects.create_user(username=username, password=password, email=email)
		MemberAccount.objects.create(user=user, person=person)
		notifications.send_welcome(person, username=username, temp_password=password)
		log(request.user, "create", ActivityLog.CAT_MEMBER, f"Admin created member account for {person.first_name} {person.last_name}.")
		messages.success(request, "Member created successfully.")
		return redirect("admin_member_list")
	return render(request, "admin/member_form.html", base_context)


@login_required
@staff_required
def member_edit(request, person_id):
	person = get_object_or_404(Person, id=person_id, is_member=True)
	base_context = {
		"person": person,
		"form_data": _empty_member_form_data(),
		"marital_status_choices": Person.MARITAL_STATUS_CHOICES,
		"is_edit": True,
	}
	if request.method == "POST":
		form_data = _member_form_data_from_post(request.POST)
		first_name = request.POST.get("first_name", "").strip()
		last_name = request.POST.get("last_name", "").strip()
		gender = request.POST.get("gender", "").strip()
		date_of_birth, dob_error = _parse_date(request.POST.get("date_of_birth", ""), "Date of birth")
		email = request.POST.get("email", "").strip()
		phone = request.POST.get("phone", "").strip()
		nationality = request.POST.get("nationality", "").strip()
		country = request.POST.get("country", "").strip()
		province = request.POST.get("province", "").strip()
		district = request.POST.get("district", "").strip()
		cell = request.POST.get("cell", "").strip()
		village = request.POST.get("village", "").strip()
		marital_status = request.POST.get("marital_status", "Single").strip() or "Single"
		spouse_name = request.POST.get("spouse_name", "").strip()
		occupation = request.POST.get("occupation", "").strip()
		emergency_contact_name = request.POST.get("emergency_contact_name", "").strip()
		emergency_contact_phone = request.POST.get("emergency_contact_phone", "").strip()
		email_error = _validate_email_value(email)
		phone_error = _validate_phone(phone)
		emergency_phone_error = _validate_phone(emergency_contact_phone)
		if not first_name or not last_name or not gender or dob_error:
			messages.error(request, dob_error or "Required fields are missing.")
			return render(request, "admin/member_form.html", {**base_context, "form_data": form_data})
		if date_of_birth and date_of_birth > timezone.localdate():
			messages.error(request, "Date of birth cannot be in the future.")
			return render(request, "admin/member_form.html", {**base_context, "form_data": form_data})
		if email_error or phone_error:
			messages.error(request, email_error or phone_error)
			return render(request, "admin/member_form.html", {**base_context, "form_data": form_data})
		if emergency_phone_error:
			messages.error(request, emergency_phone_error.replace("Phone", "Emergency contact phone"))
			return render(request, "admin/member_form.html", {**base_context, "form_data": form_data})
		if marital_status not in {"Single", "Married", "Widowed", "Divorced"}:
			messages.error(request, "Select a valid marital status.")
			return render(request, "admin/member_form.html", {**base_context, "form_data": form_data})
		if marital_status == "Married" and not spouse_name:
			messages.error(request, "Spouse name is required when marital status is married.")
			return render(request, "admin/member_form.html", {**base_context, "form_data": form_data})
		person.first_name = first_name
		person.last_name = last_name
		person.gender = gender
		person.date_of_birth = date_of_birth
		person.phone = phone
		person.email = email
		person.address = request.POST.get("address", "").strip()
		person.nationality = nationality
		person.country = country
		person.province = province
		person.district = district
		person.cell = cell
		person.village = village
		person.marital_status = marital_status
		person.spouse_name = spouse_name if marital_status == "Married" else ""
		person.occupation = occupation
		person.emergency_contact_name = emergency_contact_name
		person.emergency_contact_phone = emergency_contact_phone
		person.is_active = request.POST.get("is_active") == "on"
		person.save()
		messages.success(request, "Member updated.")
		return redirect("admin_member_list")
	return render(request, "admin/member_form.html", base_context)


@login_required
@staff_required
def admin_person_detail(request, person_id):
    person = get_object_or_404(
        Person.objects.prefetch_related(
            "father_dedications__child",
            "mother_dedications__child",
            "groom_weddings__bride",
            "bride_weddings__groom",
            "child_dedications",
        ).select_related("member_account"),
        id=person_id,
    )
    try:
        baptism = person.baptism
    except Exception:
        baptism = Baptism.objects.filter(person=person).first()
    profile_photo = None
    if hasattr(person, "member_account") and person.member_account and person.member_account.profile_photo:
        profile_photo = person.member_account.profile_photo
    return render(request, "admin/person_detail.html", {
        "person": person,
        "baptism": baptism,
        "profile_photo": profile_photo,
    })


@login_required
@staff_required
def admin_person_edit(request, person_id):
	person = get_object_or_404(Person, id=person_id)

	if request.method == "POST":
		first_name = request.POST.get("first_name", "").strip()
		last_name = request.POST.get("last_name", "").strip()
		gender = request.POST.get("gender", "").strip()
		date_of_birth, dob_error = _parse_date(request.POST.get("date_of_birth", ""), "Date of birth")
		email = request.POST.get("email", "").strip()
		phone = request.POST.get("phone", "").strip()
		address = request.POST.get("address", "").strip()
		email_error = _validate_email_value(email)
		phone_error = _validate_phone(phone)

		if not first_name or not last_name or not gender or dob_error:
			messages.error(request, dob_error or "First name, last name, gender and date of birth are required.")
			return render(request, "admin/person_edit.html", {"person": person})

		if date_of_birth and date_of_birth > timezone.localdate():
			messages.error(request, "Date of birth cannot be in the future.")
			return render(request, "admin/person_edit.html", {"person": person})

		if email_error or phone_error:
			messages.error(request, email_error or phone_error)
			return render(request, "admin/person_edit.html", {"person": person})

		person.first_name = first_name
		person.last_name = last_name
		person.gender = gender
		person.date_of_birth = date_of_birth
		person.email = email
		person.phone = phone
		person.address = address
		person.save(update_fields=["first_name", "last_name", "gender", "date_of_birth", "email", "phone", "address", "updated_at"])

		log(request.user, "update", ActivityLog.CAT_MEMBER, f"Profile updated for {person.first_name} {person.last_name}.")
		messages.success(request, f"Profile for {person} updated successfully.")
		referrer = request.POST.get("referrer", "")
		if referrer:
			return redirect(referrer)
		return redirect("admin_member_list")

	return render(request, "admin/person_edit.html", {"person": person})


@login_required
@staff_required
def member_delete(request, person_id):
	if request.method != "POST":
		raise Http404

	person = get_object_or_404(Person, id=person_id, is_member=True)
	result = _delete_or_deactivate_member(person)
	if result == "deleted":
		messages.success(request, "Member deleted.")
	else:
		messages.warning(request, "Member has sacramental references and cannot be deleted. Member was deactivated instead.")

	return redirect("admin_member_list")


@login_required
@staff_required
def admin_member_bulk_action(request):
	if request.method != "POST":
		raise Http404

	action = request.POST.get("bulk_action", "").strip().lower()
	selected_ids = request.POST.getlist("selected_ids")
	if not selected_ids:
		messages.error(request, "Select at least one member for bulk action.")
		return redirect("admin_member_list")

	members = Person.objects.select_related("member_account").filter(id__in=selected_ids, is_member=True)
	if not members.exists():
		messages.error(request, "No valid members selected.")
		return redirect("admin_member_list")

	if action == "activate":
		count = 0
		for person in members:
			if not person.is_active:
				person.is_active = True
				person.save(update_fields=["is_active", "updated_at"])
				member_account = getattr(person, "member_account", None)
				if member_account and member_account.user:
					member_account.user.is_active = True
					member_account.user.save(update_fields=["is_active"])
				count += 1
		messages.success(request, f"{count} member(s) activated.")
		return redirect("admin_member_list")

	if action == "deactivate":
		count = 0
		for person in members:
			if person.is_active:
				person.is_active = False
				person.save(update_fields=["is_active", "updated_at"])
				member_account = getattr(person, "member_account", None)
				if member_account and member_account.user:
					member_account.user.is_active = False
					member_account.user.save(update_fields=["is_active"])
				count += 1
		messages.success(request, f"{count} member(s) deactivated.")
		return redirect("admin_member_list")

	if action == "delete":
		deleted_count = 0
		deactivated_count = 0
		for person in members:
			result = _delete_or_deactivate_member(person)
			if result == "deleted":
				deleted_count += 1
			else:
				deactivated_count += 1
		messages.success(request, f"{deleted_count} member(s) deleted.")
		if deactivated_count:
			messages.warning(request, f"{deactivated_count} member(s) had sacramental history and were deactivated instead.")
		return redirect("admin_member_list")

	if action == "export_excel":
		response = HttpResponse(content_type="application/vnd.ms-excel")
		response["Content-Disposition"] = 'attachment; filename="members_export.xls"'
		writer = csv.writer(response, delimiter="\t")
		writer.writerow(["Name", "Email", "Phone", "Status", "Linked Username"])
		for person in members.order_by("last_name", "first_name"):
			member_account = getattr(person, "member_account", None)
			linked_username = member_account.user.username if member_account and member_account.user else "-"
			writer.writerow([str(person), person.email, person.phone, "Active" if person.is_active else "Inactive", linked_username])
		return response

	if action == "export_pdf":
		response = HttpResponse(content_type="application/pdf")
		response["Content-Disposition"] = 'attachment; filename="members_export.pdf"'
		pdf = canvas.Canvas(response, pagesize=A4)
		width, height = A4
		y = height - 40
		pdf.setFont("Helvetica-Bold", 13)
		pdf.drawString(40, y, "Members Export")
		y -= 18
		pdf.setFont("Helvetica", 9)
		pdf.drawString(40, y, f"Generated On: {timezone.localdate().isoformat()}")
		y -= 18
		pdf.setFont("Helvetica-Bold", 9)
		pdf.drawString(40, y, "Name")
		pdf.drawString(200, y, "Status")
		pdf.drawString(260, y, "Email")
		y -= 12
		pdf.line(40, y, width - 40, y)
		y -= 12
		pdf.setFont("Helvetica", 8)
		for person in members.order_by("last_name", "first_name"):
			if y < 50:
				pdf.showPage()
				y = height - 40
				pdf.setFont("Helvetica", 8)
			email = person.email or "-"
			if len(email) > 48:
				email = f"{email[:45]}..."
			pdf.drawString(40, y, str(person))
			pdf.drawString(200, y, "Active" if person.is_active else "Inactive")
			pdf.drawString(260, y, email)
			y -= 11
		pdf.save()
		return response

	messages.error(request, "Select a valid bulk action.")
	return redirect("admin_member_list")


@method_decorator([login_required, staff_required], name="dispatch")
class BaptismListView(TemplateView):
	template_name = "admin/baptism_list.html"

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		query = self.request.GET.get("q", "").strip()
		status = self.request.GET.get("status", "")
		sort = self.request.GET.get("sort", "person")
		dir = self.request.GET.get("dir", "asc")
		baptisms = Baptism.objects.select_related("person").all()
		if query:
			baptisms = baptisms.filter(Q(person__first_name__icontains=query) | Q(person__last_name__icontains=query))
		if status:
			baptisms = baptisms.filter(status=status)
		sort_map = {
			"person": "person__first_name",
			"status": "status",
			"date": "baptism_date",
			"officiant": "officiant",
		}
		order_field = sort_map.get(sort, "person__first_name")
		if dir == "desc":
			order_field = f"-{order_field}"
		baptisms = baptisms.order_by(order_field)
		paginator = Paginator(baptisms, 10)
		context["page_obj"] = paginator.get_page(self.request.GET.get("page"))
		context["q"] = query
		context["status"] = status
		context["sort"] = sort
		context["dir"] = dir
		context["status_choices"] = SacramentStatus.CHOICES
		context["page_query"] = _query_without_page(self.request)
		return context


@login_required
@staff_required
def admin_baptism_create(request):
	people = Person.objects.filter(is_active=True).order_by("last_name", "first_name")

	def _resolve_existing_person(person_id):
		if not person_id:
			return None
		try:
			return Person.objects.get(id=person_id)
		except (ValueError, Person.DoesNotExist):
			return None

	def _create_person_from_manual_form():
		first_name = request.POST.get("first_name", "").strip()
		last_name = request.POST.get("last_name", "").strip()
		gender = request.POST.get("gender", "").strip()
		dob_raw = request.POST.get("date_of_birth", "")
		phone = request.POST.get("phone", "").strip()
		email = request.POST.get("email", "").strip()
		address = request.POST.get("address", "").strip()

		if not first_name and not last_name and not gender and not dob_raw:
			return None, "Select an existing person or provide full manual details."

		dob, dob_error = _parse_date(dob_raw, "Date of birth")
		if not first_name or not last_name or not gender or dob_error:
			return None, dob_error or "First name, last name, gender, and date of birth are required."
		if dob > timezone.localdate():
			return None, "Date of birth cannot be in the future."

		email_error = _validate_email_value(email)
		phone_error = _validate_phone(phone)
		if email_error or phone_error:
			return None, email_error or phone_error

		person = Person.objects.create(
			first_name=first_name,
			last_name=last_name,
			gender=gender,
			date_of_birth=dob,
			phone=phone,
			email=email,
			address=address,
			is_member=False,
			is_active=True,
		)
		return person, None

	if request.method == "POST":
		selected_person_id = request.POST.get("person_id", "").strip()
		person = _resolve_existing_person(selected_person_id)

		if person is None:
			person, person_error = _create_person_from_manual_form()
			if person_error:
				messages.error(request, person_error)
				return render(request, "admin/baptism_form.html", {"people": people})

		if Baptism.objects.filter(person=person).exists():
			messages.error(request, f"{person} already has a baptism record.")
			return render(request, "admin/baptism_form.html", {"people": people})

		admin_comment = request.POST.get("admin_comment", "").strip()
		Baptism.objects.create(
			person=person,
			status=SacramentStatus.PENDING,
			admin_comment=admin_comment,
		)
		messages.success(request, "Baptism registration created successfully.")
		return redirect("admin_baptism_list")

	return render(request, "admin/baptism_form.html", {"people": people})


@login_required
@staff_required
def admin_baptism_review(request, baptism_id):
	baptism = get_object_or_404(Baptism.objects.select_related("person"), id=baptism_id)
	officiants = _active_officiants()
	baptism_slots = AvailableSlot.objects.filter(activity_type=AvailableSlot.ACTIVITY_BAPTISM, is_available=True).order_by("date")
	if request.method == "POST":
		action = request.POST.get("action")
		comment = request.POST.get("admin_comment", "").strip()
		officiant_obj = _resolve_selected_officiant(request.POST.get("officiant_id", "").strip())
		slot_id = request.POST.get("available_slot", "").strip()

		if action == "approve":
			if baptism.status != SacramentStatus.PENDING:
				messages.error(request, "Only pending requests can be approved.")
				return redirect("admin_baptism_review", baptism_id=baptism.id)
			baptism.status = SacramentStatus.APPROVED

		elif action == "reject":
			if baptism.status != SacramentStatus.PENDING:
				messages.error(request, "Only pending requests can be rejected.")
				return redirect("admin_baptism_review", baptism_id=baptism.id)
			if not comment:
				messages.error(request, "Rejection reason is required.")
				return redirect("admin_baptism_review", baptism_id=baptism.id)
			baptism.status = SacramentStatus.REJECTED

		elif action == "cancel":
			if not comment:
				messages.error(request, "Provide a reason or instruction when cancelling a request.")
				return redirect("admin_baptism_review", baptism_id=baptism.id)
			# Release slot if previously assigned
			if baptism.available_slot:
				baptism.available_slot.is_available = True
				baptism.available_slot.save(update_fields=["is_available"])
				baptism.available_slot = None
			baptism.status = SacramentStatus.CANCELLED

		elif action == "schedule":
			if baptism.status != SacramentStatus.APPROVED:
				messages.error(request, "Only approved requests can be scheduled.")
				return redirect("admin_baptism_review", baptism_id=baptism.id)
			if not slot_id:
				messages.error(request, "Select an available baptism slot.")
				return redirect("admin_baptism_review", baptism_id=baptism.id)
			try:
				selected_slot = AvailableSlot.objects.get(id=slot_id, activity_type=AvailableSlot.ACTIVITY_BAPTISM, is_available=True)
			except (ValueError, AvailableSlot.DoesNotExist):
				messages.error(request, "Invalid or already taken slot selected.")
				return redirect("admin_baptism_review", baptism_id=baptism.id)
			if not officiant_obj:
				messages.error(request, "Select an officiant from the officiants database.")
				return redirect("admin_baptism_review", baptism_id=baptism.id)
			# Mark slot as taken
			selected_slot.is_available = False
			selected_slot.save(update_fields=["is_available"])
			baptism.available_slot = selected_slot
			baptism.baptism_date = selected_slot.date
			baptism.officiant = str(officiant_obj)
			baptism.status = SacramentStatus.SCHEDULED

		elif action == "complete":
			if baptism.status != SacramentStatus.SCHEDULED:
				messages.error(request, "Only scheduled requests can be marked completed.")
				return redirect("admin_baptism_review", baptism_id=baptism.id)
			baptism.status = SacramentStatus.COMPLETED

		else:
			messages.error(request, "Invalid action.")
			return redirect("admin_baptism_review", baptism_id=baptism.id)
		if comment:
			baptism.admin_comment = comment
		baptism.save()
		notifications.send_baptism_status(baptism, action)
		_bdate = baptism.baptism_date.strftime("%d %B %Y") if baptism.baptism_date else "a date to be confirmed"
		_bmsg = {
			"approve": "Your baptism request has been approved.",
			"reject": f"Your baptism request was not approved.{' ' + baptism.admin_comment if baptism.admin_comment else ''}",
			"cancel": "Your baptism request has been cancelled.",
			"schedule": f"Your baptism has been scheduled for {_bdate}.",
			"complete": "Your baptism has been marked as completed.",
		}.get(action, "Your baptism status has been updated.")
		notify_member(baptism.person, MemberNotification.CAT_BAPTISM, _bmsg)
		log(request.user, action, ActivityLog.CAT_BAPTISM, f"Baptism for {baptism.person.first_name} {baptism.person.last_name} marked {action}.")
		messages.success(request, "Baptism request updated.")
		return redirect("admin_baptism_review", baptism_id=baptism.id)
	latest_certificate = (
		Certificate.objects.filter(
			service_type=Certificate.BAPTISM,
			object_id=baptism.id,
		)
		.exclude(certificate_file="")
		.order_by("-issued_date", "-created_at")
		.first()
	)
	return render(
		request,
		"admin/baptism_review.html",
		{
			"item": baptism,
			"officiants": officiants,
			"baptism_slots": baptism_slots,
			"latest_certificate": latest_certificate,
		},
	)


@login_required
@staff_required
def admin_generate_baptism_certificate(request, baptism_id):
	baptism = get_object_or_404(Baptism, id=baptism_id)
	if request.method != "POST":
		raise Http404
	if baptism.status not in {SacramentStatus.SCHEDULED, SacramentStatus.COMPLETED}:
		messages.error(request, "Certificates can only be generated for scheduled or completed baptisms.")
		return redirect("admin_baptism_review", baptism_id=baptism.id)
	if not baptism.baptism_date:
		messages.error(request, "Set baptism date before generating certificate.")
		return redirect("admin_baptism_review", baptism_id=baptism.id)
	generate_baptism_certificate(baptism, design_template=BAPTISM_FIXED_DESIGN_TEMPLATE)
	log(request.user, "generate", ActivityLog.CAT_CERTIFICATE, f"Baptism certificate generated for {baptism.person.first_name} {baptism.person.last_name}.")
	messages.success(request, "Baptism certificate generated.")
	return redirect("admin_baptism_review", baptism_id=baptism.id)


@login_required
@staff_required
def admin_preview_baptism_certificate(request, baptism_id):
	baptism = get_object_or_404(Baptism, id=baptism_id)
	if request.method != "POST":
		raise Http404
	pdf_data = render_baptism_preview_pdf(baptism, design_template=BAPTISM_FIXED_DESIGN_TEMPLATE)
	response = HttpResponse(pdf_data, content_type="application/pdf")
	response["Content-Disposition"] = f'inline; filename="baptism-preview-{baptism.id}.pdf"'
	return response


@login_required
@staff_required
def admin_baptism_cancel(request, baptism_id):
	if request.method != "POST":
		raise Http404
	baptism = get_object_or_404(Baptism, id=baptism_id)
	if baptism.available_slot:
		baptism.available_slot.is_available = True
		baptism.available_slot.save(update_fields=["is_available"])
		baptism.available_slot = None
	baptism.status = SacramentStatus.CANCELLED
	baptism.save(update_fields=["status", "available_slot", "updated_at"])
	messages.success(request, f"Baptism for {baptism.person} has been cancelled.")
	return redirect("admin_baptism_list")


@login_required
@staff_required
def admin_dedication_cancel(request, dedication_id):
	if request.method != "POST":
		raise Http404
	dedication = get_object_or_404(BabyDedication, id=dedication_id)
	if dedication.available_slot:
		dedication.available_slot.is_available = True
		dedication.available_slot.save(update_fields=["is_available"])
		dedication.available_slot = None
	dedication.status = SacramentStatus.CANCELLED
	dedication.save(update_fields=["status", "available_slot", "updated_at"])
	messages.success(request, f"Dedication for {dedication.child} has been cancelled.")
	return redirect("admin_dedication_list")


@login_required
@staff_required
def admin_wedding_cancel(request, wedding_id):
	if request.method != "POST":
		raise Http404
	wedding = get_object_or_404(Wedding, id=wedding_id)
	if wedding.available_slot:
		wedding.available_slot.is_available = True
		wedding.available_slot.save(update_fields=["is_available"])
		wedding.available_slot = None
	wedding.status = SacramentStatus.CANCELLED
	wedding.save(update_fields=["status", "available_slot", "updated_at"])
	messages.success(request, f"Wedding for {wedding.groom} & {wedding.bride} has been cancelled.")
	return redirect("admin_wedding_list")


@method_decorator([login_required, staff_required], name="dispatch")
class DedicationListView(TemplateView):
	template_name = "admin/dedication_list.html"

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		query = self.request.GET.get("q", "").strip()
		sort = self.request.GET.get("sort", "child")
		dir = self.request.GET.get("dir", "asc")
		dedications = BabyDedication.objects.select_related("child", "father", "mother")
		if query:
			dedications = dedications.filter(
				Q(child__first_name__icontains=query) | Q(child__last_name__icontains=query) |
				Q(father__first_name__icontains=query) | Q(father__last_name__icontains=query) |
				Q(mother__first_name__icontains=query) | Q(mother__last_name__icontains=query)
			)
		sort_map = {
			"child": "child__first_name",
			"father": "father__first_name",
			"mother": "mother__first_name",
			"status": "status",
			"date": "dedication_date",
		}
		order_field = sort_map.get(sort, "child__first_name")
		if dir == "desc":
			order_field = f"-{order_field}"
		dedications = dedications.order_by(order_field)
		paginator = Paginator(dedications, 10)
		context["page_obj"] = paginator.get_page(self.request.GET.get("page"))
		context["q"] = query
		context["sort"] = sort
		context["dir"] = dir
		context["page_query"] = _query_without_page(self.request)
		return context


@login_required
@staff_required
def admin_dedication_review(request, dedication_id):
	dedication = get_object_or_404(BabyDedication.objects.select_related("child", "father", "mother"), id=dedication_id)
	officiants = _active_officiants()
	parent_choices = Person.objects.filter(is_child_profile=False, is_active=True).order_by("last_name", "first_name")
	latest_certificate = (
		Certificate.objects.filter(
			service_type=Certificate.DEDICATION,
			object_id=dedication.id,
		)
		.exclude(certificate_file="")
		.order_by("-issued_date", "-created_at")
		.first()
	)
	if request.method == "POST":
		action = request.POST.get("action")
		comment = request.POST.get("admin_comment", "").strip()
		officiant_obj = _resolve_selected_officiant(request.POST.get("officiant_id", "").strip())
		service_date_raw = request.POST.get("service_date", "")
		if action == "update_child":
			first_name = request.POST.get("child_first_name", "").strip()
			last_name = request.POST.get("child_last_name", "").strip()
			gender = request.POST.get("child_gender", "").strip()
			dob, dob_error = _parse_date(request.POST.get("child_date_of_birth", ""), "Child date of birth")

			if not first_name or not last_name or not gender or dob_error:
				messages.error(request, dob_error or "Child first name, last name, gender, and date of birth are required.")
				return redirect("admin_dedication_review", dedication_id=dedication.id)
			if dob > timezone.localdate():
				messages.error(request, "Child date of birth cannot be in the future.")
				return redirect("admin_dedication_review", dedication_id=dedication.id)

			dedication.child.first_name = first_name
			dedication.child.last_name = last_name
			dedication.child.gender = gender
			dedication.child.date_of_birth = dob
			dedication.child.is_child_profile = True
			dedication.child.save(update_fields=["first_name", "last_name", "gender", "date_of_birth", "is_child_profile", "updated_at"])
			messages.success(request, "Child details updated.")
			return redirect("admin_dedication_review", dedication_id=dedication.id)
		elif action == "update_request":
			request_date, request_date_error = _parse_date(request.POST.get("request_date", ""), "Request date")
			scripture_reference = request.POST.get("scripture_reference", "").strip()
			scripture_text = request.POST.get("scripture_text", "").strip()

			if request_date_error:
				messages.error(request, request_date_error)
				return redirect("admin_dedication_review", dedication_id=dedication.id)
			if request_date > timezone.localdate():
				messages.error(request, "Request date cannot be in the future.")
				return redirect("admin_dedication_review", dedication_id=dedication.id)
			if not scripture_reference or not scripture_text:
				messages.error(request, "Scripture reference and verse are required.")
				return redirect("admin_dedication_review", dedication_id=dedication.id)

			dedication.request_date = request_date
			dedication.scripture_reference = scripture_reference
			dedication.scripture_text = scripture_text
			dedication.admin_comment = request.POST.get("request_admin_comment", "").strip()
			dedication.save(update_fields=["request_date", "scripture_reference", "scripture_text", "admin_comment", "updated_at"])
			messages.success(request, "Request details updated.")
			return redirect("admin_dedication_review", dedication_id=dedication.id)
		elif action == "update_family":
			father_id = request.POST.get("father_id", "").strip()
			mother_id = request.POST.get("mother_id", "").strip()
			father_obj = Person.objects.filter(id=father_id).first() if father_id else None
			mother_obj = Person.objects.filter(id=mother_id).first() if mother_id else None

			if not father_obj or not mother_obj:
				messages.error(request, "Select both father and mother from the database.")
				return redirect("admin_dedication_review", dedication_id=dedication.id)
			if father_obj.id == mother_obj.id:
				messages.error(request, "Father and mother must be different records.")
				return redirect("admin_dedication_review", dedication_id=dedication.id)

			dedication.father = father_obj
			dedication.mother = mother_obj
			dedication.save(update_fields=["father", "mother", "updated_at"])
			messages.success(request, "Family details updated.")
			return redirect("admin_dedication_review", dedication_id=dedication.id)
		elif action == "approve":
			if dedication.status != SacramentStatus.PENDING:
				messages.error(request, "Only pending requests can be approved.")
				return redirect("admin_dedication_review", dedication_id=dedication.id)
			dedication.status = SacramentStatus.APPROVED
		elif action == "reject":
			if dedication.status != SacramentStatus.PENDING:
				messages.error(request, "Only pending requests can be rejected.")
				return redirect("admin_dedication_review", dedication_id=dedication.id)
			if not comment:
				messages.error(request, "Rejection reason is required.")
				return redirect("admin_dedication_review", dedication_id=dedication.id)
			dedication.status = SacramentStatus.REJECTED
		elif action == "schedule":
			if dedication.status != SacramentStatus.APPROVED:
				messages.error(request, "Only approved requests can be scheduled.")
				return redirect("admin_dedication_review", dedication_id=dedication.id)
			service_date, error = _parse_date(service_date_raw, "Dedication date")
			if error:
				messages.error(request, error)
				return redirect("admin_dedication_review", dedication_id=dedication.id)
			if service_date < timezone.localdate():
				messages.error(request, "Dedication date cannot be in the past.")
				return redirect("admin_dedication_review", dedication_id=dedication.id)
			if not officiant_obj:
				messages.error(request, "Select an officiant from the officiants database.")
				return redirect("admin_dedication_review", dedication_id=dedication.id)
			dedication.dedication_date = service_date
			dedication.officiant = str(officiant_obj)
			dedication.status = SacramentStatus.SCHEDULED
		elif action == "complete":
			if dedication.status != SacramentStatus.SCHEDULED:
				messages.error(request, "Only scheduled requests can be marked completed.")
				return redirect("admin_dedication_review", dedication_id=dedication.id)
			dedication.status = SacramentStatus.COMPLETED
		else:
			messages.error(request, "Invalid action.")
			return redirect("admin_dedication_review", dedication_id=dedication.id)
		if comment:
			dedication.admin_comment = comment
		dedication.save()
		notifications.send_dedication_status(dedication, action)
		_ddate = dedication.dedication_date.strftime("%d %B %Y") if dedication.dedication_date else "a date to be confirmed"
		_dmsg = {
			"approve": "Your baby dedication request has been approved.",
			"reject": "Your baby dedication request was not approved.",
			"schedule": f"Your baby dedication has been scheduled for {_ddate}.",
			"complete": "Your baby dedication has been marked as completed.",
		}.get(action, "Your baby dedication status has been updated.")
		for _dp in [dedication.father, dedication.mother]:
			if _dp:
				notify_member(_dp, MemberNotification.CAT_DEDICATION, _dmsg)
		log(request.user, action, ActivityLog.CAT_DEDICATION, f"Dedication for {dedication.child.first_name} {dedication.child.last_name} marked {action}.")
		messages.success(request, "Dedication request updated.")
		return redirect("admin_dedication_review", dedication_id=dedication.id)
	return render(
		request,
		"admin/dedication_review.html",
		{
			"item": dedication,
			"officiants": officiants,
			"parent_choices": parent_choices,
			"latest_certificate": latest_certificate,
			"child_age": _calculate_age(dedication.child.date_of_birth),
		},
	)


@login_required
@staff_required
def admin_generate_dedication_certificate(request, dedication_id):
	dedication = get_object_or_404(BabyDedication, id=dedication_id)
	if request.method != "POST":
		raise Http404
	if dedication.status not in {SacramentStatus.SCHEDULED, SacramentStatus.COMPLETED}:
		messages.error(request, "Certificates can only be generated after dedication is scheduled.")
		return redirect("admin_dedication_review", dedication_id=dedication.id)
	if not dedication.dedication_date:
		messages.error(request, "Set dedication date before generating certificate.")
		return redirect("admin_dedication_review", dedication_id=dedication.id)
	generate_dedication_certificate(dedication, design_template=DEDICATION_FIXED_DESIGN_TEMPLATE)
	log(request.user, "generate", ActivityLog.CAT_CERTIFICATE, f"Dedication certificate generated for {dedication.child.first_name} {dedication.child.last_name}.")
	messages.success(request, "Dedication certificate generated.")
	return redirect("admin_dedication_review", dedication_id=dedication.id)


@login_required
@staff_required
def admin_preview_wedding_certificate(request, wedding_id):
	wedding = get_object_or_404(Wedding, id=wedding_id)
	if request.method != "POST":
		raise Http404
	pdf_data = render_wedding_preview_pdf(wedding, design_template=WEDDING_FIXED_DESIGN_TEMPLATE)
	response = HttpResponse(pdf_data, content_type="application/pdf")
	response["Content-Disposition"] = f'inline; filename="wedding-preview-{wedding.id}.pdf"'
	return response


@login_required
@staff_required
def admin_preview_dedication_certificate(request, dedication_id):
	dedication = get_object_or_404(BabyDedication, id=dedication_id)
	if request.method != "POST":
		raise Http404
	pdf_data = render_dedication_preview_pdf(dedication, design_template=DEDICATION_FIXED_DESIGN_TEMPLATE)
	response = HttpResponse(pdf_data, content_type="application/pdf")
	response["Content-Disposition"] = f'inline; filename="dedication-preview-{dedication.id}.pdf"'
	return response


@method_decorator([login_required, staff_required], name="dispatch")
class WeddingListView(TemplateView):
	template_name = "admin/wedding_list.html"

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		couple_type = self.request.GET.get("couple_type", "all").strip().lower() or "all"
		query = self.request.GET.get("q", "").strip()
		sort = self.request.GET.get("sort", "date")
		dir = self.request.GET.get("dir", "desc")
		weddings = Wedding.objects.select_related("groom", "bride").all()

		if couple_type == "members":
			weddings = weddings.filter(groom__is_member=True, bride__is_member=True)
		elif couple_type == "non_members":
			weddings = weddings.filter(groom__is_member=False, bride__is_member=False)
		elif couple_type == "mixed":
			weddings = weddings.filter(
				(Q(groom__is_member=True, bride__is_member=False) | Q(groom__is_member=False, bride__is_member=True))
			)
		else:
			couple_type = "all"

		if query:
			weddings = weddings.filter(
				Q(groom__first_name__icontains=query) | Q(groom__last_name__icontains=query) |
				Q(bride__first_name__icontains=query) | Q(bride__last_name__icontains=query)
			)

		sort_map = {
			"groom": "groom__first_name",
			"bride": "bride__first_name",
			"date": "wedding_date",
			"status": "status",
		}
		order_field = sort_map.get(sort, "wedding_date")
		if dir == "desc":
			order_field = f"-{order_field}"
		weddings = weddings.order_by(order_field)

		paginator = Paginator(weddings, 10)
		context["page_obj"] = paginator.get_page(self.request.GET.get("page"))
		context["q"] = query
		context["sort"] = sort
		context["dir"] = dir
		context["couple_type"] = couple_type
		context["page_query"] = _query_without_page(self.request)
		context["pending_requests"] = (
			WeddingRequest.objects
			.select_related("submitter", "partner")
			.filter(status=SacramentStatus.PENDING)
			.order_by("-created_at")
		)
		return context


@login_required
@staff_required
def admin_wedding_request_review(request, request_id):
	wrequest = get_object_or_404(WeddingRequest, id=request_id)

	if request.method == "POST":
		action = request.POST.get("action")

		if action == "approve":
			if wrequest.submitter_role == "groom":
				groom, bride = wrequest.submitter, wrequest.partner
			else:
				groom, bride = wrequest.partner, wrequest.submitter

			if not groom or not bride:
				messages.error(request, "Cannot approve: partner Person record is missing.")
				return redirect("admin_wedding_request_review", request_id=wrequest.id)

			try:
				wedding = Wedding.objects.create(
					groom=groom,
					bride=bride,
					available_slot=wrequest.available_slot,
					couple_photo=wrequest.couple_photo,
					groom_health_document=wrequest.submitter_health_document if wrequest.submitter_role == "groom" else wrequest.partner_health_document,
					bride_health_document=wrequest.partner_health_document if wrequest.submitter_role == "groom" else wrequest.submitter_health_document,
					status=SacramentStatus.APPROVED,
				)
				WeddingRequest.objects.filter(id=wrequest.id).update(
					status=SacramentStatus.APPROVED,
					updated_at=timezone.now(),
				)
				notifications.send_wedding_approved(wrequest)
				notify_member(wrequest.submitter, MemberNotification.CAT_WEDDING,
					"Your wedding request has been approved. Scheduling details will follow.")
				log(request.user, "approve", ActivityLog.CAT_WEDDING,
					f"Wedding request by {wrequest.submitter.first_name} {wrequest.submitter.last_name} approved.")
				messages.success(request, "Wedding request approved. Set the date and officiant below.")
				return redirect("admin_wedding_review", wedding_id=wedding.id)
			except Exception as exc:
				messages.error(request, f"Approval failed: {exc}")
				return redirect("admin_wedding_request_review", request_id=wrequest.id)

		elif action == "reject":
			wrequest.status = SacramentStatus.REJECTED
			wrequest.admin_comment = request.POST.get("admin_comment", "")
			wrequest.save(update_fields=["status", "admin_comment", "updated_at"])
			notifications.send_wedding_rejected(wrequest)
			_wrej_comment = wrequest.admin_comment
			notify_member(wrequest.submitter, MemberNotification.CAT_WEDDING,
				f"Your wedding request was not approved.{' ' + _wrej_comment if _wrej_comment else ''}")
			log(request.user, "reject", ActivityLog.CAT_WEDDING, f"Wedding request by {wrequest.submitter.first_name} {wrequest.submitter.last_name} rejected.")
			messages.info(request, "Wedding request rejected.")
			return redirect("admin_wedding_list")

	return render(request, "admin/wedding_request_review.html", {"item": wrequest})


@method_decorator([login_required, staff_required], name="dispatch")
class OfficiantListView(TemplateView):
	template_name = "admin/officiant_list.html"

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		query = self.request.GET.get("q", "").strip()
		officiants = Officiant.objects.all()
		if query:
			officiants = officiants.filter(Q(name__icontains=query) | Q(title__icontains=query))
		paginator = Paginator(officiants, 12)
		context["page_obj"] = paginator.get_page(self.request.GET.get("page"))
		context["q"] = query
		context["page_query"] = _query_without_page(self.request)
		return context


@login_required
@staff_required
def admin_officiant_create(request):
	if request.method == "POST":
		name = request.POST.get("name", "").strip()
		title = request.POST.get("title", "").strip()
		signature_image = request.FILES.get("signature_image")
		if not name:
			messages.error(request, "Officiant name is required.")
			return render(request, "admin/officiant_form.html")
		if Officiant.objects.filter(name__iexact=name).exists():
			messages.error(request, "An officiant with this name already exists.")
			return render(request, "admin/officiant_form.html")
		if signature_image:
			if not getattr(signature_image, "content_type", "").startswith("image/"):
				messages.error(request, "Signature must be an image file.")
				return render(request, "admin/officiant_form.html")
			if signature_image.size > 3 * 1024 * 1024:
				messages.error(request, "Signature image must be 3MB or smaller.")
				return render(request, "admin/officiant_form.html")
		Officiant.objects.create(name=name, title=title, signature_image=signature_image, is_active=True)
		messages.success(request, "Officiant created.")
		return redirect("admin_officiant_list")
	return render(request, "admin/officiant_form.html")


@login_required
@staff_required
def admin_officiant_edit(request, officiant_id):
	officiant = get_object_or_404(Officiant, id=officiant_id)
	if request.method == "POST":
		name = request.POST.get("name", "").strip()
		title = request.POST.get("title", "").strip()
		remove_signature = request.POST.get("remove_signature") == "on"
		signature_image = request.FILES.get("signature_image")
		is_active = request.POST.get("is_active") == "on"
		if not name:
			messages.error(request, "Officiant name is required.")
			return render(request, "admin/officiant_form.html", {"officiant": officiant})
		if Officiant.objects.filter(name__iexact=name).exclude(id=officiant.id).exists():
			messages.error(request, "An officiant with this name already exists.")
			return render(request, "admin/officiant_form.html", {"officiant": officiant})
		if signature_image:
			if not getattr(signature_image, "content_type", "").startswith("image/"):
				messages.error(request, "Signature must be an image file.")
				return render(request, "admin/officiant_form.html", {"officiant": officiant})
			if signature_image.size > 3 * 1024 * 1024:
				messages.error(request, "Signature image must be 3MB or smaller.")
				return render(request, "admin/officiant_form.html", {"officiant": officiant})
		officiant.name = name
		officiant.title = title
		officiant.is_active = is_active
		if remove_signature and officiant.signature_image:
			officiant.signature_image.delete(save=False)
			officiant.signature_image = ""
		if signature_image:
			if officiant.signature_image:
				officiant.signature_image.delete(save=False)
			officiant.signature_image = signature_image
		officiant.save()
		messages.success(request, "Officiant updated.")
		return redirect("admin_officiant_list")
	return render(request, "admin/officiant_form.html", {"officiant": officiant})


@login_required
@staff_required
def admin_officiant_delete(request, officiant_id):
	if request.method != "POST":
		raise Http404

	officiant = get_object_or_404(Officiant, id=officiant_id)
	officiant_name = str(officiant)

	linked_exists = (
		Baptism.objects.filter(officiant=officiant_name).exists()
		or BabyDedication.objects.filter(officiant=officiant_name).exists()
		or Wedding.objects.filter(officiant=officiant_name).exists()
	)

	if linked_exists:
		officiant.is_active = False
		officiant.save(update_fields=["is_active", "updated_at"])
		messages.warning(request, "Officiant is referenced in records and cannot be deleted. Officiant was deactivated.")
		return redirect("admin_officiant_list")

	officiant.delete()
	messages.success(request, "Officiant deleted.")
	return redirect("admin_officiant_list")


def _active_officiants():
	return Officiant.objects.filter(is_active=True).order_by("name")


def _resolve_selected_officiant(officiant_id):
	if not officiant_id:
		return None
	try:
		return Officiant.objects.get(id=officiant_id, is_active=True)
	except (ValueError, Officiant.DoesNotExist):
		return None


@login_required
@staff_required
def admin_wedding_create(request):
	people = Person.objects.filter(is_active=True).order_by("last_name", "first_name")
	officiants = _active_officiants()

	def _resolve_existing_person(person_id):
		if not person_id:
			return None
		try:
			return Person.objects.get(id=person_id)
		except (ValueError, Person.DoesNotExist):
			return None

	def _create_person_from_manual(prefix):
		first_name = request.POST.get(f"{prefix}_first_name", "").strip()
		last_name = request.POST.get(f"{prefix}_last_name", "").strip()
		gender = request.POST.get(f"{prefix}_gender", "").strip()
		dob_raw = request.POST.get(f"{prefix}_date_of_birth", "")
		phone = request.POST.get(f"{prefix}_phone", "").strip()
		email = request.POST.get(f"{prefix}_email", "").strip()
		address = request.POST.get(f"{prefix}_address", "").strip()

		if not first_name and not last_name and not gender and not dob_raw:
			return None, f"Select an existing {prefix} or provide full manual details."

		dob, dob_error = _parse_date(dob_raw, f"{prefix.capitalize()} date of birth")
		if not first_name or not last_name or not gender or dob_error:
			return None, dob_error or f"{prefix.capitalize()} first name, last name, gender and date of birth are required."
		if dob > timezone.localdate():
			return None, f"{prefix.capitalize()} date of birth cannot be in the future."

		email_error = _validate_email_value(email)
		phone_error = _validate_phone(phone)
		if email_error or phone_error:
			return None, email_error or phone_error

		person = Person.objects.create(
			first_name=first_name,
			last_name=last_name,
			gender=gender,
			date_of_birth=dob,
			phone=phone,
			email=email,
			address=address,
			is_member=False,
			is_active=True,
		)
		return person, None

	if request.method == "POST":
		groom_person_id = request.POST.get("groom_person_id", "").strip()
		bride_person_id = request.POST.get("bride_person_id", "").strip()
		groom_health_document = request.FILES.get("groom_health_document")
		bride_health_document = request.FILES.get("bride_health_document")
		groom_church_name = request.POST.get("groom_church_name", "").strip() or request.POST.get(
			"groom_existing_church_name", ""
		).strip()
		bride_church_name = request.POST.get("bride_church_name", "").strip() or request.POST.get(
			"bride_existing_church_name", ""
		).strip()
		wedding_date, error = _parse_date(request.POST.get("wedding_date", ""), "Wedding date")
		officiant_obj = _resolve_selected_officiant(request.POST.get("officiant_id", "").strip())

		if error or not officiant_obj:
			messages.error(request, error or "All fields are required.")
			return render(request, "admin/wedding_form.html", {"people": people, "officiants": officiants})
		if wedding_date < timezone.localdate():
			messages.error(request, "Wedding date cannot be in the past.")
			return render(request, "admin/wedding_form.html", {"people": people, "officiants": officiants})

		groom = _resolve_existing_person(groom_person_id)
		bride = _resolve_existing_person(bride_person_id)

		if groom is None:
			groom, groom_error = _create_person_from_manual("groom")
			if groom_error:
				messages.error(request, groom_error)
				return render(request, "admin/wedding_form.html", {"people": people, "officiants": officiants})

		if bride is None:
			bride, bride_error = _create_person_from_manual("bride")
			if bride_error:
				messages.error(request, bride_error)
				return render(request, "admin/wedding_form.html", {"people": people, "officiants": officiants})

		if groom.id == bride.id:
			messages.error(request, "Groom and bride must be different people.")
			return render(request, "admin/wedding_form.html", {"people": people, "officiants": officiants})

		if not groom.is_member and not groom_church_name:
			messages.error(request, "Provide church name for a non-member groom.")
			return render(request, "admin/wedding_form.html", {"people": people, "officiants": officiants})
		if not bride.is_member and not bride_church_name:
			messages.error(request, "Provide church name for a non-member bride.")
			return render(request, "admin/wedding_form.html", {"people": people, "officiants": officiants})

		if groom.is_member:
			groom_church_name = ""
		if bride.is_member:
			bride_church_name = ""

		document_error = _validate_health_document(groom_health_document, "Groom") or _validate_health_document(
			bride_health_document, "Bride"
		)
		if document_error:
			messages.error(request, document_error)
			return render(request, "admin/wedding_form.html", {"people": people, "officiants": officiants})

		Wedding.objects.create(
			groom=groom,
			bride=bride,
			groom_church_name=groom_church_name,
			bride_church_name=bride_church_name,
			wedding_date=wedding_date,
			officiant=str(officiant_obj),
			groom_health_document=groom_health_document,
			bride_health_document=bride_health_document,
			status=SacramentStatus.SCHEDULED,
		)
		messages.success(request, "Wedding created.")
		return redirect("admin_wedding_list")
	return render(request, "admin/wedding_form.html", {"people": people, "officiants": officiants})


@login_required
@staff_required
def admin_wedding_review(request, wedding_id):
	wedding = get_object_or_404(Wedding.objects.select_related("groom", "bride"), id=wedding_id)
	officiants = _active_officiants()
	if request.method == "POST":
		action = request.POST.get("action")
		comment = request.POST.get("admin_comment", "").strip()
		if action == "mark_divorced":
			wedding.marriage_resolution = Wedding.RESOLUTION_DIVORCED
			if not comment:
				comment = "Marriage marked as divorced by admin."
		elif action == "mark_annulled":
			wedding.marriage_resolution = Wedding.RESOLUTION_ANNULLED
			wedding.resolution_date = date.today()
			if not comment:
				comment = "Marriage marked as annulled by admin."
		elif action == "mark_married":
			wedding.status = SacramentStatus.MARRIED
			if not comment:
				comment = "Marriage status set to Married by admin."
		elif action == "generate_certificate":
			# This action is handled by the separate certificate generation form
			# But we can redirect to show the form if needed
			messages.info(request, "Please select a certificate design and click Generate Certificate.")
			return redirect("admin_wedding_review", wedding_id=wedding.id)
		elif action == "approve":
			if wedding.status not in {SacramentStatus.PENDING, SacramentStatus.REJECTED}:
				messages.error(request, "Only pending or rejected wedding requests can be approved.")
				return redirect("admin_wedding_review", wedding_id=wedding.id)
			wedding.status = SacramentStatus.APPROVED
		elif action == "reject":
			if wedding.status not in {SacramentStatus.PENDING, SacramentStatus.APPROVED}:
				messages.error(request, "Only pending or approved wedding requests can be rejected.")
				return redirect("admin_wedding_review", wedding_id=wedding.id)
			if not comment:
				messages.error(request, "Provide a reason or instruction when rejecting a request.")
				return redirect("admin_wedding_review", wedding_id=wedding.id)
			wedding.status = SacramentStatus.REJECTED
		elif action == "complete":
			wedding.status = SacramentStatus.COMPLETED
		elif action == "schedule":
			if wedding.status not in {SacramentStatus.PENDING, SacramentStatus.APPROVED, SacramentStatus.REJECTED}:
				messages.error(request, "Wedding must be in Pending, Approved, or Rejected status to be scheduled.")
				return redirect("admin_wedding_review", wedding_id=wedding.id)
			service_date, error = _parse_date(request.POST.get("service_date", ""), "Wedding date")
			officiant_obj = _resolve_selected_officiant(request.POST.get("officiant_id", "").strip())
			if error:
				messages.error(request, error)
				return redirect("admin_wedding_review", wedding_id=wedding.id)
			if service_date < timezone.localdate():
				messages.error(request, "Wedding date cannot be in the past.")
				return redirect("admin_wedding_review", wedding_id=wedding.id)
			if not officiant_obj:
				messages.error(request, "Select an officiant from the officiants database.")
				return redirect("admin_wedding_review", wedding_id=wedding.id)
			wedding.wedding_date = service_date
			wedding.officiant = str(officiant_obj)
			wedding.status = SacramentStatus.SCHEDULED
		elif action == "upload_photo":
			photo = request.FILES.get("couple_photo")
			if photo:
				wedding.couple_photo = photo
				wedding.save(update_fields=["couple_photo", "updated_at"])
				messages.success(request, "Couple photo uploaded successfully.")
			else:
				messages.error(request, "No file was selected.")
			return redirect("admin_wedding_review", wedding_id=wedding.id)
		else:
			messages.error(request, "Invalid action.")
			return redirect("admin_wedding_review", wedding_id=wedding.id)
		if comment:
			wedding.admin_comment = comment
		wedding.save()
		if action == "schedule" and wedding.wedding_date:
			_wdate = wedding.wedding_date.strftime("%d %B %Y")
			notifications.send_wedding_scheduled(wedding)
			for _wp in [wedding.groom, wedding.bride]:
				if _wp:
					notify_member(_wp, MemberNotification.CAT_WEDDING, f"Your wedding has been scheduled for {_wdate}.")
		elif action == "mark_married":
			for _wp in [wedding.groom, wedding.bride]:
				if _wp:
					notify_member(_wp, MemberNotification.CAT_WEDDING, "Congratulations! Your marriage has been recorded.")
		messages.success(request, "Wedding updated.")
		return redirect("admin_wedding_review", wedding_id=wedding.id)
	# Lazy 10-day check: if annulment window has closed, reset both persons to Single
	if (
		wedding.marriage_resolution == Wedding.RESOLUTION_ANNULLED
		and wedding.resolution_date
		and date.today() > wedding.resolution_date + timedelta(days=10)
	):
		for person in [wedding.groom, wedding.bride]:
			if person and person.marital_status != "Single":
				person.marital_status = "Single"
				person.spouse_name = ""
				person.save(update_fields=["marital_status", "spouse_name"])

	within_remarry_window = (
		wedding.marriage_resolution == Wedding.RESOLUTION_ANNULLED
		and wedding.resolution_date is not None
		and date.today() <= wedding.resolution_date + timedelta(days=10)
	)

	latest_certificate = (
		Certificate.objects.filter(
			service_type=Certificate.WEDDING,
			object_id=wedding.id,
		)
		.exclude(certificate_file="")
		.order_by("-issued_date", "-created_at")
		.first()
	)
	return render(
		request,
		"admin/wedding_review.html",
		{
			"item": wedding,
			"officiants": officiants,
			"latest_certificate": latest_certificate,
			"within_remarry_window": within_remarry_window,
		},
	)


@login_required
@staff_required
def admin_wedding_edit(request, wedding_id):
	wedding = get_object_or_404(Wedding.objects.select_related("groom", "bride"), id=wedding_id)
	people = Person.objects.filter(is_active=True).order_by("last_name", "first_name")
	officiants = _active_officiants()

	# Resolve which officiant is currently assigned
	current_officiant_name = wedding.officiant
	selected_officiant_id = ""
	for o in officiants:
		if str(o) == current_officiant_name:
			selected_officiant_id = o.id
			break

	if request.method == "POST":
		groom_church_name = request.POST.get("groom_church_name", "").strip() or request.POST.get(
			"groom_existing_church_name", ""
		).strip()
		bride_church_name = request.POST.get("bride_church_name", "").strip() or request.POST.get(
			"bride_existing_church_name", ""
		).strip()
		wedding_date, error = _parse_date(request.POST.get("wedding_date", ""), "Wedding date")
		officiant_obj = _resolve_selected_officiant(request.POST.get("officiant_id", "").strip())
		admin_comment = request.POST.get("admin_comment", "").strip()

		if error or not officiant_obj:
			messages.error(request, error or "Wedding date and officiant are required.")
			return render(request, "admin/wedding_form.html", {
				"wedding": wedding, "people": people, "officiants": officiants, "is_edit": True,
				"selected_officiant_id": selected_officiant_id,
			})
		if wedding_date < timezone.localdate():
			messages.error(request, "Wedding date cannot be in the past.")
			return render(request, "admin/wedding_form.html", {
				"wedding": wedding, "people": people, "officiants": officiants, "is_edit": True,
				"selected_officiant_id": selected_officiant_id,
			})

		if not wedding.groom.is_member and not groom_church_name:
			messages.error(request, "Provide church name for a non-member groom.")
			return render(request, "admin/wedding_form.html", {
				"wedding": wedding, "people": people, "officiants": officiants, "is_edit": True,
				"selected_officiant_id": selected_officiant_id,
			})
		if not wedding.bride.is_member and not bride_church_name:
			messages.error(request, "Provide church name for a non-member bride.")
			return render(request, "admin/wedding_form.html", {
				"wedding": wedding, "people": people, "officiants": officiants, "is_edit": True,
				"selected_officiant_id": selected_officiant_id,
			})

		# Update health documents if new ones uploaded
		groom_health = request.FILES.get("groom_health_document")
		bride_health = request.FILES.get("bride_health_document")
		couple_photo = request.FILES.get("couple_photo")
		if groom_health:
			wedding.groom_health_document = groom_health
		if bride_health:
			wedding.bride_health_document = bride_health
		if couple_photo:
			wedding.couple_photo = couple_photo

		wedding.groom_church_name = groom_church_name if not wedding.groom.is_member else ""
		wedding.bride_church_name = bride_church_name if not wedding.bride.is_member else ""
		wedding.wedding_date = wedding_date
		wedding.officiant = str(officiant_obj)
		wedding.admin_comment = admin_comment
		wedding.save()
		messages.success(request, "Wedding updated successfully.")
		return redirect("admin_wedding_review", wedding_id=wedding.id)

	return render(request, "admin/wedding_form.html", {
		"wedding": wedding,
		"people": people,
		"officiants": officiants,
		"is_edit": True,
		"selected_officiant_id": selected_officiant_id,
	})


@login_required
@staff_required
def admin_generate_wedding_certificate(request, wedding_id):
	wedding = get_object_or_404(Wedding, id=wedding_id)
	if request.method != "POST":
		raise Http404
	admin_override = request.POST.get("admin_override") == "true"

	# Check if wedding is scheduled and date validation
	if wedding.status != SacramentStatus.SCHEDULED:
		messages.error(request, "Certificate can only be generated for scheduled weddings.")
		return redirect("admin_wedding_review", wedding_id=wedding.id)

	today = timezone.localdate()

	if wedding.wedding_date > today and not admin_override:
		messages.warning(request, f"Wedding date ({wedding.wedding_date}) is in the future. Certificate generation is not allowed yet. Check 'Admin Override' to proceed anyway.")
		return redirect("admin_wedding_review", wedding_id=wedding.id)
	elif wedding.wedding_date < today and not admin_override:
		messages.warning(request, f"Wedding date ({wedding.wedding_date}) has passed. Normally certificates should be generated on or after the wedding date. Check 'Admin Override' to proceed anyway.")
		return redirect("admin_wedding_review", wedding_id=wedding.id)

	generate_wedding_certificate(wedding, design_template=WEDDING_FIXED_DESIGN_TEMPLATE)
	log(request.user, "generate", ActivityLog.CAT_CERTIFICATE, f"Wedding certificate generated for {wedding.groom.first_name} {wedding.groom.last_name} & {wedding.bride.first_name} {wedding.bride.last_name}.")
	messages.success(request, "Wedding certificate generated.")
	return redirect("admin_wedding_review", wedding_id=wedding.id)


@method_decorator([login_required, staff_required], name="dispatch")
class CertificateListView(TemplateView):
	template_name = "admin/certificate_list.html"

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		query = self.request.GET.get("q", "").strip()
		certificates = Certificate.objects.select_related("content_type").order_by("-issued_date")
		if query:
			certificates = certificates.filter(certificate_number__icontains=query)
		paginator = Paginator(certificates, 15)
		context["page_obj"] = paginator.get_page(self.request.GET.get("page"))
		context["q"] = query
		context["page_query"] = _query_without_page(self.request)
		# Authentication result
		auth_number = self.request.GET.get("auth", "").strip()
		context["auth_certificate"] = None
		if auth_number:
			context["auth_certificate"] = Certificate.objects.filter(certificate_number__iexact=auth_number).first()
		return context


def _certificate_source_url(certificate):
	"""Get the admin review URL for the sacrament linked to a certificate."""
	linked = certificate.linked_object
	if not linked:
		return None
	if certificate.service_type == Certificate.BAPTISM:
		return reverse("admin_baptism_review", kwargs={"baptism_id": linked.id})
	elif certificate.service_type == Certificate.DEDICATION:
		return reverse("admin_dedication_review", kwargs={"dedication_id": linked.id})
	elif certificate.service_type == Certificate.WEDDING:
		return reverse("admin_wedding_review", kwargs={"wedding_id": linked.id})
	return None


def _certificate_source_name(certificate):
	"""Get the display name for the person/couple linked to a certificate."""
	linked = certificate.linked_object
	if not linked:
		return "-"
	if certificate.service_type == Certificate.BAPTISM:
		return str(linked.person)
	elif certificate.service_type == Certificate.DEDICATION:
		return str(linked.child)
	elif certificate.service_type == Certificate.WEDDING:
		return f"{linked.groom} & {linked.bride}"
	return "-"


@login_required
@staff_required
def admin_certificate_authenticate(request):
	"""Admin-side certificate authentication."""
	if request.method != "POST":
		raise Http404
	certificate_number = request.POST.get("certificate_number", "").strip()
	if not certificate_number:
		messages.error(request, "Enter a certificate number to authenticate.")
		return redirect("admin_certificate_list")
	return redirect(f"{reverse('admin_certificate_list')}?auth={certificate_number}")


@login_required
@staff_required
def admin_revoke_certificate(request, certificate_id):
	certificate = get_object_or_404(Certificate, id=certificate_id)
	if request.method != "POST":
		raise Http404
	reason = request.POST.get("reason", "").strip()
	if not reason:
		messages.error(request, "Revocation reason is required.")
		return redirect("admin_certificate_list")
	certificate.is_valid = False
	certificate.revoked_reason = reason
	certificate.save(update_fields=["is_valid", "revoked_reason", "updated_at"])
	messages.success(request, "Certificate revoked.")
	return redirect("admin_certificate_list")


@login_required
@staff_required
def admin_calendar(request):
	today = timezone.localdate()
	year = int(request.GET.get("year", today.year))
	month = int(request.GET.get("month", today.month))
	_, total_days = calendar.monthrange(year, month)

	month_rows = list(calendar.Calendar(firstweekday=0).monthdayscalendar(year, month))

	events = []
	for item in Baptism.objects.filter(baptism_date__year=year, baptism_date__month=month):
		events.append({"day": item.baptism_date.day, "label": f"Baptism: {item.person}", "type": "baptism"})
	for item in BabyDedication.objects.filter(dedication_date__year=year, dedication_date__month=month):
		events.append({"day": item.dedication_date.day, "label": f"Dedication: {item.child}", "type": "dedication"})
	for item in Wedding.objects.filter(wedding_date__year=year, wedding_date__month=month).exclude(marriage_resolution=Wedding.RESOLUTION_ANNULLED):
		events.append({"day": item.wedding_date.day, "label": f"Wedding: {item.groom} & {item.bride}", "type": "wedding"})

	return render(
		request,
		"admin/calendar.html",
		{
			"year": year,
			"month": month,
			"month_rows": month_rows,
			"events": events,
			"month_name": calendar.month_name[month],
		},
	)


@login_required
@staff_required
def admin_scheduling(request):
	today = timezone.localdate()
	year = int(request.GET.get("year", today.year))
	month = int(request.GET.get("month", today.month))
	_, total_days = calendar.monthrange(year, month)

	if request.method == "POST":
		action = request.POST.get("action", "")

		if action == "add_slot":
			activity_type = request.POST.get("activity_type", "").strip()
			slot_date, date_error = _parse_date(request.POST.get("date", ""), "Date")
			slot_time_str = request.POST.get("time", "").strip()

			if date_error or not activity_type:
				messages.error(request, date_error or "Activity type and date are required.")
				return redirect("admin_scheduling")

			slot_time = None
			if activity_type == AvailableSlot.ACTIVITY_WEDDING and slot_time_str:
				try:
					slot_time = datetime.strptime(slot_time_str, "%H:%M").time()
				except ValueError:
					messages.error(request, "Invalid time format. Use HH:MM (e.g. 14:00).")
					return redirect("admin_scheduling")

			AvailableSlot.objects.get_or_create(
				activity_type=activity_type,
				date=slot_date,
				time=slot_time,
				defaults={"is_available": True},
			)
			messages.success(request, f"{activity_type} slot created for {slot_date}.")
			return redirect("admin_scheduling")

		elif action == "add_blackout":
			blackout_date, date_error = _parse_date(request.POST.get("date", ""), "Date")
			reason = request.POST.get("reason", "").strip()
			activity_type = request.POST.get("activity_type", "All").strip()

			if date_error:
				messages.error(request, date_error)
				return redirect("admin_scheduling")

			BlackoutDate.objects.get_or_create(
				date=blackout_date,
				activity_type=activity_type,
				defaults={"reason": reason},
			)
			messages.success(request, f"Blackout date added for {blackout_date}.")
			return redirect("admin_scheduling")

		elif action == "bulk_create":
			activity_type = request.POST.get("activity_type", "").strip()
			start_date, start_error = _parse_date(request.POST.get("start_date", ""), "Start date")
			end_date, end_error = _parse_date(request.POST.get("end_date", ""), "End date")

			if start_error or end_error or not activity_type:
				messages.error(request, start_error or end_error or "Activity type, start and end dates are required.")
				return redirect("admin_scheduling")
			if start_date > end_date:
				start_date, end_date = end_date, start_date

			times = [None]
			if activity_type == AvailableSlot.ACTIVITY_WEDDING:
				times = [time(12, 0), time(14, 0), time(16, 0)]

			created = 0
			current = start_date
			while current <= end_date:
				for slot_time in times:
					_, was_created = AvailableSlot.objects.get_or_create(
						activity_type=activity_type,
						date=current,
						time=slot_time,
						defaults={"is_available": True},
					)
					if was_created:
						created += 1
				current += timedelta(days=1)

			messages.success(request, f"{created} {activity_type} slot(s) created from {start_date} to {end_date}.")
			return redirect("admin_scheduling")

		elif action == "toggle_slot":
			slot_id = request.POST.get("slot_id", "").strip()
			try:
				slot = AvailableSlot.objects.get(id=slot_id)
				slot.is_available = not slot.is_available
				slot.save(update_fields=["is_available"])
				messages.success(request, f"Slot {'enabled' if slot.is_available else 'disabled'}.")
			except (ValueError, AvailableSlot.DoesNotExist):
				messages.error(request, "Invalid slot.")
			return redirect("admin_scheduling")

		elif action == "delete_blackout":
			blackout_id = request.POST.get("blackout_id", "").strip()
			try:
				BlackoutDate.objects.get(id=blackout_id).delete()
				messages.success(request, "Blackout date removed.")
			except (ValueError, BlackoutDate.DoesNotExist):
				messages.error(request, "Invalid blackout date.")
			return redirect("admin_scheduling")

		messages.error(request, "Invalid action.")
		return redirect("admin_scheduling")

	# GET: Build calendar data
	# Build month rows for calendar display
	import calendar as cal_mod
	cal = cal_mod.Calendar(firstweekday=0)  # Monday first
	month_rows = []
	for week in cal.monthdayscalendar(year, month):
		month_rows.append(week)

	events = []
	for item in Baptism.objects.filter(baptism_date__year=year, baptism_date__month=month):
		events.append({"day": item.baptism_date.day, "label": f"Baptism: {item.person}", "color": "#0d6efd", "type": "baptism"})
	for item in BabyDedication.objects.filter(dedication_date__year=year, dedication_date__month=month):
		events.append({"day": item.dedication_date.day, "label": f"Dedication: {item.child}", "color": "#fd7e14", "type": "dedication"})
	for item in Wedding.objects.filter(wedding_date__year=year, wedding_date__month=month):
		events.append({"day": item.wedding_date.day, "label": f"Wedding: {item.groom} & {item.bride}", "color": "#6f42c1", "type": "wedding"})

	# Blackout dates for the month
	blackout_dates = BlackoutDate.objects.filter(date__year=year, date__month=month)
	for bd in blackout_dates:
		events.append({"day": bd.date.day, "label": f"BLACKOUT: {bd.reason or bd.activity_type}", "color": "#dc3545", "type": "blackout"})

	# Available slots for the month
	available_slots = AvailableSlot.objects.filter(date__year=year, date__month=month).order_by("date", "time")
	upcoming_slots = AvailableSlot.objects.filter(date__gte=today, is_available=True).order_by("date", "time")[:20]
	upcoming_blackouts = BlackoutDate.objects.filter(date__gte=today).order_by("date")[:20]

	return render(
		request,
		"admin/scheduling.html",
		{
			"year": year,
			"month": month,
			"days": list(range(1, total_days + 1)),
			"events": events,
			"month_name": calendar.month_name[month],
			"available_slots": available_slots,
			"upcoming_slots": upcoming_slots,
			"upcoming_blackouts": upcoming_blackouts,
			"activity_choices": AvailableSlot.ACTIVITY_CHOICES,
			"blackout_activity_choices": BlackoutDate.ACTIVITY_CHOICES,
			"month_rows": month_rows,
		},
	)


@login_required
@staff_required
def admin_reports(request):
	current_year = timezone.now().year
	months = [f"{index:02d}" for index in range(1, 13)]

	def _to_int(value, fallback):
		try:
			return int(value)
		except (TypeError, ValueError):
			return fallback

	min_baptism_year = Baptism.objects.order_by("request_date").values_list("request_date", flat=True).first()
	min_dedication_year = BabyDedication.objects.order_by("request_date").values_list("request_date", flat=True).first()
	min_wedding_year = Wedding.objects.order_by("wedding_date").values_list("wedding_date", flat=True).first()

	year_candidates = [
		value.year
		for value in [min_baptism_year, min_dedication_year, min_wedding_year]
		if value is not None
	]
	minimum_year = min(year_candidates) if year_candidates else current_year - 4
	available_years = list(range(minimum_year, current_year + 1))

	selected_start_year = _to_int(request.GET.get("start_year", current_year - 4), current_year - 4)
	selected_end_year = _to_int(request.GET.get("end_year", current_year), current_year)

	if selected_start_year not in available_years:
		selected_start_year = max(minimum_year, current_year - 4)
	if selected_end_year not in available_years:
		selected_end_year = current_year
	if selected_start_year > selected_end_year:
		selected_start_year, selected_end_year = selected_end_year, selected_start_year

	years = [year for year in available_years if selected_start_year <= year <= selected_end_year]

	def by_month(model, field):
		output = []
		for month in months:
			output.append(model.objects.filter(**{f"{field}__year": current_year, f"{field}__month": int(month)}).count())
		return output

	baptisms_monthly = by_month(Baptism, "request_date")
	dedications_monthly = by_month(BabyDedication, "request_date")
	weddings_monthly = by_month(Wedding, "wedding_date")
	certificates_monthly = by_month(Certificate, "issued_date")
	membership_growth = by_month(Person, "date_joined")

	services_per_year_baptism = [Baptism.objects.filter(request_date__year=year).count() for year in years]
	services_per_year_dedication = [BabyDedication.objects.filter(request_date__year=year).count() for year in years]
	services_per_year_wedding = [Wedding.objects.filter(wedding_date__year=year).count() for year in years]

	approved_count = Baptism.objects.filter(status=SacramentStatus.APPROVED).count() + BabyDedication.objects.filter(
		status=SacramentStatus.APPROVED
	).count()
	rejected_count = Baptism.objects.filter(status=SacramentStatus.REJECTED).count() + BabyDedication.objects.filter(
		status=SacramentStatus.REJECTED
	).count()

	return render(
		request,
		"admin/reports.html",
		{
			"month_labels": months,
			"year_labels": years,
			"available_years": available_years,
			"selected_start_year": selected_start_year,
			"selected_end_year": selected_end_year,
			"baptisms_monthly": baptisms_monthly,
			"dedications_monthly": dedications_monthly,
			"weddings_monthly": weddings_monthly,
			"services_per_year_baptism": services_per_year_baptism,
			"services_per_year_dedication": services_per_year_dedication,
			"services_per_year_wedding": services_per_year_wedding,
			"certificates_monthly": certificates_monthly,
			"membership_growth": membership_growth,
			"approval_rejection": [approved_count, rejected_count],
		},
	)


@login_required
@staff_required
def admin_report_download(request):
	def _parse_date_safe(value):
		if not value:
			return None
		try:
			return datetime.strptime(value, "%Y-%m-%d").date()
		except (ValueError, TypeError):
			return None

	from_date = _parse_date_safe(request.GET.get("from_date"))
	to_date = _parse_date_safe(request.GET.get("to_date"))
	selected_status = request.GET.get("status", "").strip()
	format_type = request.GET.get("format", "").strip().lower()
	selected_types = request.GET.getlist("types")

	if not from_date or not to_date:
		return render(
			request,
			"admin/report_download.html",
			{
				"baptism_count": Baptism.objects.count(),
				"dedication_count": BabyDedication.objects.count(),
				"wedding_count": Wedding.objects.count(),
				"earliest_date": _get_earliest_date(),
				"latest_date": _get_latest_date(),
			},
		)

	if from_date > to_date:
		from_date, to_date = to_date, from_date

	if not selected_types:
		selected_types = ["baptisms", "dedications", "weddings"]

	def _filter_queryset(queryset, date_field):
		filters = {f"{date_field}__gte": from_date, f"{date_field}__lte": to_date}
		if selected_status:
			filters["status"] = selected_status
		return queryset.filter(**filters)

	rows = []
	if "baptisms" in selected_types:
		for b in _filter_queryset(
			Baptism.objects.select_related("person"), "baptism_date"
		).order_by("baptism_date"):
			rows.append((
				"Baptism",
				str(b.person),
				str(b.baptism_date or b.request_date),
				b.status,
				b.officiant or "-",
				str(b.request_date),
			))

	if "dedications" in selected_types:
		for d in _filter_queryset(
			BabyDedication.objects.select_related("child", "father", "mother"), "dedication_date"
		).order_by("dedication_date"):
			rows.append((
				"Dedication",
				str(d.child),
				str(d.dedication_date or d.request_date),
				d.status,
				f"Father: {d.father}, Mother: {d.mother}",
				d.scripture_reference or "-",
			))

	if "weddings" in selected_types:
		for w in _filter_queryset(
			Wedding.objects.select_related("groom", "bride"), "wedding_date"
		).order_by("wedding_date"):
			rows.append((
				"Wedding",
				f"{w.groom} & {w.bride}",
				str(w.wedding_date),
				w.status,
				w.officiant or "-",
				w.admin_comment or "-",
			))

	if format_type == "csv":
		response = HttpResponse(content_type="text/csv")
		response["Content-Disposition"] = f'attachment; filename="church_records_{from_date}_to_{to_date}.csv"'
		writer = csv.writer(response)
		writer.writerow([f"Church Records: {from_date} to {to_date}"])
		writer.writerow([f"Generated On: {timezone.localdate().isoformat()}"])
		writer.writerow([])
		writer.writerow(["Type", "Name", "Date", "Status", "Additional Info", "Notes"])
		for row in rows:
			writer.writerow(row)
		return response

	if format_type == "pdf":
		response = HttpResponse(content_type="application/pdf")
		response["Content-Disposition"] = f'attachment; filename="church_records_{from_date}_to_{to_date}.pdf"'
		pdf = canvas.Canvas(response, pagesize=A4)
		width, height = A4
		y = height - 40
		pdf.setFont("Helvetica-Bold", 14)
		pdf.drawString(40, y, "Church Records Report")
		y -= 22
		pdf.setFont("Helvetica", 10)
		pdf.drawString(40, y, f"Date Range: {from_date} to {to_date}")
		y -= 14
		pdf.drawString(40, y, f"Generated On: {timezone.localdate().isoformat()}")
		y -= 24
		pdf.setFont("Helvetica-Bold", 10)
		pdf.drawString(40, y, "Type")
		pdf.drawString(100, y, "Name")
		pdf.drawString(290, y, "Date")
		pdf.drawString(370, y, "Status")
		y -= 14
		pdf.line(40, y, width - 40, y)
		y -= 14
		pdf.setFont("Helvetica", 9)
		if not rows:
			pdf.drawString(40, y, "No records found for the selected range.")
		else:
			for row in rows:
				if y < 50:
					pdf.showPage()
					y = height - 40
					pdf.setFont("Helvetica-Bold", 10)
					pdf.drawString(40, y, "Type")
					pdf.drawString(100, y, "Name")
					pdf.drawString(290, y, "Date")
					pdf.drawString(370, y, "Status")
					y -= 14
					pdf.line(40, y, width - 40, y)
					y -= 14
					pdf.setFont("Helvetica", 9)
				record_type, name, service_date, status = row[0], row[1], row[2], row[3]
				trimmed_name = name if len(name) <= 35 else f"{name[:32]}..."
				pdf.drawString(40, y, record_type)
				pdf.drawString(100, y, trimmed_name)
				pdf.drawString(290, y, service_date)
				pdf.drawString(370, y, status)
				y -= 13
		pdf.save()
		return response

	return redirect("admin_report_download")


def _get_earliest_date():
	dates = []
	baptism = Baptism.objects.order_by("baptism_date").values_list("baptism_date", flat=True).first()
	if baptism:
		dates.append(baptism)
	dedication = BabyDedication.objects.order_by("dedication_date").values_list("dedication_date", flat=True).first()
	if dedication:
		dates.append(dedication)
	wedding = Wedding.objects.order_by("wedding_date").values_list("wedding_date", flat=True).first()
	if wedding:
		dates.append(wedding)
	return min(dates) if dates else None


def _get_latest_date():
	dates = []
	baptism = Baptism.objects.order_by("-baptism_date").values_list("baptism_date", flat=True).first()
	if baptism:
		dates.append(baptism)
	dedication = BabyDedication.objects.order_by("-dedication_date").values_list("dedication_date", flat=True).first()
	if dedication:
		dates.append(dedication)
	wedding = Wedding.objects.order_by("-wedding_date").values_list("wedding_date", flat=True).first()
	if wedding:
		dates.append(wedding)
	return max(dates) if dates else None


@login_required
@staff_required
def admin_ai_reports(request):
	prompt = ""
	report_result = None

	if request.method == "POST":
		action = request.POST.get("action", "generate")
		prompt = request.POST.get("prompt", "").strip()
		report_result = generate_ai_report(prompt)

		if action == "export_csv":
			if not report_result.get("matched"):
				messages.warning(request, "Cannot export CSV for an unrecognized request.")
				return redirect("admin_ai_reports")

			response = HttpResponse(content_type="text/csv")
			title = report_result.get("title", "ai-report").replace(" ", "_").replace("/", "-")
			response["Content-Disposition"] = f'attachment; filename="{title.lower()}.csv"'
			writer = csv.writer(response)
			writer.writerow([report_result.get("title", "AI Report")])
			writer.writerow(["Prompt", prompt])
			writer.writerow(["Generated On", timezone.localdate().isoformat()])
			writer.writerow([])
			columns = report_result.get("columns", [])
			rows = report_result.get("rows", [])
			if columns:
				writer.writerow(columns)
			for row in rows:
				writer.writerow(row)
			return response

		if report_result.get("matched"):
			messages.success(request, "AI report generated successfully.")
		else:
			messages.warning(request, "Could not match that request. Try one of the supported prompts.")

	if report_result is None:
		report_result = generate_ai_report("")

	return render(
		request,
		"admin/ai_reports.html",
		{
			"prompt": prompt,
			"report": report_result,
			"chat_examples": CHAT_EXAMPLES,
		},
	)


@login_required
@staff_required
def admin_ai_reports_chat_api(request):
	if request.method != "POST":
		raise Http404

	prompt = request.POST.get("prompt", "").strip()
	chat_result = answer_system_chat(prompt)
	return JsonResponse(chat_result)


@login_required
@staff_required
def export_services_csv(request):
	def _to_int(value, fallback):
		try:
			return int(value)
		except (TypeError, ValueError):
			return fallback

	current_year = timezone.now().year
	start_year = _to_int(request.GET.get("start_year"), current_year - 4)
	end_year = _to_int(request.GET.get("end_year"), current_year)
	if start_year > end_year:
		start_year, end_year = end_year, start_year

	response = HttpResponse(content_type="text/csv")
	response["Content-Disposition"] = 'attachment; filename="services_export.csv"'
	writer = csv.writer(response)
	writer.writerow(["Report Range", f"{start_year}-{end_year}"])
	writer.writerow(["Generated On", timezone.localdate().isoformat()])
	writer.writerow([])
	writer.writerow(["Type", "Name", "Date", "Status"])

	for baptism in Baptism.objects.select_related("person").filter(request_date__year__gte=start_year, request_date__year__lte=end_year):
		writer.writerow(["Baptism", str(baptism.person), baptism.baptism_date or baptism.request_date, baptism.status])
	for dedication in BabyDedication.objects.select_related("child").filter(request_date__year__gte=start_year, request_date__year__lte=end_year):
		writer.writerow(["Dedication", str(dedication.child), dedication.dedication_date or dedication.request_date, dedication.status])
	for wedding in Wedding.objects.select_related("groom", "bride").filter(wedding_date__year__gte=start_year, wedding_date__year__lte=end_year):
		writer.writerow(["Wedding", f"{wedding.groom} & {wedding.bride}", wedding.wedding_date, wedding.status])
	return response


@login_required
@staff_required
def export_services_pdf(request):
	def _to_int(value, fallback):
		try:
			return int(value)
		except (TypeError, ValueError):
			return fallback

	current_year = timezone.now().year
	start_year = _to_int(request.GET.get("start_year"), current_year - 4)
	end_year = _to_int(request.GET.get("end_year"), current_year)
	if start_year > end_year:
		start_year, end_year = end_year, start_year

	baptisms = Baptism.objects.select_related("person").filter(request_date__year__gte=start_year, request_date__year__lte=end_year)
	dedications = BabyDedication.objects.select_related("child").filter(request_date__year__gte=start_year, request_date__year__lte=end_year)
	weddings = Wedding.objects.select_related("groom", "bride").filter(wedding_date__year__gte=start_year, wedding_date__year__lte=end_year)

	rows = []
	for baptism in baptisms:
		rows.append(("Baptism", str(baptism.person), str(baptism.baptism_date or baptism.request_date), baptism.status))
	for dedication in dedications:
		rows.append(("Dedication", str(dedication.child), str(dedication.dedication_date or dedication.request_date), dedication.status))
	for wedding in weddings:
		rows.append(("Wedding", f"{wedding.groom} & {wedding.bride}", str(wedding.wedding_date), wedding.status))

	response = HttpResponse(content_type="application/pdf")
	response["Content-Disposition"] = 'attachment; filename="services_export.pdf"'

	pdf = canvas.Canvas(response, pagesize=A4)
	width, height = A4

	y = height - 40
	pdf.setFont("Helvetica-Bold", 14)
	pdf.drawString(40, y, "Church Services Report")
	y -= 22
	pdf.setFont("Helvetica", 10)
	pdf.drawString(40, y, f"Report Range: {start_year}-{end_year}")
	y -= 14
	pdf.drawString(40, y, f"Generated On: {timezone.localdate().isoformat()}")
	y -= 24

	pdf.setFont("Helvetica-Bold", 10)
	pdf.drawString(40, y, "Type")
	pdf.drawString(130, y, "Name")
	pdf.drawString(350, y, "Date")
	pdf.drawString(430, y, "Status")
	y -= 14
	pdf.line(40, y, width - 40, y)
	y -= 14

	pdf.setFont("Helvetica", 9)
	if not rows:
		pdf.drawString(40, y, "No records found for selected range.")
	else:
		for record_type, name, service_date, status in rows:
			if y < 50:
				pdf.showPage()
				y = height - 40
				pdf.setFont("Helvetica-Bold", 10)
				pdf.drawString(40, y, "Type")
				pdf.drawString(130, y, "Name")
				pdf.drawString(350, y, "Date")
				pdf.drawString(430, y, "Status")
				y -= 14
				pdf.line(40, y, width - 40, y)
				y -= 14
				pdf.setFont("Helvetica", 9)

			trimmed_name = name if len(name) <= 40 else f"{name[:37]}..."
			pdf.drawString(40, y, record_type)
			pdf.drawString(130, y, trimmed_name)
			pdf.drawString(350, y, service_date)
			pdf.drawString(430, y, status)
			y -= 13

	pdf.save()
	return response


@login_required
@staff_required
def export_certificate_log_pdf(request):
	def _to_int(value, fallback):
		try:
			return int(value)
		except (TypeError, ValueError):
			return fallback

	current_year = timezone.now().year
	start_year = _to_int(request.GET.get("start_year"), current_year - 4)
	end_year = _to_int(request.GET.get("end_year"), current_year)
	if start_year > end_year:
		start_year, end_year = end_year, start_year

	certificates = Certificate.objects.filter(
		issued_date__year__gte=start_year,
		issued_date__year__lte=end_year,
	).order_by("-issued_date", "certificate_number")

	response = HttpResponse(content_type="application/pdf")
	response["Content-Disposition"] = 'attachment; filename="certificate_log_export.pdf"'

	pdf = canvas.Canvas(response, pagesize=A4)
	width, height = A4

	y = height - 40
	pdf.setFont("Helvetica-Bold", 14)
	pdf.drawString(40, y, "Certificate Log Report")
	y -= 22
	pdf.setFont("Helvetica", 10)
	pdf.drawString(40, y, f"Report Range: {start_year}-{end_year}")
	y -= 14
	pdf.drawString(40, y, f"Generated On: {timezone.localdate().isoformat()}")
	y -= 24

	pdf.setFont("Helvetica-Bold", 10)
	pdf.drawString(40, y, "Certificate #")
	pdf.drawString(170, y, "Service")
	pdf.drawString(260, y, "Issued Date")
	pdf.drawString(340, y, "Status")
	pdf.drawString(410, y, "Design")
	y -= 14
	pdf.line(40, y, width - 40, y)
	y -= 14

	pdf.setFont("Helvetica", 9)
	if not certificates.exists():
		pdf.drawString(40, y, "No certificate records found for selected range.")
	else:
		for certificate in certificates:
			if y < 50:
				pdf.showPage()
				y = height - 40
				pdf.setFont("Helvetica-Bold", 10)
				pdf.drawString(40, y, "Certificate #")
				pdf.drawString(170, y, "Service")
				pdf.drawString(260, y, "Issued Date")
				pdf.drawString(340, y, "Status")
				pdf.drawString(410, y, "Design")
				y -= 14
				pdf.line(40, y, width - 40, y)
				y -= 14
				pdf.setFont("Helvetica", 9)

			status_text = "Valid" if certificate.is_valid else "Revoked"
			design_name = certificate.design_template or "-"
			if len(design_name) > 22:
				design_name = f"{design_name[:19]}..."

			pdf.drawString(40, y, certificate.certificate_number)
			pdf.drawString(170, y, certificate.service_type)
			pdf.drawString(260, y, str(certificate.issued_date))
			pdf.drawString(340, y, status_text)
			pdf.drawString(410, y, design_name)
			y -= 13

	pdf.save()
	return response


@login_required
@member_required
def member_profile(request):
	member_account = request.user.member_account
	person = member_account.person
	if request.method == "POST":
		action = request.POST.get("action", "account")
		if action == "password":
			new_password = request.POST.get("new_password", "")
			confirm_password = request.POST.get("confirm_password", "")

			if not new_password or not confirm_password:
				messages.error(request, "New password and confirmation are required.")
				return redirect("member_profile")
			if len(new_password) < 8:
				messages.error(request, "New password must be at least 8 characters.")
				return redirect("member_profile")
			if new_password != confirm_password:
				messages.error(request, "New password and confirmation do not match.")
				return redirect("member_profile")
			if request.user.check_password(new_password):
				messages.error(request, "New password must be different from current password.")
				return redirect("member_profile")

			request.user.set_password(new_password)
			request.user.save(update_fields=["password"])
			update_session_auth_hash(request, request.user)
			messages.success(request, "Password updated successfully.")
			return redirect("member_profile")

		if action == "account":
			username = request.POST.get("username", "").strip()
			email = request.POST.get("email", "").strip()
			if not username:
				messages.error(request, "Username is required.")
				return redirect("member_profile")
			if User.objects.filter(username=username).exclude(id=request.user.id).exists():
				messages.error(request, "Username is already taken.")
				return redirect("member_profile")
			email_error = _validate_email_value(email)
			if email_error:
				messages.error(request, email_error)
				return redirect("member_profile")

			request.user.username = username
			request.user.email = email
			request.user.save(update_fields=["username", "email"])
			person.email = email
			person.save(update_fields=["email", "updated_at"])
			messages.success(request, "Account details updated.")
			return redirect("member_profile")

		if action == "personal":
			first_name = request.POST.get("first_name", "").strip()
			last_name = request.POST.get("last_name", "").strip()
			gender = request.POST.get("gender", "").strip()
			dob_value, dob_error = _parse_date(request.POST.get("date_of_birth", "").strip(), "Date of birth")
			if not first_name or not last_name or not gender or dob_error:
				messages.error(request, dob_error or "First name, last name, gender and date of birth are required.")
				return redirect("member_profile")
			if dob_value and dob_value > timezone.localdate():
				messages.error(request, "Date of birth cannot be in the future.")
				return redirect("member_profile")

			person.first_name = first_name
			person.last_name = last_name
			person.gender = gender
			person.date_of_birth = dob_value
			person.save(update_fields=["first_name", "last_name", "gender", "date_of_birth", "updated_at"])

			request.user.first_name = first_name
			request.user.last_name = last_name
			request.user.save(update_fields=["first_name", "last_name"])
			messages.success(request, "Personal profile updated.")
			return redirect("member_profile")

		if action == "contact":
			phone = request.POST.get("phone", "").strip()
			email = request.POST.get("email", "").strip()
			address = request.POST.get("address", "").strip()
			remove_photo = request.POST.get("remove_photo") == "on"
			uploaded_photo = request.FILES.get("profile_photo")
			email_error = _validate_email_value(email)
			phone_error = _validate_phone(phone)
			if email_error or phone_error:
				messages.error(request, email_error or phone_error)
				return redirect("member_profile")

			if uploaded_photo:
				if not getattr(uploaded_photo, "content_type", "").startswith("image/"):
					messages.error(request, "Profile picture must be an image file.")
					return redirect("member_profile")
				if uploaded_photo.size > 5 * 1024 * 1024:
					messages.error(request, "Profile picture must be 5MB or smaller.")
					return redirect("member_profile")

			person.phone = phone
			person.email = email
			person.address = address
			person.save(update_fields=["phone", "email", "address", "updated_at"])

			request.user.email = email
			request.user.save(update_fields=["email"])

			if remove_photo and member_account.profile_photo:
				member_account.profile_photo.delete(save=False)
				member_account.profile_photo = ""
			if uploaded_photo:
				if member_account.profile_photo:
					member_account.profile_photo.delete(save=False)
				member_account.profile_photo = uploaded_photo
			member_account.save()

			messages.success(request, "Contact information updated.")
			return redirect("member_profile")

		messages.error(request, "Invalid action.")
		return redirect("member_profile")
	return render(
		request,
		"member/profile.html",
		{
			"person": person,
			"member_account": member_account,
			"gender_choices": Person.GENDER_CHOICES,
		},
	)


@login_required
@member_required
def member_baptism_request(request):
	person = request.user.member_account.person
	existing = Baptism.objects.filter(person=person).first()
	available_slots = AvailableSlot.objects.filter(activity_type=AvailableSlot.ACTIVITY_BAPTISM, is_available=True).order_by("date")
	
	if request.method == "POST":
		if existing and existing.status != SacramentStatus.CANCELLED:
			messages.error(request, "You already have a baptism request/record. You can request again only if it is cancelled or removed by admin.")
			return redirect("member_dashboard")

		slot_id = request.POST.get("available_slot", "").strip()
		selected_slot = None
		
		if slot_id:
			try:
				selected_slot = AvailableSlot.objects.get(id=slot_id, activity_type=AvailableSlot.ACTIVITY_BAPTISM, is_available=True)
			except (ValueError, AvailableSlot.DoesNotExist):
				messages.error(request, "Invalid slot selected.")
				return render(request, "member/baptism_request.html", {"existing": existing, "available_slots": available_slots})
		
		if existing:
			existing.status = SacramentStatus.PENDING
			existing.available_slot = selected_slot
			existing.admin_comment = ""
			existing.save(update_fields=["status", "available_slot", "admin_comment", "updated_at"])
			baptism_obj = existing
			messages.success(request, "Baptism request resubmitted.")
		else:
			baptism_obj = Baptism.objects.create(
				person=person,
				request_date=timezone.localdate(),
				status=SacramentStatus.PENDING,
				available_slot=selected_slot,
			)
			messages.success(request, "Baptism request submitted.")
		review_url = request.build_absolute_uri(
			reverse("admin_baptism_review", kwargs={"baptism_id": baptism_obj.id})
		)
		notifications.notify_admin_new_baptism(baptism_obj, review_url)
		log(request.user, "create", ActivityLog.CAT_BAPTISM, f"{person.first_name} {person.last_name} submitted a baptism request.")
		return redirect("member_dashboard")
	
	return render(request, "member/baptism_request.html", {
		"existing": existing, 
		"available_slots": available_slots
	})


@login_required
@member_required
def member_wedding_request(request):
	"""
	Submit a wedding request. Stores non-member partner data as JSON
	and creates a WeddingRequest record with an invite code for partner consent.
	"""
	member_person = request.user.member_account.person
	member_choices = Person.objects.filter(is_member=True, is_active=True).exclude(id=member_person.id).order_by("last_name", "first_name")
	available_slots = AvailableSlot.objects.filter(
		activity_type=AvailableSlot.ACTIVITY_WEDDING,
		is_available=True,
		date__gte=timezone.localdate(),
	).order_by("date", "time")

	# Check for existing active WeddingRequest (not just old Wedding)
	active_request_exists = WeddingRequest.objects.filter(
		Q(submitter=member_person) | Q(partner=member_person),
		status__in=[SacramentStatus.PENDING, SacramentStatus.APPROVED],
	).exists()

	if request.method == "POST":
		owner_role = request.POST.get("owner_role", "").strip().lower()
		has_read = request.POST.get("has_read") == "on"
		partner_member_id = request.POST.get("partner_member_id", "").strip()
		couple_photo = request.FILES.get("couple_photo")

		if active_request_exists:
			messages.error(request, "You already have an active wedding request.")
			return redirect("member_dashboard")
		if not has_read:
			messages.error(request, "Please read and acknowledge the process before submitting.")
			return render(request, "member/wedding_request.html", {
				"member_choices": member_choices, 
				"available_slots": available_slots,
				"active_request_exists": active_request_exists
			})
		if owner_role not in {"groom", "bride"}:
			messages.error(request, "Select whether you are the groom or the bride.")
			return render(request, "member/wedding_request.html", {
				"member_choices": member_choices, 
				"available_slots": available_slots,
				"active_request_exists": active_request_exists
			})

		partner = None
		partner_is_member = bool(partner_member_id)
		partner_non_member_data = {}
		partner_gender_expected = "Female" if owner_role == "groom" else "Male"

		if partner_member_id:
			try:
				partner = Person.objects.get(id=partner_member_id, is_member=True, is_active=True)
			except (ValueError, Person.DoesNotExist):
				partner = None
			if not partner:
				messages.error(request, "Select a valid church member partner or provide non-member details.")
				return render(request, "member/wedding_request.html", {
					"member_choices": member_choices, 
					"available_slots": available_slots,
					"active_request_exists": active_request_exists
				})
			if partner.id == member_person.id:
				messages.error(request, "You cannot submit a wedding request with yourself as both groom and bride.")
				return render(request, "member/wedding_request.html", {
					"member_choices": member_choices, 
					"available_slots": available_slots,
					"active_request_exists": active_request_exists
				})
		else:
			partner_first_name = request.POST.get("partner_first_name", "").strip()
			partner_last_name = request.POST.get("partner_last_name", "").strip()
			partner_gender = request.POST.get("partner_gender", "").strip()
			partner_dob, partner_dob_error = _parse_date(request.POST.get("partner_date_of_birth", ""), "Partner date of birth")
			partner_phone = request.POST.get("partner_phone", "").strip()
			partner_email = request.POST.get("partner_email", "").strip()
			partner_address = request.POST.get("partner_address", "").strip()
			partner_church_name = request.POST.get("partner_church_name", "").strip()
			partner_province = request.POST.get("partner_province", "").strip()
			partner_district = request.POST.get("partner_district", "").strip()
			partner_sector = request.POST.get("partner_sector", "").strip()
			partner_cell = request.POST.get("partner_cell", "").strip()
			partner_village = request.POST.get("partner_village", "").strip()

			if (
				not partner_first_name or not partner_last_name or not partner_gender
				or partner_dob_error or not partner_church_name
				or not partner_province or not partner_district or not partner_sector
				or not partner_cell or not partner_village
			):
				messages.error(
					request,
					partner_dob_error
					or "Complete non-member partner details, including church and full location (province, district, sector, cell, village).",
				)
				return render(request, "member/wedding_request.html", {
					"member_choices": member_choices, 
					"available_slots": available_slots,
					"active_request_exists": active_request_exists
				})
			if partner_dob > timezone.localdate():
				messages.error(request, "Partner date of birth cannot be in the future.")
				return render(request, "member/wedding_request.html", {
					"member_choices": member_choices, 
					"available_slots": available_slots,
					"active_request_exists": active_request_exists
				})
			email_error = _validate_email_value(partner_email)
			phone_error = _validate_phone(partner_phone)
			if email_error or phone_error:
				messages.error(request, email_error or phone_error)
				return render(request, "member/wedding_request.html", {
					"member_choices": member_choices, 
					"available_slots": available_slots,
					"active_request_exists": active_request_exists
				})

			partner_non_member_data = {
				"first_name": partner_first_name,
				"last_name": partner_last_name,
				"gender": partner_gender,
				"date_of_birth": partner_dob.isoformat(),
				"phone": partner_phone,
				"email": partner_email,
				"address": partner_address,
				"church_name": partner_church_name,
				"province": partner_province,
				"district": partner_district,
				"sector": partner_sector,
				"cell": partner_cell,
				"village": partner_village,
			}
			# Create a Person record so the partner is trackable in the People table
			partner = Person.objects.create(
				first_name=partner_first_name,
				last_name=partner_last_name,
				gender=partner_gender,
				date_of_birth=partner_dob,
				phone=partner_phone,
				email=partner_email,
				address=partner_address,
				province=partner_province,
				district=partner_district,
				sector=partner_sector,
				cell=partner_cell,
				village=partner_village,
				is_member=False,
				is_visitor=False,
				is_child_profile=False,
			)

		submitter_health_document = request.FILES.get("submitter_health_document")

		# Resolve requested slot (optional — member may not have selected one)
		requested_slot = None
		slot_id = request.POST.get("available_slot", "").strip()
		if slot_id:
			try:
				requested_slot = AvailableSlot.objects.get(
					id=slot_id,
					activity_type=AvailableSlot.ACTIVITY_WEDDING,
					is_available=True,
				)
			except (ValueError, AvailableSlot.DoesNotExist):
				requested_slot = None

		wrequest = WeddingRequest.objects.create(
			submitter=member_person,
			partner=partner,
			partner_is_member=partner_is_member,
			partner_non_member_data=partner_non_member_data,
			partner_gender_expected=partner_gender_expected,
			available_slot=requested_slot,
			submitter_role=owner_role,
			couple_photo=couple_photo,
			submitter_health_document=submitter_health_document,
			status=SacramentStatus.PENDING,
		)
		invite_url = request.build_absolute_uri(
			reverse("member_wedding_consent", kwargs={"invite_code": wrequest.partner_invite_code})
		)
		review_url = request.build_absolute_uri(
			reverse("admin_wedding_request_review", kwargs={"request_id": wrequest.id})
		)
		notifications.send_partner_invite(wrequest, invite_url)
		notifications.notify_admin_new_wedding_request(wrequest, review_url)
		log(request.user, "create", ActivityLog.CAT_WEDDING, f"{member_person.first_name} {member_person.last_name} submitted a wedding request.")
		messages.success(
			request,
			"Wedding request submitted! "
			+ ("Your partner will receive an invite to confirm." if partner_is_member else "Admin will review your request.")
		)
		return redirect("member_wedding_status", request_id=wrequest.id)

	return render(request, "member/wedding_request.html", {
		"member_choices": member_choices, 
		"available_slots": available_slots,
		"active_request_exists": active_request_exists,
	})


@login_required
@member_required
def member_wedding_status(request, request_id):
	"""Show the status of a wedding request and the invite link for partner."""
	wrequest = get_object_or_404(WeddingRequest, id=request_id)
	member_person = request.user.member_account.person

	if wrequest.submitter != member_person and wrequest.partner != member_person:
		raise Http404

	invite_url = request.build_absolute_uri(
		reverse("member_wedding_consent", kwargs={"invite_code": wrequest.partner_invite_code})
	)

	is_submitter = wrequest.submitter == member_person
	return render(request, "member/wedding_status.html", {
		"wrequest": wrequest,
		"invite_url": invite_url,
		"can_edit": is_submitter and wrequest.status == SacramentStatus.PENDING,
		"can_cancel": is_submitter and wrequest.status == SacramentStatus.PENDING,
		"can_resubmit": is_submitter and wrequest.status in [SacramentStatus.REJECTED, SacramentStatus.CANCELLED],
		"show_application_form": wrequest.status == SacramentStatus.APPROVED,
	})


@login_required
@member_required
def member_wedding_cancel(request, request_id):
	"""Member cancels their own pending wedding request."""
	if request.method != "POST":
		return redirect("member_wedding_status", request_id=request_id)

	wrequest = get_object_or_404(WeddingRequest, id=request_id)
	member_person = request.user.member_account.person
	if wrequest.submitter != member_person:
		raise Http404

	if wrequest.status != SacramentStatus.PENDING:
		messages.error(request, "This request cannot be removed in its current status.")
		return redirect("member_wedding_status", request_id=request_id)

	wrequest_id = wrequest.id
	notifications.notify_admin_wedding_cancelled(wrequest)
	log(request.user, "cancel", ActivityLog.CAT_WEDDING, f"Member removed wedding request {wrequest_id}")
	wrequest.delete()
	messages.success(request, "Your wedding request has been removed.")
	return redirect("member_dashboard")


@login_required
@member_required
def member_wedding_edit(request, request_id):
	"""Member edits their pending wedding request (slot, photo, health docs)."""
	wrequest = get_object_or_404(WeddingRequest, id=request_id)
	member_person = request.user.member_account.person
	if wrequest.submitter != member_person:
		raise Http404

	if wrequest.status != SacramentStatus.PENDING:
		messages.error(request, "You can only edit a request while it is pending.")
		return redirect("member_wedding_status", request_id=request_id)

	available_slots = AvailableSlot.objects.filter(
		activity_type=AvailableSlot.ACTIVITY_WEDDING,
		is_available=True,
	).order_by("date", "time")

	member_choices = Person.objects.filter(is_member=True, is_active=True).exclude(id=member_person.id).order_by("last_name", "first_name")

	if request.method == "POST":
		slot_id = request.POST.get("available_slot") or None
		slot = None
		if slot_id:
			slot = AvailableSlot.objects.filter(id=slot_id, activity_type=AvailableSlot.ACTIVITY_WEDDING, is_available=True).first()

		qs_update = {"updated_at": timezone.now(), "available_slot": slot}

		# --- Partner editing ---
		if not wrequest.partner_is_member:
			# Non-member partner: update JSON data + the linked Person record
			p_first = request.POST.get("partner_first_name", "").strip()
			p_last = request.POST.get("partner_last_name", "").strip()
			p_gender = request.POST.get("partner_gender", "").strip()
			p_dob_raw = request.POST.get("partner_date_of_birth", "").strip()
			p_phone = request.POST.get("partner_phone", "").strip()
			p_email = request.POST.get("partner_email", "").strip()
			p_address = request.POST.get("partner_address", "").strip()
			p_church = request.POST.get("partner_church_name", "").strip()
			p_province = request.POST.get("partner_province", "").strip()
			p_district = request.POST.get("partner_district", "").strip()
			p_sector = request.POST.get("partner_sector", "").strip()
			p_cell = request.POST.get("partner_cell", "").strip()
			p_village = request.POST.get("partner_village", "").strip()

			p_dob, p_dob_error = _parse_date(p_dob_raw, "Partner date of birth")
			email_err = _validate_email_value(p_email) if p_email else None
			phone_err = _validate_phone(p_phone) if p_phone else None

			if p_dob_error or email_err or phone_err:
				messages.error(request, p_dob_error or email_err or phone_err)
				return render(request, "member/wedding_edit.html", {
					"wrequest": wrequest,
					"available_slots": available_slots,
					"member_choices": member_choices,
				})

			if p_first and p_last:
				new_json = dict(wrequest.partner_non_member_data)
				new_json.update({
					"first_name": p_first,
					"last_name": p_last,
					"gender": p_gender,
					"date_of_birth": p_dob.isoformat() if p_dob else new_json.get("date_of_birth", ""),
					"phone": p_phone,
					"email": p_email,
					"address": p_address,
					"church_name": p_church,
					"province": p_province,
					"district": p_district,
					"sector": p_sector,
					"cell": p_cell,
					"village": p_village,
				})
				qs_update["partner_non_member_data"] = new_json
				# Also update the Person record that was created for the non-member partner
				if wrequest.partner_id:
					Person.objects.filter(id=wrequest.partner_id).update(
						first_name=p_first,
						last_name=p_last,
						gender=p_gender,
						date_of_birth=p_dob if p_dob else wrequest.partner.date_of_birth,
						phone=p_phone,
						email=p_email,
						address=p_address,
						province=p_province,
						district=p_district,
						sector=p_sector,
						cell=p_cell,
						village=p_village,
					)
		else:
			# Member partner: allow swapping if partner hasn't consented yet
			if not wrequest.partner_consented:
				new_partner_id = request.POST.get("partner_member_id", "").strip()
				if new_partner_id and new_partner_id != str(wrequest.partner_id):
					try:
						new_partner = Person.objects.get(id=new_partner_id, is_member=True, is_active=True)
						if new_partner.id != member_person.id:
							qs_update["partner"] = new_partner
					except Person.DoesNotExist:
						pass

		WeddingRequest.objects.filter(id=wrequest.id).update(**qs_update)

		wrequest.refresh_from_db()
		from django.db.models import Model as _Model
		if "couple_photo" in request.FILES:
			wrequest.couple_photo = request.FILES["couple_photo"]
			_Model.save(wrequest, update_fields=["couple_photo"])
		if "submitter_health_document" in request.FILES:
			wrequest.submitter_health_document = request.FILES["submitter_health_document"]
			_Model.save(wrequest, update_fields=["submitter_health_document"])
		if "partner_health_document" in request.FILES:
			wrequest.partner_health_document = request.FILES["partner_health_document"]
			_Model.save(wrequest, update_fields=["partner_health_document"])

		messages.success(request, "Your wedding request has been updated.")
		return redirect("member_wedding_status", request_id=wrequest.id)

	return render(request, "member/wedding_edit.html", {
		"wrequest": wrequest,
		"available_slots": available_slots,
		"member_choices": member_choices,
	})


@login_required
@member_required
def member_wedding_resubmit(request, request_id):
	"""Member resubmits a rejected or cancelled wedding request."""
	if request.method != "POST":
		return redirect("member_wedding_status", request_id=request_id)

	wrequest = get_object_or_404(WeddingRequest, id=request_id)
	member_person = request.user.member_account.person
	if wrequest.submitter != member_person:
		raise Http404

	if wrequest.status not in [SacramentStatus.REJECTED, SacramentStatus.CANCELLED]:
		messages.error(request, "This request cannot be resubmitted in its current status.")
		return redirect("member_wedding_status", request_id=request_id)

	WeddingRequest.objects.filter(id=wrequest.id).update(
		status=SacramentStatus.PENDING,
		updated_at=timezone.now(),
	)
	review_url = request.build_absolute_uri(
		reverse("admin_wedding_request_review", kwargs={"request_id": wrequest.id})
	)
	notifications.notify_admin_new_wedding_request(wrequest, review_url)
	notify_member(wrequest.submitter, MemberNotification.CAT_WEDDING,
		"Your wedding request has been resubmitted and is under review.")
	log(request.user, "create", ActivityLog.CAT_WEDDING, f"Member resubmitted wedding request {wrequest.id}")
	messages.success(request, "Your wedding request has been resubmitted for review.")
	return redirect("member_wedding_status", request_id=wrequest.id)


@login_required
def member_wedding_consent(request, invite_code):
	"""
	Partner consent view. The partner opens this via the invite link,
	confirms they want to marry, and uploads their health document.
	"""
	wrequest = get_object_or_404(WeddingRequest, partner_invite_code=invite_code)

	if wrequest.partner_consented:
		messages.info(request, "You have already confirmed this wedding request.")
		return redirect("member_dashboard")

	if request.method == "POST":
		agree = request.POST.get("agree") == "on"
		if not agree:
			messages.error(request, "You must confirm your agreement to proceed.")
			return render(request, "member/wedding_consent.html", {"wrequest": wrequest})

		partner_health = request.FILES.get("partner_health_document")
		if partner_health:
			wrequest.partner_health_document = partner_health

		wrequest.partner_consented = True
		wrequest.partner_consented_at = timezone.now()
		wrequest.save()
		messages.success(request, "Thank you! You have confirmed your participation. The request will now be reviewed by admin.")
		return redirect("member_dashboard")

	return render(request, "member/wedding_consent.html", {"wrequest": wrequest})


@login_required
@member_required
def member_dedication_request(request):
	member_person = request.user.member_account.person
	available_slots = AvailableSlot.objects.filter(activity_type=AvailableSlot.ACTIVITY_DEDICATION, is_available=True).order_by("date")
	
	if request.method == "POST":
		child_first = request.POST.get("child_first_name", "").strip()
		child_last = request.POST.get("child_last_name", "").strip()
		child_gender = request.POST.get("child_gender", "").strip()
		child_dob, child_error = _parse_date(request.POST.get("child_date_of_birth", ""), "Child date of birth")
		father_name = request.POST.get("father_name", "").strip()
		mother_name = request.POST.get("mother_name", "").strip()
		scripture_reference = request.POST.get("scripture_reference", "").strip()
		scripture_text = request.POST.get("scripture_text", "").strip()
		slot_id = request.POST.get("available_slot", "").strip()

		if not child_first or not child_last or not child_gender or child_error or not father_name or not mother_name or not scripture_reference or not scripture_text:
			messages.error(request, child_error or "All fields are required, including scripture and verse.")
			return render(request, "member/dedication_request.html", {"available_slots": available_slots})
		if child_dob and child_dob > timezone.localdate():
			messages.error(request, "Child date of birth cannot be in the future.")
			return render(request, "member/dedication_request.html", {"available_slots": available_slots})
		if father_name.strip().lower() == mother_name.strip().lower():
			messages.error(request, "Father and mother names must be different.")
			return render(request, "member/dedication_request.html", {"available_slots": available_slots})

		# Validate slot if provided
		selected_slot = None
		if slot_id:
			try:
				selected_slot = AvailableSlot.objects.get(id=slot_id, activity_type=AvailableSlot.ACTIVITY_DEDICATION, is_available=True)
			except (ValueError, AvailableSlot.DoesNotExist):
				messages.error(request, "Invalid slot selected.")
				return render(request, "member/dedication_request.html", {"available_slots": available_slots})

		father_parts = father_name.split(" ", 1)
		mother_parts = mother_name.split(" ", 1)
		member_full_name = f"{member_person.first_name} {member_person.last_name}".strip().lower()
		father_full_name = f"{father_parts[0]} {father_parts[1] if len(father_parts) > 1 else ''}".strip().lower()
		mother_full_name = f"{mother_parts[0]} {mother_parts[1] if len(mother_parts) > 1 else ''}".strip().lower()

		if father_full_name == member_full_name:
			father = member_person
		else:
			father = Person.objects.create(
				first_name=father_parts[0],
				last_name=father_parts[1] if len(father_parts) > 1 else "",
				gender="Male",
				date_of_birth=date(1990, 1, 1),
				is_member=False,
			)

		if mother_full_name == member_full_name:
			mother = member_person
		else:
			mother = Person.objects.create(
				first_name=mother_parts[0],
				last_name=mother_parts[1] if len(mother_parts) > 1 else "",
				gender="Female",
				date_of_birth=date(1990, 1, 1),
				is_member=False,
			)
		child = Person.objects.create(
			first_name=child_first,
			last_name=child_last,
			gender=child_gender,
			date_of_birth=child_dob,
			is_member=False,
			is_child_profile=True,
		)
		ded = BabyDedication.objects.create(
			child=child,
			father=father,
			mother=mother,
			scripture_reference=scripture_reference,
			scripture_text=scripture_text,
			request_date=timezone.localdate(),
			available_slot=selected_slot,
		)
		review_url = request.build_absolute_uri(
			reverse("admin_dedication_review", kwargs={"dedication_id": ded.id})
		)
		notifications.notify_admin_new_dedication(ded, review_url)
		log(request.user, "create", ActivityLog.CAT_DEDICATION, f"{member_person.first_name} {member_person.last_name} submitted a dedication request for {child_first} {child_last}.")
		messages.success(request, "Dedication request submitted.")
		return redirect("member_dashboard")
	
	return render(request, "member/dedication_request.html", {"available_slots": available_slots})


@login_required
@member_required
def member_dedication_edit(request, dedication_id):
	person = request.user.member_account.person
	dedication = get_object_or_404(
		BabyDedication.objects.select_related("child", "father", "mother"),
		id=dedication_id,
		status=SacramentStatus.REJECTED,
	)
	if person not in [dedication.father, dedication.mother] and not request.user.is_staff:
		raise Http404

	if request.method == "POST":
		child_first = request.POST.get("child_first_name", "").strip()
		child_last = request.POST.get("child_last_name", "").strip()
		scripture_reference = request.POST.get("scripture_reference", "").strip()
		scripture_text = request.POST.get("scripture_text", "").strip()
		if not child_first or not child_last or not scripture_reference or not scripture_text:
			messages.error(request, "Child name, scripture reference, and scripture verse are required.")
			return redirect("member_dedication_edit", dedication_id=dedication.id)
		dedication.child.first_name = child_first
		dedication.child.last_name = child_last
		dedication.child.save(update_fields=["first_name", "last_name", "updated_at"])
		dedication.scripture_reference = scripture_reference
		dedication.scripture_text = scripture_text
		dedication.status = SacramentStatus.PENDING
		dedication.admin_comment = ""
		dedication.save(update_fields=["scripture_reference", "scripture_text", "status", "admin_comment", "updated_at"])
		messages.success(request, "Dedication request resubmitted.")
		return redirect("member_dashboard")
	return render(request, "member/dedication_edit.html", {"item": dedication})


def _member_certificates(person):
	baptism_ids = list(Baptism.objects.filter(person=person).values_list("id", flat=True))
	dedication_ids = list(BabyDedication.objects.filter(Q(father=person) | Q(mother=person)).values_list("id", flat=True))
	wedding_ids = list(Wedding.objects.filter(Q(groom=person) | Q(bride=person)).values_list("id", flat=True))

	return Certificate.objects.filter(
		Q(service_type=Certificate.BAPTISM, object_id__in=baptism_ids)
		| Q(service_type=Certificate.DEDICATION, object_id__in=dedication_ids)
		| Q(service_type=Certificate.WEDDING, object_id__in=wedding_ids)
	).order_by("-issued_date")


@method_decorator([login_required, member_required], name="dispatch")
class MemberCertificateListView(TemplateView):
	template_name = "member/certificate_list.html"

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		certificates = _member_certificates(self.request.user.member_account.person)
		paginator = Paginator(certificates, 10)
		context["page_obj"] = paginator.get_page(self.request.GET.get("page"))
		context["page_query"] = _query_without_page(self.request)
		return context


@login_required
@member_required
def member_notifications(request):
	MemberNotification.objects.filter(user=request.user, is_read=False).update(is_read=True)
	qs = MemberNotification.objects.filter(user=request.user)
	paginator = Paginator(qs, 20)
	return render(request, "member/notifications.html", {
		"page_obj": paginator.get_page(request.GET.get("page")),
	})


@login_required
@member_required
def member_mark_notifications_read(request):
	if request.method == "POST":
		MemberNotification.objects.filter(user=request.user, is_read=False).update(is_read=True)
	return redirect(request.POST.get("next") or "member_dashboard")


@login_required
@member_required
def member_baptism_status(request):
	person = request.user.member_account.person
	baptism = get_object_or_404(Baptism, person=person)
	latest_certificate = (
		Certificate.objects.filter(service_type=Certificate.BAPTISM, object_id=baptism.id)
		.exclude(certificate_file="")
		.order_by("-issued_date", "-created_at")
		.first()
	)
	return render(request, "member/baptism_status.html", {
		"baptism": baptism,
		"latest_certificate": latest_certificate,
	})


@login_required
@member_required
def member_dedication_status(request, dedication_id):
	person = request.user.member_account.person
	dedication = get_object_or_404(
		BabyDedication,
		id=dedication_id,
	)
	if dedication.father != person and dedication.mother != person:
		raise Http404
	latest_certificate = (
		Certificate.objects.filter(service_type=Certificate.DEDICATION, object_id=dedication.id)
		.exclude(certificate_file="")
		.order_by("-issued_date", "-created_at")
		.first()
	)
	return render(request, "member/dedication_status.html", {
		"dedication": dedication,
		"latest_certificate": latest_certificate,
	})


def verify_certificate(request, certificate_number):
	certificate = Certificate.objects.filter(certificate_number=certificate_number).first()
	if not certificate:
		return render(request, "public/verify_result.html", {"not_found": True})

	linked = certificate.linked_object
	names = ""
	service_date = None
	if certificate.service_type == Certificate.BAPTISM and linked:
		names = str(linked.person)
		service_date = linked.baptism_date
	elif certificate.service_type == Certificate.DEDICATION and linked:
		names = str(linked.child)
		service_date = linked.dedication_date
	elif certificate.service_type == Certificate.WEDDING and linked:
		names = f"{linked.groom} & {linked.bride}"
		service_date = linked.wedding_date

	return render(
		request,
		"public/verify_result.html",
		{
			"certificate": certificate,
			"service_type": certificate.service_type,
			"names": names,
			"service_date": service_date,
			"status": "Valid" if certificate.is_valid else "Revoked",
		},
	)


# ---------------------------------------------------------------------------
# Notifications / Activity Log
# ---------------------------------------------------------------------------

@method_decorator([login_required, staff_required], name="dispatch")
class NotificationListView(TemplateView):
	template_name = "admin/notifications.html"

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		cat = self.request.GET.get("cat", "all")
		qs = ActivityLog.objects.select_related("actor").all()
		if cat != "all":
			qs = qs.filter(category=cat)
		paginator = Paginator(qs, 30)
		context["page_obj"] = paginator.get_page(self.request.GET.get("page"))
		context["active_cat"] = cat
		context["categories"] = ActivityLog.CATEGORY_CHOICES
		context["unread_total"] = ActivityLog.objects.filter(is_read=False).count()
		return context


@login_required
@staff_required
def mark_notifications_read(request):
	if request.method == "POST":
		ActivityLog.objects.filter(is_read=False).update(is_read=True)
	return redirect(request.POST.get("next", "admin_notifications"))
