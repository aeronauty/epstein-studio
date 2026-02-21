from django.urls import path
from . import views

urlpatterns = [
    path("", views.start_page, name="start"),
    path("redactions-demo/", views.redactions_demo, name="redactions_demo"),
    path("redactions-list/", views.redactions_list, name="redactions_list"),
    path("redactions/<int:pk>/", views.redaction_detail, name="redaction_detail"),
    path("redactions/<int:pk>/page-image/", views.redaction_page_image, name="redaction_page_image"),
    path("redactions/<int:pk>/font-analysis/", views.redaction_font_analysis, name="redaction_font_analysis"),
    path("redactions/<int:pk>/font-optimize/", views.redaction_font_optimize, name="redaction_font_optimize"),
    path("redactions-image/<path:filepath>", views.redaction_image, name="redaction_image"),
]
