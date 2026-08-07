"""
Paquete de la aplicación Django 'reservas'.

Sistema de gestión de reservas de vehículos corporativos con lógica de
prioridad jerárquica y resolución automática de conflictos.

Módulos principales:
    - models.py: Definición de entidades (Cargo, Usuario, Vehículo, Ticket).
    - views.py: Vistas tradicionales con templates (HTML).
    - services.py: Motor de reglas de negocio (colisiones, jerarquía).
    - forms.py: Formularios de validación de datos.
    - admin.py: Configuración de Django Admin.
    - urls.py: Enrutamiento HTTP.
    - apps.py: Configuración de la aplicación.

Estructura del proyecto:
    - templates/: Plantillas HTML (vistas tradicionales).
    - management/: Comandos custom de Django (migraciones, seeders).
    - migrations/: Historial de cambios de esquema BD.
    - fixtures/: Datos de prueba para seeding.

Épicas funcionales:
    1. Autenticación (registro, login, validación por admin).
    2. Inicio y gestión de tickets (usuario normal).
    3. Calendario interactivo e integración temporal.
    4. Reglas de negocio (colisiones, prioridad jerárquica).
    5. Supervisión administrativa (directorio, auditoría, monitor).
    6. ABM de vehículos (alta, baja, modificación de vehículos).

Convención de sesión:
    - request.session["usuario_id"]: PK del usuario logueado. Única fuente
      de verdad; toda vista resuelve el Usuario actual con
      get_usuario_sesion(request).
    - request.session["es_admin"]: se guarda por compatibilidad pero NO es
      de fiar para autorización — es una foto tomada en el login que queda
      obsoleta si le cambian el cargo al usuario con la sesión ya abierta.
      Cualquier chequeo de permisos debe recalcular
      usuario.id_cargo.prioridad == 0 en cada request (ver
      admin_requerido/chofer_requerido en views/_base.py).
"""
