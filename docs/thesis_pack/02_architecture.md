# 02 — System Architecture

## Architecture Style
The system follows a server-rendered Django monolith pattern with layered responsibilities:

1. Presentation Layer
   - Django templates (`templates/`)
   - Bootstrap styling + Chart.js visualization

2. Application Layer
   - Request handling and business actions in `base/views.py`
   - Access control decorators in `base/decorators.py`
   - Reporting/certificate services in `base/services/`

3. Domain/Data Layer
   - ORM models in `base/models.py`
   - SQLite database (`db.sqlite3`)

4. Document Generation Layer
   - ReportLab PDF generation
   - QR code image generation for certificate verification URLs

## Routing and Module Composition
- Project root routes: `baby_dedication/urls.py`
- App routes: `base/urls.py`
- Primary app logic: `base/views.py`
- Certificate generation service: `base/services/certificates.py`
- AI-like report/chat logic: `base/services/ai_reports.py`

## Access Control Model
- `staff_required`: allows only authenticated staff/admin users.
- `member_required`: allows members with `MemberAccount`; staff can pass through for controlled cases.
- Login redirects user by role to admin or member dashboard.

## Request Lifecycle (Typical)
1. User sends HTTP request to a route.
2. View validates authentication/authorization.
3. View validates form inputs and business conditions.
4. ORM persists/retrieves records from SQLite.
5. Optional service call performs PDF/report generation.
6. System returns rendered template, file response, JSON response, or redirect.

## Deployment Note for Thesis
Current settings are development-oriented (`DEBUG=True`, SQLite, local media/static) and should be hardened for production.
