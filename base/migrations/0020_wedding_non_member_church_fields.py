from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("base", "0019_person_extended_profile_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="wedding",
            name="bride_church_name",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="wedding",
            name="groom_church_name",
            field=models.CharField(blank=True, max_length=200),
        ),
    ]
