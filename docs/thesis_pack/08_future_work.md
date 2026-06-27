# 08 — Future Work and Recommendations

## Security and Deployment
1. Move sensitive settings to environment variables.
2. Disable debug mode and configure production host/domain settings.
3. Add hardened media/static serving strategy and routine backup automation.

## Architecture Improvements
1. Refactor large view logic into service and form layers.
2. Introduce REST API endpoints for integration and mobile clients.
3. Add structured audit logging for sensitive actions (status changes, revocations).

## Data and Performance
1. Migrate to PostgreSQL for improved reliability and scaling.
2. Add query optimization and indexing strategy for reporting workloads.
3. Add caching for dashboard and report-heavy pages.

## Feature Enhancements
1. Notification subsystem (email/SMS/WhatsApp) for status updates.
2. Appointment reminders for scheduled sacraments.
3. Multi-parish / multi-branch tenant support.
4. Better report builder with user-selected filters.

## AI and Knowledge Features
1. Replace keyword assistant with retrieval-augmented LLM support.
2. Add explainable report summaries and anomaly detection.
3. Add guided thesis/report generation from anonymized exports.

## Quality Assurance
1. Build unit, integration, and regression test suites.
2. Add CI pipeline for lint/test checks.
3. Add UAT protocol with church administrators and members.
