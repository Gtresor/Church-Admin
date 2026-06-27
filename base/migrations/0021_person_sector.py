from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("base", "0020_wedding_non_member_church_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="person",
            name="sector",
            field=models.CharField(blank=True, max_length=80),
        ),
    ]
