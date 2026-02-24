from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("base", "0016_officiant_signature_image"),
    ]

    operations = [
        migrations.AddField(
            model_name="wedding",
            name="bride_health_document",
            field=models.FileField(blank=True, upload_to="wedding_health_documents/"),
        ),
        migrations.AddField(
            model_name="wedding",
            name="groom_health_document",
            field=models.FileField(blank=True, upload_to="wedding_health_documents/"),
        ),
    ]
