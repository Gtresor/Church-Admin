# Church Sacrament Scheduling System

## Overview

The church management system has been updated with a new scheduling system for sacraments. Instead of members selecting their own dates, the admin now creates available dates/slots, and members choose from them when making requests. If no slots are available, members can still submit requests and the admin will schedule them later.

## Key Features

### 1. Available Slots Management
- **Admins create available slots** for each activity (Baptism, Wedding, Baby Dedication)
- **Weddings have 3 time slots per day**: 12:00 PM, 2:00 PM, 4:00 PM
- **Baptisms and Dedications** have daily slots (no specific times)
- **Easy management** through Django admin panel

### 2. Member Request Flow
- Members see available slots and can select one when submitting a request
- If no slots are available, they can still submit a request
- Admin receives the request and schedules it when a slot becomes available, or assigns an existing slot
- Members can receive notifications about assigned slots

### 3. Admin Features
- View all pending requests grouped by activity type
- See which slots are available and assigned
- Assign available slots to pending requests
- Manage slot availability (create, edit, disable)
- Dates automatically sync from slots to sacrament records

## How to Use

### For Admins: Creating Available Slots

#### Option 1: Using Management Command (Recommended)

Create wedding slots for specific dates:
```bash
python manage.py create_wedding_slots --start-date 2026-04-15 --end-date 2026-04-20 --activity Wedding
```

Create baptism slots:
```bash
python manage.py create_wedding_slots --start-date 2026-04-15 --end-date 2026-04-20 --activity Baptism
```

Create dedication slots:
```bash
python manage.py create_wedding_slots --start-date 2026-04-15 --end-date 2026-04-20 --activity Dedication
```

#### Option 2: Using Django Admin

1. Log in to the Django admin panel
2. Navigate to "Available Slots"
3. Click "Add Available Slot"
4. Fill in:
   - **Activity Type**: Select Wedding, Baptism, or Dedication
   - **Date**: The date of the slot
   - **Time**: For weddings only (12:00, 14:00, 16:00). Leave blank for other activities
   - **Is Available**: Check to make it available for members
5. Click Save

### For Admins: Managing Sacrament Requests

1. Go to **Baptism**, **Baby Dedication**, or **Wedding** section in admin
2. View pending requests (filter by Status = "Pending")
3. For each pending request:
   - Click the request to edit it
   - In the "Scheduling" section, select an "Available Slot"
   - The date will automatically populate in the sacrament date field
   - Update status if needed (e.g., change to "Scheduled" when slot is assigned)
   - Update officiant information
   - Add admin comments if needed
   - Save

### For Members: Submitting Requests

#### Weddings
1. Go to member dashboard → "Request Wedding"
2. Read and acknowledge the process
3. Select whether you're the groom or bride
4. If available slots exist, select your preferred **date and time**
5. Enter partner information (church member or non-member)
6. Submit

#### Baptisms
1. Go to member dashboard → "Request Baptism"
2. If available slots exist, optionally select an available date
3. Submit (slot selection is optional)

#### Baby Dedication
1. Go to member dashboard → "Request Dedication"
2. Fill in child and parent details
3. Add scripture reference and verse
4. If available slots exist, optionally select an available date
5. Submit

## Database Schema

### AvailableSlot Model
```
- id (UUID)
- activity_type (Baptism, Dedication, Wedding)
- date (Date)
- time (Time) - Only used for weddings
- is_available (Boolean)
- created_at (DateTime)
- updated_at (DateTime)
```

### Updated Sacrament Models
All sacrament models now include:
- `available_slot` (ForeignKey to AvailableSlot, nullable)

And have automatic date synchronization:
- When `available_slot` is set, the sacrament date (baptism_date, dedication_date, wedding_date) auto-populates

## Admin Dashboard Views

### Baptism Admin
- List display: Person, Status, Assigned Slot, Baptism Date, Certificate Generated
- Filter by: Status, Certificate Generated
- Search by: Person name, Officiant

### Baby Dedication Admin
- List display: Child, Father, Mother, Status, Assigned Slot, Dedication Date, Certificate Generated
- Filter by: Status, Certificate Generated
- Search by: Names

### Wedding Admin
- List display: Groom, Bride, Status, Assigned Slot, Wedding Date, Certificate Generated
- Filter by: Status, Certificate Generated
- Search by: Names, Officiant

### Available Slots Admin
- List display: Activity Type, Date, Time, Is Available
- Filter by: Activity Type, Date, Is Available
- Can create and bulk-edit slots

## Examples

### Example 1: Create Wedding Slots for April

```bash
python manage.py create_wedding_slots --start-date 2026-04-01 --end-date 2026-04-30 --activity Wedding
```

This creates:
- 90 wedding slots (3 per day × 30 days)
- Each with times: 12:00, 14:00, 16:00
- All marked as available

### Example 2: Assign Slot to Pending Wedding

1. Member submits wedding request (with or without slot selected)
2. Admin views pending weddings
3. Admin clicks on the pending request
4. In "Scheduling" section, selects an available slot (e.g., "2026-04-15 at 14:00")
5. Wedding date auto-fills to 2026-04-15
6. Admin updates status to "Scheduled"
7. Admin enters officiant name
8. Admin clicks Save

### Example 3: No Slots Available

1. Member tries to submit baptism request
2. System shows: "No Available Dates: There are currently no available dates for baptism."
3. Member can still submit request
4. Admin later creates baptism slots
5. Admin assigns slot to the pending request
6. System sends notification/member dashboard shows scheduled date

## Workflow Diagram

```
Member Request Flow:
│
├─ Member Submits Request
│  ├─ If slots exist: Can select OR leave blank
│  └─ If no slots: Can only submit without slot
│
├─ Admin Reviews Request (Pending Status)
│  └─ Can assign available slot to request
│
├─ Date Auto-Syncs from Slot
│  └─ baptism_date/dedication_date/wedding_date populated
│
└─ Status Updated to Scheduled
   └─ Member sees scheduled date on dashboard

Admin Slot Management:
│
├─ Admin Creates Available Slots
│  ├─ Via management command: create_wedding_slots
│  ├─ Via Django admin: Add > Available Slot
│  └─ Slots marked as "Is Available = True"
│
├─ Slots Appear in Member Requests
│  └─ Dropdown shows all available slots
│
└─ Admin Can Disable Slots
   └─ Set "Is Available = False"
```

## API-like Slot Assignment Logic

### Finding Available Slots
```python
available_slots = AvailableSlot.objects.filter(
    activity_type=activity_type,  # 'Wedding', 'Baptism', 'Dedication'
    is_available=True
).order_by('date', 'time')
```

### Assigning a Slot
```python
sacrament.available_slot = slot  # e.g., wedding.available_slot = available_slot
sacrament.save()  # Date auto-syncs
```

### Checking Slot Assignment
```python
if baptism.available_slot:
    print(f"Baptism scheduled for {baptism.baptism_date}")
else:
    print(f"Baptism pending assignment (requested on {baptism.request_date})")
```

## Troubleshooting

### Issue: Slots not appearing for members
- **Solution**: Check that slots are marked as `is_available = True` in admin
- **Check**: Go to Available Slots admin, verify slots exist and are not disabled

### Issue: Can't create slots with management command
- **Solution**: Check date format is YYYY-MM-DD
- **Example**: `python manage.py create_wedding_slots --start-date 2026-04-15`

### Issue: Date not auto-populating from slot
- **Solution**: Verify slot was saved before saving the sacrament record
- **Check**: The model's save() method should automatically sync the date

### Issue: Member sees old date picker
- **Solution**: Clear browser cache or do a hard refresh (Ctrl+Shift+R)

## Future Enhancements

Potential improvements to the system:
1. Email notifications when slots become available
2. SMS notifications for slot assignments
3. Calendar visualization of available slots
4. Admin dashboard with slot utilization stats
5. Automatic slot availability based on church schedule
6. Waitlist system if slots are full
7. Recurring slot creation (e.g., "Every Saturday at 10am")
8. Slot capacity limits (max 3 weddings per time slot)

## Technical Details

### Model Relationships
```
AvailableSlot (1) ──→ (many) Baptism
AvailableSlot (1) ──→ (many) BabyDedication
AvailableSlot (1) ──→ (many) Wedding
```

### Auto-sync Logic (in Model.save())
```python
def save(self, *args, **kwargs):
    if self.available_slot:
        self.sacrament_date = self.available_slot.date
    super().save(*args, **kwargs)
```

### Admin Fieldsets
- **Scheduling**: Shows available_slot dropdown
- **Status**: Shows the synced date (read-only)
- Personal details remain in their own sections

## Support

For questions or issues with the scheduling system:
1. Check this documentation
2. Review the management command help: `python manage.py create_wedding_slots --help`
3. Check Django admin for slot configurations
4. Review sacrament status and comments for admin notes
