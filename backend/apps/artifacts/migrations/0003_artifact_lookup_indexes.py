from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("artifacts", "0002_artifact_artifact_created_id_idx"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="artifact",
            index=models.Index(fields=["name", "type", "role"], name="artifact_identity_idx"),
        ),
        migrations.AddIndex(
            model_name="artifact",
            index=models.Index(fields=["value"], name="artifact_value_idx"),
        ),
    ]
