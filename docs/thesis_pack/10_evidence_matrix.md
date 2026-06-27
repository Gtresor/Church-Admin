# 10 — Evidence Matrix (Claim-to-Code Traceability)

Use this table in your thesis writing process to keep statements evidence-based.

| Thesis Claim | Evidence Source | Notes |
|---|---|---|
| System uses Django with server-rendered templates | `baby_dedication/settings.py`, `templates/` | Django template engine configured with project-level templates directory |
| App is routed through a single base module | `baby_dedication/urls.py`, `base/urls.py` | Root includes base app routes |
| Role-based access is enforced | `base/decorators.py` | `staff_required` and `member_required` decorators |
| Core domain includes person, sacrament, certificate entities | `base/models.py` | Person, Baptism, BabyDedication, Wedding, Certificate |
| Sacrament records are protected from deletion | `base/models.py` | `ProtectedSacramentModel` + `pre_delete` signal |
| Certificates are uniquely numbered and verifiable | `base/models.py`, `base/services/certificates.py`, `base/views.py` | Unique number, QR generation, public verify endpoint |
| Admin can revoke certificates with reasons | `base/views.py` | Revocation endpoint requires reason |
| Members can submit sacrament requests | `base/views.py`, `templates/member/` | Baptism, wedding, dedication request flows |
| Admin dashboard provides operational summaries | `base/views.py`, `templates/admin/dashboard.html` | Counts, upcoming services, recents |
| Reporting and exports are available | `base/views.py`, `templates/admin/reports.html` | CSV/PDF exports for services and certificate logs |
| Internal AI assistant exists but is rule-based | `base/services/ai_reports.py`, `templates/admin/ai_reports.html` | Keyword intent matching, deterministic output |

## How to Use This Matrix
1. Before finalizing a thesis paragraph, confirm each technical sentence maps to one matrix row.
2. If a claim is not mapped, mark it as assumption or remove it.
3. Add new rows when your code changes.
