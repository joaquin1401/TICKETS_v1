"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from . import views

urlpatterns = [
    path('admin/', admin.site.urls),
    # ── Épica 1: Autenticación ──────────────────────────────────────────────
    path("", views.login_view, name="login"),
    path("registro/", views.registro, name="registro"),
    path("logout/", views.logout_view, name="logout"),

    # ── Épica 2: Dashboard y tickets ───────────────────────────────────────
    path("dashboard/", views.dashboard, name="dashboard"),
    path("historial/", views.historial, name="historial"),
    path("tickets/<int:ticket_id>/", views.detalle_ticket, name="detalle_ticket"),

    # ── Épica 3: Calendario ─────────────────────────────────────────────────
    path("calendario/", views.calendario, name="calendario"),
    path(
        "calendario/<int:vehiculo_id>/<int:anio>/<int:mes>/<int:dia>/",
        views.timeline_dia,
        name="timeline_dia",
    ),

    # ── Épica 5: Administración ─────────────────────────────────────────────
    path("admin-panel/validacion/", views.panel_validacion, name="panel_validacion"),
    path("admin-panel/usuarios/", views.directorio_usuarios, name="directorio_usuarios"),
    path("admin-panel/usuarios/rechazados/", views.usuarios_rechazados, name="usuarios_rechazados"),
    path("admin-panel/tickets/activos/", views.monitor_tickets_activos, name="monitor_tickets_activos"),
    path("admin-panel/tickets/auditoria/", views.auditoria_tickets, name="auditoria_tickets"),

    # ── Épica 6: ABM de flota ──────────────────────────────────────────────
    path("admin-panel/flota/", views.listado_flota, name="listado_flota"),
    path("admin-panel/flota/nueva/", views.alta_vehiculo, name="alta_vehiculo"),
    path("admin-panel/flota/<int:vehiculo_id>/editar/", views.edicion_vehiculo, name="edicion_vehiculo"),
]
