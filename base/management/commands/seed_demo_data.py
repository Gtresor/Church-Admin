from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from base.models import BabyDedication, Baptism, MemberAccount, Officiant, Person, SacramentStatus, Wedding
from base.services.certificates import (
    generate_baptism_certificate,
    generate_dedication_certificate,
    generate_wedding_certificate,
)


class Command(BaseCommand):
    help = "Seed realistic demo data for Church Sacramental & Member Management System"

    def handle(self, *args, **options):
        admin_user, _ = User.objects.get_or_create(
            username="admin",
            defaults={"email": "admin@example.com", "is_staff": True, "is_superuser": True},
        )
        admin_user.is_staff = True
        admin_user.is_superuser = True
        admin_user.set_password("Admin@12345")
        admin_user.save()

        john = self._create_member(
            username="john.member",
            password="Member@123",
            first_name="John",
            last_name="Mensah",
            gender="Male",
            dob=date(1993, 5, 14),
            phone="+233201234567",
            email="john@example.com",
            address="Accra, Ghana",
        )
        mary = self._create_member(
            username="mary.member",
            password="Member@123",
            first_name="Mary",
            last_name="Owusu",
            gender="Female",
            dob=date(1995, 8, 22),
            phone="+233209876543",
            email="mary@example.com",
            address="Kumasi, Ghana",
        )

        today = timezone.localdate()
        officiant_baptism, _ = Officiant.objects.get_or_create(name="Samuel Boateng", defaults={"title": "Rev."})
        officiant_dedication, _ = Officiant.objects.get_or_create(name="Grace Adjei", defaults={"title": "Pastor"})
        officiant_wedding, _ = Officiant.objects.get_or_create(name="K. Nyarko", defaults={"title": "Bishop"})

        baptism, _ = Baptism.objects.get_or_create(
            person=john,
            defaults={
                "request_date": today - timedelta(days=15),
                "status": SacramentStatus.SCHEDULED,
                "baptism_date": today + timedelta(days=7),
                "officiant": str(officiant_baptism),
            },
        )

        child, _ = Person.objects.get_or_create(
            first_name="Eliana",
            last_name="Mensah",
            gender="Female",
            date_of_birth=today - timedelta(days=280),
            defaults={"is_member": False},
        )
        dedication, _ = BabyDedication.objects.get_or_create(
            child=child,
            father=john,
            mother=mary,
            defaults={
                "request_date": today - timedelta(days=10),
                "status": SacramentStatus.SCHEDULED,
                "dedication_date": today + timedelta(days=10),
                "officiant": str(officiant_dedication),
            },
        )

        groom, _ = Person.objects.get_or_create(
            first_name="Daniel",
            last_name="Asare",
            gender="Male",
            date_of_birth=date(1991, 2, 12),
            defaults={"is_member": False},
        )
        bride, _ = Person.objects.get_or_create(
            first_name="Esi",
            last_name="Antwi",
            gender="Female",
            date_of_birth=date(1994, 11, 6),
            defaults={"is_member": False},
        )
        wedding, _ = Wedding.objects.get_or_create(
            groom=groom,
            bride=bride,
            defaults={
                "wedding_date": today + timedelta(days=30),
                "officiant": str(officiant_wedding),
                "status": SacramentStatus.SCHEDULED,
            },
        )

        if baptism.status in [SacramentStatus.COMPLETED, SacramentStatus.SCHEDULED]:
            baptism.baptism_date = baptism.baptism_date or (today - timedelta(days=2))
            baptism.status = SacramentStatus.COMPLETED
            baptism.save(update_fields=["baptism_date", "status", "updated_at"])
            generate_baptism_certificate(baptism)

        if dedication.status in [SacramentStatus.COMPLETED, SacramentStatus.SCHEDULED]:
            dedication.dedication_date = dedication.dedication_date or (today - timedelta(days=1))
            dedication.status = SacramentStatus.COMPLETED
            dedication.save(update_fields=["dedication_date", "status", "updated_at"])
            generate_dedication_certificate(dedication)

        wedding.status = SacramentStatus.COMPLETED
        wedding.save(update_fields=["status", "updated_at"])
        generate_wedding_certificate(wedding)

        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully."))
        self.stdout.write("Admin: admin / Admin@12345")
        self.stdout.write("Member: john.member / Member@123")
        self.stdout.write("Member: mary.member / Member@123")

    def _create_member(self, username, password, first_name, last_name, gender, dob, phone, email, address):
        user, _ = User.objects.get_or_create(username=username, defaults={"email": email})
        user.email = email
        user.is_staff = False
        user.is_superuser = False
        user.set_password(password)
        user.save()

        person, _ = Person.objects.get_or_create(
            first_name=first_name,
            last_name=last_name,
            gender=gender,
            date_of_birth=dob,
            defaults={
                "phone": phone,
                "email": email,
                "address": address,
                "is_member": True,
                "date_joined": timezone.localdate() - timedelta(days=365),
                "is_active": True,
            },
        )
        person.phone = phone
        person.email = email
        person.address = address
        person.is_member = True
        person.date_joined = person.date_joined or timezone.localdate() - timedelta(days=365)
        person.is_active = True
        person.save()

        MemberAccount.objects.get_or_create(user=user, person=person)
        return person
