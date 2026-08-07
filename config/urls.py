from django.contrib import admin
from django.urls import include, path

from .views import healthz

urlpatterns = [
    path("admin/", admin.site.urls),
    # Para probes de infraestructura (Render, K8s, balanceadores). Sin login,
    # sin CSRF: lo consulta el orquestador, no un usuario.
    path("healthz/", healthz, name="healthz"),
    # Esta línea deriva todo el tráfico hacia tu app "reservas"
    path("", include("reservas.urls")),
]
handler404 = "reservas.views.custom_404"
