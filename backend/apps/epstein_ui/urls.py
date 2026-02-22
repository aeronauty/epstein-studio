from django.urls import path
from . import views

urlpatterns = [
    path("", views.start_page, name="start"),
    path("entities/", views.entities_page, name="entities_page"),
    path("entities/list/", views.entities_list, name="entities_list"),
    path("entities/detail/<path:entity_text>/", views.entity_detail, name="entity_detail"),
    path("entities/candidates/", views.candidate_lists, name="candidate_lists"),
    path("entities/candidates/<int:pk>/delete/", views.candidate_list_delete, name="candidate_list_delete"),
    path("matches/", views.matches_page, name="matches_page"),
    path("matches/list/", views.matches_list, name="matches_list"),
    path("matches/stats/", views.matches_stats, name="matches_stats"),
    path("redactions-demo/", views.redactions_demo, name="redactions_demo"),
    path("redactions-list/", views.redactions_list, name="redactions_list"),
    path("redactions/<int:pk>/", views.redaction_detail, name="redaction_detail"),
    path("redactions/<int:pk>/page-image/", views.redaction_page_image, name="redaction_page_image"),
    path("redactions/<int:pk>/font-analysis/", views.redaction_font_analysis, name="redaction_font_analysis"),
    path("redactions/<int:pk>/font-optimize/", views.redaction_font_optimize, name="redaction_font_optimize"),
    path("redactions/<int:pk>/text-candidates/", views.redaction_text_candidates, name="redaction_text_candidates"),
    path("redactions-image/<path:filepath>", views.redaction_image, name="redaction_image"),
]
