from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("base", "0005_babydedication_scripture_reference_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="officiant",
            name="signature_image",
            field=models.ImageField(blank=True, upload_to="officiant_signatures/"),
        ),
    ]
