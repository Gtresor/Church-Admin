# 05 — Business Rules and Validation Logic

## Authentication and Authorization Rules
- Unauthenticated users are redirected to login.
- Staff-only endpoints are guarded by `staff_required`.
- Member endpoints require linked `MemberAccount` via `member_required`.

## Core Data Validation Rules
- Required fields are validated before persistence.
- Date fields must be valid and often cannot be in the future/past depending on context.
- Email values are format-validated.
- Phone values accept only constrained character patterns.
- Uploaded health documents for weddings:
  - Required for both groom and bride in admin wedding creation.
  - Type restricted to PDF/PNG/JPG.
  - Size restricted to <= 5MB.

## Workflow State Rules

### Baptism
- Can be approved/rejected/cancelled/scheduled/completed through review actions.
- Scheduling requires a valid future date and selected officiant.
- Certificate generation requires baptism date.

### Baby Dedication
- Approval/rejection accepted only from pending state.
- Scheduling accepted only from approved state.
- Completion accepted only from scheduled state.
- Scheduling requires future date and selected officiant.
- Certificate generation allowed only when scheduled/completed and date exists.

### Wedding
- Approval allowed from pending/rejected.
- Rejection allowed from pending/approved with required reason.
- Scheduling requires future date and selected officiant.
- Completion can be marked in review.
- Marriage resolution can be marked as divorced or annulled.

## Historical Record Integrity Rules
- Sacrament and certificate records are non-deletable by design.
- If a linked profile cannot be deleted due to references, system deactivates it instead.
- Certificate revocation requires mandatory reason and preserves history.
