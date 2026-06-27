"""
Management command to create wedding slots for specific dates with standard times: 12pm, 2pm, 4pm
"""
from datetime import date, time
from django.core.management.base import BaseCommand
from django.utils import timezone
from base.models import AvailableSlot


class Command(BaseCommand):
	help = 'Create wedding slots for a specific date or date range with 12pm, 2pm, 4pm times'

	def add_arguments(self, parser):
		parser.add_argument('--start-date', type=str, help='Start date in format YYYY-MM-DD')
		parser.add_argument('--end-date', type=str, help='End date in format YYYY-MM-DD (optional, if not provided only start-date is used)')
		parser.add_argument('--activity', type=str, choices=['Wedding', 'Baptism', 'Dedication'], default='Wedding',
			help='Activity type (default: Wedding)')

	def handle(self, *args, **options):
		from datetime import datetime, timedelta
		
		start_date_str = options.get('start_date')
		end_date_str = options.get('end_date')
		activity_type = options['activity']
		
		if not start_date_str:
			self.stdout.write(self.style.ERROR('--start-date is required'))
			return

		try:
			start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
		except ValueError:
			self.stdout.write(self.style.ERROR(f'Invalid start date format: {start_date_str}. Use YYYY-MM-DD'))
			return

		if end_date_str:
			try:
				end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
			except ValueError:
				self.stdout.write(self.style.ERROR(f'Invalid end date format: {end_date_str}. Use YYYY-MM-DD'))
				return
		else:
			end_date = start_date

		# Wedding slots have standard times
		if activity_type == 'Wedding':
			times = [time(12, 0), time(14, 0), time(16, 0)]  # 12pm, 2pm, 4pm
		else:
			times = [None]  # Baptism and Dedication don't have specific times

		current_date = start_date
		created_count = 0
		skipped_count = 0

		while current_date <= end_date:
			for slot_time in times:
				try:
					slot, created = AvailableSlot.objects.get_or_create(
						activity_type=activity_type,
						date=current_date,
						time=slot_time,
						defaults={'is_available': True}
					)
					if created:
						created_count += 1
						self.stdout.write(self.style.SUCCESS(
							f'✓ Created {activity_type} slot for {current_date}' +
							(f' at {slot_time.strftime("%H:%M")}' if slot_time else '')
						))
					else:
						skipped_count += 1
				except Exception as e:
					self.stdout.write(self.style.ERROR(f'✗ Error creating slot: {e}'))

			current_date += timedelta(days=1)

		self.stdout.write(self.style.SUCCESS(
			f'\nSummary: {created_count} slots created, {skipped_count} slots already exist'
		))
