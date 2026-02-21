"""Database models for per-PDF annotation data and redaction extraction."""
import uuid
from django.conf import settings
from django.db import models


class Annotation(models.Model):
    """Top-level annotation anchor tied to a PDF and user."""
    hash = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    pdf_key = models.CharField(max_length=255, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    client_id = models.CharField(max_length=64)
    x = models.FloatField()
    y = models.FloatField()
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("pdf_key", "user", "client_id")


class TextItem(models.Model):
    """Placed text overlay belonging to an annotation."""
    annotation = models.ForeignKey(Annotation, on_delete=models.CASCADE, related_name="text_items")
    x = models.FloatField()
    y = models.FloatField()
    text = models.TextField(blank=True)
    font_family = models.CharField(max_length=255, blank=True)
    font_size = models.CharField(max_length=32, blank=True)
    font_weight = models.CharField(max_length=32, blank=True)
    font_style = models.CharField(max_length=32, blank=True)
    font_kerning = models.CharField(max_length=32, blank=True)
    font_feature_settings = models.CharField(max_length=64, blank=True)
    color = models.CharField(max_length=32, blank=True)
    opacity = models.FloatField(default=1)


class ArrowItem(models.Model):
    """Hint arrow belonging to an annotation."""
    annotation = models.ForeignKey(Annotation, on_delete=models.CASCADE, related_name="arrow_items")
    x1 = models.FloatField()
    y1 = models.FloatField()
    x2 = models.FloatField()
    y2 = models.FloatField()


class PdfDocument(models.Model):
    """Indexed PDF available for annotation."""
    filename = models.CharField(max_length=255, db_index=True)
    path = models.TextField(unique=True)
    annotation_count = models.IntegerField(default=0)
    comment_count = models.IntegerField(default=0)
    vote_score = models.IntegerField(default=0)

    def __str__(self) -> str:
        return self.filename


class AnnotationVote(models.Model):
    """Single user vote (+1 or -1) for an annotation."""
    annotation = models.ForeignKey(Annotation, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    value = models.SmallIntegerField()

    class Meta:
        unique_together = ("annotation", "user")


class AnnotationComment(models.Model):
    """Discussion comment for an annotation."""
    annotation = models.ForeignKey(Annotation, on_delete=models.CASCADE, related_name="comments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="replies")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class CommentVote(models.Model):
    """Single user vote (+1 or -1) for a comment."""
    comment = models.ForeignKey(AnnotationComment, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    value = models.SmallIntegerField()

    class Meta:
        unique_together = ("comment", "user")


class PdfVote(models.Model):
    """Single user vote (+1 or -1) for a PDF file."""
    pdf = models.ForeignKey(PdfDocument, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    value = models.SmallIntegerField()

    class Meta:
        unique_together = ("pdf", "user")


class PdfComment(models.Model):
    """Discussion comment for a PDF."""
    hash = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    pdf = models.ForeignKey(PdfDocument, on_delete=models.CASCADE, related_name="comments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class PdfCommentReply(models.Model):
    """Reply in a PDF comment discussion."""
    comment = models.ForeignKey(PdfComment, on_delete=models.CASCADE, related_name="replies")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="children")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class PdfCommentReplyVote(models.Model):
    """Single user vote (+1 or -1) for a PDF comment reply."""
    reply = models.ForeignKey(PdfCommentReply, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    value = models.SmallIntegerField()

    class Meta:
        unique_together = ("reply", "user")


class PdfCommentVote(models.Model):
    """Single user vote (+1 or -1) for a PDF comment."""
    comment = models.ForeignKey(PdfComment, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    value = models.SmallIntegerField()

    class Meta:
        unique_together = ("comment", "user")


class Notification(models.Model):
    """User notification for replies on annotations or PDF comments."""
    TYPE_ANNOTATION_REPLY = "annotation_reply"
    TYPE_PDF_COMMENT_REPLY = "pdf_comment_reply"
    TYPE_CHOICES = [
        (TYPE_ANNOTATION_REPLY, "Annotation Reply"),
        (TYPE_PDF_COMMENT_REPLY, "PDF Comment Reply"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    notif_type = models.CharField(max_length=64, choices=TYPE_CHOICES)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    # Optional references to the origin of the notification
    annotation = models.ForeignKey(Annotation, null=True, blank=True, on_delete=models.CASCADE)
    annotation_comment = models.ForeignKey(AnnotationComment, null=True, blank=True, on_delete=models.CASCADE)
    pdf_comment = models.ForeignKey(PdfComment, null=True, blank=True, on_delete=models.CASCADE)
    pdf_comment_reply = models.ForeignKey(PdfCommentReply, null=True, blank=True, on_delete=models.CASCADE)


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

    # Geometry in PDF points
    bbox_x0_points = models.FloatField()
    bbox_y0_points = models.FloatField()
    bbox_x1_points = models.FloatField()
    bbox_y1_points = models.FloatField()
    width_points = models.FloatField()
    height_points = models.FloatField()

    # Geometry in pixels (at render DPI)
    bbox_x0_pixels = models.IntegerField()
    bbox_y0_pixels = models.IntegerField()
    bbox_x1_pixels = models.IntegerField()
    bbox_y1_pixels = models.IntegerField()
    width_pixels = models.IntegerField()
    height_pixels = models.IntegerField()

    # Detection metadata
    detection_method = models.CharField(max_length=16, db_index=True)
    confidence = models.FloatField(db_index=True)

    # Character estimation
    estimated_chars = models.IntegerField(default=0, db_index=True)
    font_size_nearby = models.FloatField(null=True, blank=True)
    avg_char_width = models.FloatField(null=True, blank=True)

    # Surrounding text context
    text_before = models.TextField(blank=True)
    text_after = models.TextField(blank=True)

    # Leakage analysis
    has_ascender_leakage = models.BooleanField(default=False)
    has_descender_leakage = models.BooleanField(default=False)
    leakage_pixels_top = models.IntegerField(default=0)
    leakage_pixels_bottom = models.IntegerField(default=0)

    # Multi-line grouping
    is_multiline = models.BooleanField(default=False)
    multiline_group_id = models.CharField(max_length=255, blank=True)
    line_index_in_group = models.IntegerField(null=True, blank=True)

    # Image paths (relative to extractor output directory)
    image_tight = models.TextField(blank=True)
    image_context = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["extracted_document", "page_num"]),
            models.Index(fields=["detection_method", "estimated_chars"]),
        ]

    def __str__(self) -> str:
        return f"Redaction {self.redaction_index} on page {self.page_num} of {self.extracted_document_id}"
