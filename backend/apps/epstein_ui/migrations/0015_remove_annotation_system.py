"""Remove all annotation/comment/vote/notification models."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('epstein_ui', '0014_redaction_extraction_models'),
    ]

    operations = [
        # Clear all unique_together constraints first
        migrations.AlterUniqueTogether(name='annotation', unique_together=set()),
        migrations.AlterUniqueTogether(name='annotationvote', unique_together=set()),
        migrations.AlterUniqueTogether(name='commentvote', unique_together=set()),
        migrations.AlterUniqueTogether(name='pdfvote', unique_together=set()),
        migrations.AlterUniqueTogether(name='pdfcommentvote', unique_together=set()),
        migrations.AlterUniqueTogether(name='pdfcommentreplyvote', unique_together=set()),

        # Delete models (children before parents)
        migrations.DeleteModel(name='ArrowItem'),
        migrations.DeleteModel(name='TextItem'),
        migrations.DeleteModel(name='CommentVote'),
        migrations.DeleteModel(name='AnnotationVote'),
        migrations.DeleteModel(name='AnnotationComment'),
        migrations.DeleteModel(name='Notification'),
        migrations.DeleteModel(name='PdfCommentReplyVote'),
        migrations.DeleteModel(name='PdfCommentReply'),
        migrations.DeleteModel(name='PdfCommentVote'),
        migrations.DeleteModel(name='PdfComment'),
        migrations.DeleteModel(name='Annotation'),
        migrations.DeleteModel(name='PdfVote'),

        # Remove leftover fields from PdfDocument
        migrations.RemoveField(model_name='pdfdocument', name='annotation_count'),
        migrations.RemoveField(model_name='pdfdocument', name='comment_count'),
        migrations.RemoveField(model_name='pdfdocument', name='vote_score'),
    ]
