# 03 — Data Model and Relationships

## Core Entities

### Person
Stores biographic/contact/location details. Acts as a base person record for members, children, and non-member spouses/parents.

### MemberAccount
One-to-one bridge between Django `User` and `Person` for member portal access.

### AdminProfile
One-to-one extension for admin user profile/photo.

### Officiant
Represents ministers/officiants and optional signature image used on certificates.

### Baptism
One-to-one with `Person`; tracks request, status, service date, officiant text, and certificate flag.

### BabyDedication
Links child, father, and mother (all `Person` records), plus scripture metadata, status, and certificate flag.

### Wedding
Links groom and bride (`Person`), stores date, officiant, health documents, status, and resolution fields.

### Certificate
Generic relation to one sacrament record (Baptism/Dedication/Wedding). Includes unique certificate number, issue date, template code, QR image, PDF file, and validity/revocation fields.

## Relationship Summary
- User 1:1 MemberAccount
- User 1:1 AdminProfile
- Person 1:1 MemberAccount
- Person 1:1 Baptism
- Person 1:N BabyDedication (as child/father/mother roles)
- Person 1:N Wedding (as groom/bride roles)
- Certificate N:1 (generic target to one sacrament object)

## Integrity and Constraints
- UUID primary keys on domain records.
- Sacrament and certificate records are protected from deletion:
  - `ProtectedSacramentModel.delete()` raises validation error.
  - `pre_delete` signal blocks deletions for historical integrity.
- `Certificate.certificate_number` is unique and auto-generated when missing.
- Officiant names are unique.

## Domain Status Model
Shared status choices:
- Pending
- Approved
- Rejected
- Scheduled
- Completed
- Cancelled

These statuses drive workflow transitions and available actions in review screens.
