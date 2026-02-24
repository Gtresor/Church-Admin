from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("base", "0018_person_is_child_profile"),
    ]

    operations = [
        migrations.AddField(
            model_name="person",
            name="cell",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="person",
            name="country",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="person",
            name="district",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="person",
            name="emergency_contact_name",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="person",
            name="emergency_contact_phone",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="person",
            name="marital_status",
            field=models.CharField(
                choices=[("Single", "Single"), ("Married", "Married"), ("Widowed", "Widowed"), ("Divorced", "Divorced")],
                default="Single",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="person",
            name="nationality",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="person",
            name="occupation",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="person",
            name="province",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="person",
            name="spouse_name",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="person",
            name="village",
            field=models.CharField(blank=True, max_length=80),
        ),
    ]
