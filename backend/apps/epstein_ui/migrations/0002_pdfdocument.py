from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("epstein_ui", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PdfDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("filename", models.CharField(db_index=True, max_length=255)),
                ("path", models.TextField(unique=True)),
            ],
        ),
    ]
