"""Database models for PDF indexing and redaction extraction."""
from django.db import models


class PdfDocument(models.Model):
    """Indexed PDF file on disk."""
    filename = models.CharField(max_length=255, db_index=True)
    path = models.TextField(unique=True)

    def __str__(self) -> str:
        return self.filename


# ---------------------------------------------------------------------------
# Redaction extraction models
# ---------------------------------------------------------------------------

class ExtractionRun(models.Model):
    """A single batch run of the redaction extractor."""
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_RUNNING)
    parameters = models.JSONField(default=dict)
    total_documents = models.IntegerField(default=0)
    total_pages = models.IntegerField(default=0)
    total_redactions = models.IntegerField(default=0)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"ExtractionRun {self.pk} ({self.status} @ {self.started_at:%Y-%m-%d %H:%M})"


class ExtractedDocument(models.Model):
    """Per-document results within an extraction run."""
    extraction_run = models.ForeignKey(
        ExtractionRun, on_delete=models.CASCADE, related_name="extracted_documents"
    )
    pdf_document = models.ForeignKey(
        PdfDocument, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="extracted_documents",
    )
    doc_id = models.CharField(max_length=255, db_index=True)
    file_path = models.TextField()
    total_pages = models.IntegerField(default=0)
    error = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["extraction_run", "doc_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.doc_id} (run {self.extraction_run_id})"


class RedactionRecord(models.Model):
    """A single detected redaction bar with full analysis data."""
    extracted_document = models.ForeignKey(
        ExtractedDocument, on_delete=models.CASCADE, related_name="redactions"
    )
    page_num = models.IntegerField()
    redaction_index = models.IntegerField()

    bbox_x0_points = models.FloatField()
    bbox_y0_points = models.FloatField()
    bbox_x1_points = models.FloatField()
    bbox_y1_points = models.FloatField()
    width_points = models.FloatField()
    height_points = models.FloatField()

    bbox_x0_pixels = models.IntegerField()
    bbox_y0_pixels = models.IntegerField()
    bbox_x1_pixels = models.IntegerField()
    bbox_y1_pixels = models.IntegerField()
    width_pixels = models.IntegerField()
    height_pixels = models.IntegerField()

    detection_method = models.CharField(max_length=16, db_index=True)
    confidence = models.FloatField(db_index=True)

    estimated_chars = models.IntegerField(default=0, db_index=True)
    font_size_nearby = models.FloatField(null=True, blank=True)
    avg_char_width = models.FloatField(null=True, blank=True)

    text_before = models.TextField(blank=True)
    text_after = models.TextField(blank=True)

    has_ascender_leakage = models.BooleanField(default=False)
    has_descender_leakage = models.BooleanField(default=False)
    leakage_pixels_top = models.IntegerField(default=0)
    leakage_pixels_bottom = models.IntegerField(default=0)

    is_multiline = models.BooleanField(default=False)
    multiline_group_id = models.CharField(max_length=255, blank=True)
    line_index_in_group = models.IntegerField(null=True, blank=True)

    image_tight = models.TextField(blank=True)
    image_context = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["extracted_document", "page_num"]),
            models.Index(fields=["detection_method", "estimated_chars"]),
        ]

    def __str__(self) -> str:
        return f"Redaction {self.redaction_index} on page {self.page_num} of {self.extracted_document_id}"
