# 07 — Current Limitations

## Technical Limitations
1. Development configuration in project settings
   - `DEBUG=True`
   - Hard-coded secret key in settings file
   - Empty `ALLOWED_HOSTS`

2. Database choice
   - SQLite is suitable for development/small deployments but limited for high concurrency and scaling.

3. Monolithic view layer
   - Many business rules are concentrated in large view functions, which can reduce maintainability.

4. Test coverage
   - Automated tests are currently minimal/absent (`base/tests.py` placeholder).

5. File storage
   - Media files (certificates, profile photos, health documents) are stored locally, with no cloud backup strategy shown.

## Functional Limitations
1. No integrated notifications
   - No built-in email/SMS workflow notifications to members.

2. Internal AI module constraints
   - Prompt understanding is based on hard-coded keyword matching.
   - Unsupported prompts return fallback responses.

3. Deployment hardening pending
   - No explicit production deployment pipeline documented in current workspace.

## Research Limitation Statement (Draft)
Although the system demonstrates complete core workflows for church sacramental administration, its current implementation prioritizes functional completeness over production hardening, advanced automation, and large-scale performance engineering.
