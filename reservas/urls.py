"""
Configuración de enrutamiento URL para la aplicación de reservas.

Define todas las rutas HTTP del sistema, organizadas por épica funcional:
- Épica 1: Autenticación (registro, login, logout)
- Épica 2: Inicio y gestión de tickets de usuario
- Épica 3: Calendario interactivo y línea de tiempo
- Épica 5: Panel administrativo (validación, directorio, auditoría)
- Épica 6: Administración de flota

Convención de nombramiento: Los nombres de rutas (name=...) utilizan
snake_case y sirven como identificadores únicos en templates y redirects.

Autenticación de sesión:
    Utiliza sistema de sesión Django estándar. La sesión se almacena en:
    - request.session["usuario_id"] (PK del usuario logueado)
    - request.session["es_admin"] (bool, True si prioridad == 0)

Decoradores de vista:
    - @login_requerido: Redirige a login si no hay sesión activa.
    - @admin_requerido: Redirige a inicio si es_admin == False.
"""

from django.contrib import admin
from django.urls import path
from . import views

urlpatterns = [
    path('admin/', admin.site.urls),

    # ═══════════════════════════════════════════════════════════════════════════════
    # Épica 1: Autenticación
    # ═══════════════════════════════════════════════════════════════════════════════
    # HU 1.1: Registro de cuenta
    # HU 1.2: Inicio de sesión
    # HU 1.3 / 1.4: Panel de validación (dentro de admin-panel)
    
    path("", views.login_view, name="login"),
    path("registro/", views.registro, name="registro"),
    path("logout/", views.logout_view, name="logout"),

    # ═══════════════════════════════════════════════════════════════════════════════
    # Épica 2: Inicio y Tickets (Usuario normal)
    # ═══════════════════════════════════════════════════════════════════════════════
    # HU 2.1: Inicio con formulario rápido de reserva
    # HU 2.2: Historial de tickets
    # HU 2.3: Detalle de ticket específico
    
    path("inicio/", views.inicio, name="inicio"),
    path("historial/", views.historial, name="historial"),
    path("tickets/<int:ticket_id>/", views.detalle_ticket, name="detalle_ticket"),
    path("tickets/<int:ticket_id>/cancelar/", views.cancelar_ticket, name="cancelar_ticket"),

    # ═══════════════════════════════════════════════════════════════════════════════
    # Épica 3: Calendario e Interactividad
    # ═══════════════════════════════════════════════════════════════════════════════
    # HU 3.1: Selector de vehículo
    # HU 3.2: Vista mensual del calendario
    # HU 3.3: Línea de tiempo horaria de un día
    
    # HU 3.1: Selector de vehículo
    # HU 3.2: Vista mensual del calendario
    # HU 3.3: Línea de tiempo horaria de un día

    # ═══════════════════════════════════════════════════════════════════════════════
    # Épica 5: Supervisión y Administración
    # ═══════════════════════════════════════════════════════════════════════════════
    # HU 1.3 / 1.4: Panel de validación de usuarios pendientes
    # HU 5.1: Directorio de usuarios (búsqueda y filtros)
    # HU 5.2: Vista de usuarios rechazados
    # HU 5.3: Monitor de tickets activos de la empresa
    # HU 5.4: Historial de tickets históricos y cancelados
    
    path("admin-panel/validacion/", views.panel_validacion, name="panel_validacion"),
    path("admin-panel/usuarios/", views.usuarios, name="usuarios"),
    path("admin-panel/usuarios/rechazados/", views.usuarios_rechazados, name="usuarios_rechazados"),
    path("admin-panel/tickets/activos/", views.monitor_tickets_activos, name="monitor_tickets_activos"),
    path("admin-panel/tickets/historial/", views.historial_tickets, name="historial_tickets"),

    # ═══════════════════════════════════════════════════════════════════════════════
    # Épica 6: ABM (Alta, Baja, Modificación) de Flota
    # ═══════════════════════════════════════════════════════════════════════════════
    # HU 6.1: Listado de vehículos
    # HU 6.2: Alta de vehículo
    # HU 6.3: Edición / baja de vehículo
    
    path("admin-panel/analiticas/", views.reporte_analiticas, name="reporte_analiticas"),
    path("admin-panel/analiticas/pdf/", views.reporte_analiticas_pdf, name="reporte_analiticas_pdf"),
    path("admin-panel/flota/", views.listado_flota, name="listado_flota"),
    path("admin-panel/flota/nueva/", views.alta_vehiculo, name="alta_vehiculo"),
    path("admin-panel/flota/<int:vehiculo_id>/editar/", views.edicion_vehiculo, name="edicion_vehiculo"),


    # NUEVO — Verificación de correo electrónico (extensión de HU 1.1)
    #
    # Flujo post-registro:
    #   registro() → guarda usuario con correo_verificado=False
    #             → genera VerificacionCorreo (código + token UUID)
    #             → envía email con ambos métodos
    #             → redirige a /verificar-correo/
    #
    # /verificar-correo/
    #   Vista: views.verificar_correo
    #   GET:  muestra el formulario con dos tabs (código / enlace mágico).
    #   POST accion="reenviar": regenera el registro y reenvía el correo.
    #   POST (sin accion):      valida el código ingresado con VerificacionCodigoForm.
    #   Requiere request.session["verificacion_uid"] para identificar al usuario.
    #
    # /verificar-correo/<uuid:token>/
    #   Vista: views.verificar_correo_enlace
    #   El conversor <uuid:> de Django valida el formato antes de llegar a la vista,
    #   evitando procesar strings malformados. Si el token es válido y vigente,
    #   marca correo_verificado=True y redirige al login con mensaje de éxito.
    path("verificar-correo/", views.verificar_correo, name="verificar_correo"),
    path("verificar-correo/<uuid:token>/", views.verificar_correo_enlace, name="verificar_correo_enlace"),

    # Recuperación de contraseña
    path("recuperar-password/", views.solicitar_recuperacion, name="solicitar_recuperacion"),
    path("recuperar-password/verificar/", views.verificar_recuperacion, name="verificar_recuperacion"),
    path("recuperar-password/verificar/<uuid:token>/", views.verificar_recuperacion_enlace, name="verificar_recuperacion_enlace"),
    path("recuperar-password/nueva/", views.nueva_contrasena, name="nueva_contrasena"),

]
