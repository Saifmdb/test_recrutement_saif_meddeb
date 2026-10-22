from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Admissions — back-office"
admin.site.site_title = "Admissions"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("admissions.urls")),
]
