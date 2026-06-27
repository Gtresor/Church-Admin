# 04 — User Workflows

## A. Admin Workflow

1. Login
   - Admin authenticates and lands on admin dashboard.

2. Member/Kid/Officiant Management
   - Create, edit, activate/deactivate, or delete entities.
   - Deletion gracefully falls back to deactivation when historical references exist.

3. Sacrament Processing
   - Baptism: create request or register directly; review and update status.
   - Dedication: review child/family/request details; approve/schedule/complete lifecycle.
   - Wedding: create request, validate participants/docs, schedule and complete.

4. Certificate Operations
   - Generate certificate PDF (service-specific design templates).
   - Assign/refresh QR code for public verification.
   - Revoke certificate with mandatory reason.

5. Monitoring and Reporting
   - Dashboard cards, upcoming services, and recent activity.
   - Calendar event view for sacrament schedules.
   - Analytics reports with charts and export options (CSV/PDF).

## B. Member Workflow

1. Registration/Login
   - Member self-registration is matched to an active pre-existing member record.

2. Profile Management
   - Update account, personal, and contact details.
   - Change password and profile photo.

3. Service Requests
   - Submit baptism request.
   - Submit dedication request with child and scripture details.
   - Submit wedding request with member/non-member partner handling.

4. Request Follow-Up
   - View statuses on dashboard.
   - Re-submit rejected dedication request after corrections.

5. Certificate Access
   - View personal certificate list linked by ownership relationship.

## C. Public Verification Workflow
1. Public user opens `/verify/<certificate_number>/`.
2. System checks existence and validity status.
3. Result page displays service type, names, service date, and valid/revoked state.
