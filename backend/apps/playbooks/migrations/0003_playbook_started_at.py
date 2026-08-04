from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("playbooks", "0002_playbook_playbook_created_job_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="playbook",
            name="started_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text="Background job claim time, used to reap runs abandoned by a dead worker (后台任务领取时间)",
            ),
        ),
    ]
