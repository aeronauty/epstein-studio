from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("epstein_ui", "0015_remove_annotation_system"),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentEntity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("entity_text", models.CharField(db_index=True, max_length=512)),
                ("entity_type", models.CharField(
                    choices=[
                        ("PERSON", "Person"),
                        ("ORG", "Organization"),
                        ("GPE", "Geopolitical Entity"),
                        ("LOC", "Location"),
                        ("DATE", "Date"),
                        ("NORP", "Nationality/Group"),
                        ("FAC", "Facility"),
                        ("EVENT", "Event"),
                        ("LAW", "Law/Legal"),
                        ("MONEY", "Money"),
                        ("OTHER", "Other"),
                    ],
                    db_index=True,
                    max_length=16,
                )),
                ("page_num", models.IntegerField()),
                ("count", models.IntegerField(default=1)),
                ("extracted_document", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="entities",
                    to="epstein_ui.extracteddocument",
                )),
            ],
            options={
                "indexes": [
                    models.Index(fields=["entity_type", "entity_text"], name="epstein_ui_do_entity__4c0c3e_idx"),
                    models.Index(fields=["extracted_document", "entity_type"], name="epstein_ui_do_extract_8f1a2b_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="CandidateList",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("entries", models.JSONField(default=list, help_text="List of candidate strings")),
            ],
        ),
    ]
