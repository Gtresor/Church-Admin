from django.db import migrations, models


def mark_existing_dedication_children(apps, schema_editor):
    Person = apps.get_model("base", "Person")
    BabyDedication = apps.get_model("base", "BabyDedication")
    child_ids = BabyDedication.objects.values_list("child_id", flat=True)
    Person.objects.filter(id__in=child_ids).update(is_child_profile=True)


class Migration(migrations.Migration):

    dependencies = [
        ("base", "0017_wedding_health_documents"),
    ]

    operations = [
        migrations.AddField(
            model_name="person",
            name="is_child_profile",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(mark_existing_dedication_children, migrations.RunPython.noop),
    ]
