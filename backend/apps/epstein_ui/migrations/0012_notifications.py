from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("epstein_ui", "0011_pdf_comment_hash"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("notif_type", models.CharField(choices=[("annotation_reply", "Annotation Reply"), ("pdf_comment_reply", "PDF Comment Reply")], max_length=64)),
                ("is_read", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "annotation",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to="epstein_ui.annotation"),
                ),
                (
                    "annotation_comment",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to="epstein_ui.annotationcomment"
                    ),
                ),
                (
                    "pdf_comment",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to="epstein_ui.pdfcomment"),
                ),
                (
                    "pdf_comment_reply",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to="epstein_ui.pdfcommentreply"),
                ),
                (
                    "user",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notifications", to=settings.AUTH_USER_MODEL),
                ),
            ],
        ),
    ]
