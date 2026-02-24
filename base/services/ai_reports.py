import re
from datetime import timedelta

from django.db.models import Count
from django.db.models.functions import TruncMonth
from django.utils import timezone

from base.models import BabyDedication, Baptism, Certificate, Person, SacramentStatus, Wedding


SUPPORTED_EXAMPLES = [
    "pending dedication requests",
    "members by district",
    "certificates by service type in 2026",
    "monthly baptisms in 2025",
    "upcoming scheduled services in 30 days",
]

CHAT_EXAMPLES = [
    "How many active members do we have?",
    "Show pending dedication requests",
    "How many certificates were issued this year?",
    "What services are scheduled in 30 days?",
    "Show monthly baptisms in 2025",
]


def _extract_year(prompt_text: str):
    current_year = timezone.localdate().year
    if "this year" in prompt_text:
        return current_year
    match = re.search(r"\b(20\d{2})\b", prompt_text)
    if match:
        return int(match.group(1))
    return current_year


def _extract_days(prompt_text: str):
    match = re.search(r"\b(\d{1,3})\s*day", prompt_text)
    if match:
        return max(1, int(match.group(1)))
    return 30


def _serialize_queryset_rows(queryset, columns):
    rows = []
    for item in queryset:
        row = []
        for column in columns:
            value = item.get(column, "")
            row.append("" if value is None else str(value))
        rows.append(row)
    return rows


def _report_pending_dedications():
    queryset = (
        BabyDedication.objects.filter(status=SacramentStatus.PENDING)
        .values("child__first_name", "child__last_name", "request_date", "father__last_name", "mother__last_name")
        .order_by("-request_date")
    )
    columns = ["Child First", "Child Last", "Request Date", "Father", "Mother"]
    rows = [
        [
            item["child__first_name"],
            item["child__last_name"],
            str(item["request_date"]),
            item["father__last_name"],
            item["mother__last_name"],
        ]
        for item in queryset
    ]
    return {
        "title": "Pending Dedication Requests",
        "summary": f"Found {len(rows)} pending dedication request(s).",
        "columns": columns,
        "rows": rows,
    }


def _report_members_by_district():
    queryset = (
        Person.objects.filter(is_member=True)
        .values("district")
        .annotate(total=Count("id"))
        .order_by("district")
    )
    columns = ["District", "Members"]
    rows = [[item["district"] or "Unspecified", str(item["total"])] for item in queryset]
    return {
        "title": "Members by District",
        "summary": f"Found {len(rows)} district group(s).",
        "columns": columns,
        "rows": rows,
    }


def _report_certificates_by_service_type(year):
    queryset = (
        Certificate.objects.filter(issued_date__year=year, is_valid=True)
        .values("service_type")
        .annotate(total=Count("id"))
        .order_by("service_type")
    )
    columns = ["Service Type", "Certificates"]
    rows = [[item["service_type"], str(item["total"])] for item in queryset]
    return {
        "title": f"Certificates by Service Type ({year})",
        "summary": f"Found {len(rows)} service type group(s).",
        "columns": columns,
        "rows": rows,
    }


def _report_monthly_baptisms(year):
    queryset = (
        Baptism.objects.filter(request_date__year=year)
        .annotate(month=TruncMonth("request_date"))
        .values("month")
        .annotate(total=Count("id"))
        .order_by("month")
    )
    columns = ["Month", "Requests"]
    rows = [[item["month"].strftime("%Y-%m"), str(item["total"])] for item in queryset if item["month"]]
    return {
        "title": f"Monthly Baptism Requests ({year})",
        "summary": f"Found data for {len(rows)} month(s).",
        "columns": columns,
        "rows": rows,
    }


def _report_monthly_dedications(year):
    queryset = (
        BabyDedication.objects.filter(request_date__year=year)
        .annotate(month=TruncMonth("request_date"))
        .values("month")
        .annotate(total=Count("id"))
        .order_by("month")
    )
    columns = ["Month", "Requests"]
    rows = [[item["month"].strftime("%Y-%m"), str(item["total"])] for item in queryset if item["month"]]
    return {
        "title": f"Monthly Dedication Requests ({year})",
        "summary": f"Found data for {len(rows)} month(s).",
        "columns": columns,
        "rows": rows,
    }


def _report_upcoming_services(days):
    today = timezone.localdate()
    end_date = today + timedelta(days=days)

    baptisms = (
        Baptism.objects.filter(status=SacramentStatus.SCHEDULED, baptism_date__range=(today, end_date))
        .values("baptism_date", "person__first_name", "person__last_name")
        .order_by("baptism_date")
    )
    dedications = (
        BabyDedication.objects.filter(status=SacramentStatus.SCHEDULED, dedication_date__range=(today, end_date))
        .values("dedication_date", "child__first_name", "child__last_name")
        .order_by("dedication_date")
    )
    weddings = (
        Wedding.objects.filter(status=SacramentStatus.SCHEDULED, wedding_date__range=(today, end_date))
        .values("wedding_date", "groom__first_name", "groom__last_name", "bride__first_name", "bride__last_name")
        .order_by("wedding_date")
    )

    columns = ["Service", "Date", "Subject"]
    rows = []
    rows.extend([
        ["Baptism", str(item["baptism_date"]), f"{item['person__first_name']} {item['person__last_name']}"] for item in baptisms
    ])
    rows.extend([
        ["Dedication", str(item["dedication_date"]), f"{item['child__first_name']} {item['child__last_name']}"] for item in dedications
    ])
    rows.extend([
        [
            "Wedding",
            str(item["wedding_date"]),
            f"{item['groom__first_name']} {item['groom__last_name']} & {item['bride__first_name']} {item['bride__last_name']}",
        ]
        for item in weddings
    ])
    rows.sort(key=lambda row: row[1])

    return {
        "title": f"Upcoming Scheduled Services (Next {days} Days)",
        "summary": f"Found {len(rows)} scheduled service(s) between {today} and {end_date}.",
        "columns": columns,
        "rows": rows,
    }


def generate_ai_report(prompt: str):
    prompt_text = (prompt or "").strip().lower()
    if not prompt_text:
        return {
            "matched": False,
            "title": "No Prompt Provided",
            "summary": "Enter a report request in plain language.",
            "columns": [],
            "rows": [],
            "examples": SUPPORTED_EXAMPLES,
        }

    year = _extract_year(prompt_text)
    days = _extract_days(prompt_text)

    if "pending" in prompt_text and "dedication" in prompt_text:
        result = _report_pending_dedications()
    elif "members" in prompt_text and "district" in prompt_text:
        result = _report_members_by_district()
    elif "certificate" in prompt_text and ("service" in prompt_text or "type" in prompt_text):
        result = _report_certificates_by_service_type(year)
    elif "monthly" in prompt_text and "bapt" in prompt_text:
        result = _report_monthly_baptisms(year)
    elif "monthly" in prompt_text and "dedication" in prompt_text:
        result = _report_monthly_dedications(year)
    elif "upcoming" in prompt_text or "scheduled" in prompt_text:
        result = _report_upcoming_services(days)
    else:
        return {
            "matched": False,
            "title": "Intent Not Recognized",
            "summary": "Try one of the supported report prompts.",
            "columns": [],
            "rows": [],
            "examples": SUPPORTED_EXAMPLES,
        }

    result["matched"] = True
    result["examples"] = SUPPORTED_EXAMPLES
    return result


def answer_system_chat(prompt: str):
    prompt_text = (prompt or "").strip().lower()
    if not prompt_text:
        return {
            "reply": "Ask me anything about members, sacraments, schedules, and certificates.",
            "examples": CHAT_EXAMPLES,
        }

    current_year = timezone.localdate().year

    if any(word in prompt_text for word in ["hello", "hi", "hey"]):
        return {
            "reply": "Hello. I can answer questions about this church system and generate report tables from your prompt.",
            "examples": CHAT_EXAMPLES,
        }

    if "active member" in prompt_text and ("how many" in prompt_text or "count" in prompt_text or "total" in prompt_text):
        count = Person.objects.filter(is_member=True, is_active=True).count()
        return {
            "reply": f"There are {count} active member(s) in the system.",
            "examples": CHAT_EXAMPLES,
        }

    if "member" in prompt_text and ("how many" in prompt_text or "count" in prompt_text or "total" in prompt_text):
        count = Person.objects.filter(is_member=True).count()
        return {
            "reply": f"There are {count} member record(s) in total.",
            "examples": CHAT_EXAMPLES,
        }

    if "certificate" in prompt_text and ("how many" in prompt_text or "count" in prompt_text or "total" in prompt_text):
        total = Certificate.objects.filter(issued_date__year=current_year, is_valid=True).count()
        return {
            "reply": f"There are {total} valid certificate(s) issued in {current_year}.",
            "examples": CHAT_EXAMPLES,
        }

    if "pending" in prompt_text and ("request" in prompt_text or "dedication" in prompt_text or "baptism" in prompt_text):
        pending_baptisms = Baptism.objects.filter(status=SacramentStatus.PENDING).count()
        pending_dedications = BabyDedication.objects.filter(status=SacramentStatus.PENDING).count()
        return {
            "reply": f"Pending requests: Baptisms {pending_baptisms}, Dedications {pending_dedications}.",
            "examples": CHAT_EXAMPLES,
        }

    report = generate_ai_report(prompt)
    if report.get("matched"):
        return {
            "reply": report.get("summary", "Report generated."),
            "report": {
                "title": report.get("title", "Report"),
                "columns": report.get("columns", []),
                "rows": report.get("rows", [])[:120],
            },
            "examples": CHAT_EXAMPLES,
        }

    return {
        "reply": "I did not understand that yet. Ask about members, pending requests, certificates, monthly trends, or upcoming schedules.",
        "examples": CHAT_EXAMPLES,
    }
