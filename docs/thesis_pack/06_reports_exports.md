# 06 — Reporting, Analytics, and Export Features

## Dashboard Outputs
Admin dashboard presents key operational indicators:
- Total members
- Pending baptisms
- Pending dedications
- Total weddings
- Certificates issued
- Upcoming services (cross-service timeline)
- Recent requests and recent certificates

Member dashboard presents:
- Personal baptism status
- Family dedication requests
- Personal certificate history
- Pending request count summary

## Calendar Module
Monthly calendar view aggregates scheduled events from:
- Baptism dates
- Dedication dates
- Wedding dates

## Report Analytics
The reports page computes time-based indicators such as:
- Monthly baptisms, dedications, weddings
- Monthly certificates issued
- Membership growth by month
- Approval vs rejection counts
- Year-range service totals

## Prompt-Driven AI-Like Reporting
The internal assistant (`base/services/ai_reports.py`) supports recognized intents, including:
- pending dedication requests
- members by district
- certificates by service type in a year
- monthly baptisms/dedications
- upcoming scheduled services in N days

Important: this module is deterministic and keyword-driven; it is not a generative LLM.

## Export Features
- CSV export for services by selected year range
- PDF export for service logs
- PDF export for certificate logs
- AI report CSV export for matched report prompts

These features support administrative transparency and external reporting needs.
