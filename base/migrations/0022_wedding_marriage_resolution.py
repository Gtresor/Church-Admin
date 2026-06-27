from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("base", "0021_person_sector"),
    ]

    operations = [
        migrations.AddField(
            model_name="wedding",
            name="marriage_resolution",
            field=models.CharField(blank=True, choices=[("Divorced", "Divorced"), ("Annulled", "Annulled")], max_length=20),
        ),
    ]
