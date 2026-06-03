"""
Models para el sistema de reserva de vehículos.

Define las entidades principales del dominio:
- Cargo: Jerarquía organizacional de usuarios.
- Usuario: Cuentas de usuario con control de acceso por cargo.
- Vehículo: Flota disponible para reservas.
- Ticket: Solicitudes de reserva con lógica de conflictos y jerarquía.

Este módulo integra con la lógica de negocio en services.py para resolver
conflictos de disponibilidad según la prioridad del cargo del solicitante.
"""

from django.db import models
from django.contrib.auth.hashers import make_password


class Cargo(models.Model):
    """
    Representa los roles jerárquicos en la organización.

    Un cargo define la posición de un usuario en la jerarquía,
    determinando su capacidad de sobrescribir reservas conflictivas.
    Los números de prioridad menores indican mayor jerarquía.
    El Administrador SEU posee prioridad 0 para control total.

    Attributes:
        nombre (CharField): Nombre único del cargo (Decano, Secretario, Usuario).
        prioridad (PositiveIntegerField): Número de prioridad jerárquica.
            Menor número = mayor jerarquía. Utilizado en la resolución
            de conflictos de reservas según HU 4.2 y 4.3.
    """

    DECANO = "Decano"
    SECRETARIO = "Secretario"
    USUARIO = "Usuario"
    ADMIN_SEU = "Administrador SEU"

    CARGOS_CHOICES = [
        (DECANO, "Decano"),
        (SECRETARIO, "Secretario"),
        (USUARIO, "Usuario"),
        (ADMIN_SEU, "Administrador SEU"),
    ]

    nombre = models.CharField(max_length=100, choices=CARGOS_CHOICES, unique=True)
    prioridad = models.PositiveIntegerField(
        help_text="Número menor = mayor jerarquía (0 = Administrador SEU / Máxima prioridad)"
    )

    class Meta:
        verbose_name = "Cargo"
        verbose_name_plural = "Cargos"
        ordering = ["prioridad"]

    def __str__(self):
        return f"{self.nombre} (prioridad {self.prioridad})"



class Usuario(models.Model):
    """
    Representa una cuenta de usuario en el sistema.

    Implementa un flujo de validación de dos fases:
    1. Registro inicial: valido=False, rechazado=False (pendiente aprobación).
    2. Aprobación o rechazo por administrador.

    La contraseña se almacena hasheada usando make_password(). Proporciona
    métodos helpers para seguridad: set_password() y check_password().

    Attributes:
        id_cargo (ForeignKey): Relación con Cargo. Determina la jerarquía
            para resolución de conflictos de reservas (ver HU 4.2 y 4.3).
        nombre (CharField): Nombre de pila del usuario.
        apellido (CharField): Apellido del usuario.
        contrasena (CharField): Contraseña hasheada (max 255 caracteres
            para soportar bcrypt y algoritmos modernos).
        correo (EmailField): Email único. Utilizado como identificador
            primario en login (ver HU 1.2).
        valido (BooleanField): Indica si la cuenta fue aprobada por admin.
            False = pendiente o rechazada.
        rechazado (BooleanField): Indica si fue explícitamente rechazado.
            Permite distinguir entre pendiente y rechazado en login.

    Properties:
        nombre_completo: Retorna "{nombre} {apellido}".
        prioridad: Retorna el número de prioridad del cargo asociado.
    """

    id_cargo = models.ForeignKey(
        Cargo, on_delete=models.PROTECT, related_name="usuarios"
    )
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    contrasena = models.CharField(max_length=255)
    correo = models.EmailField(unique=True)
    valido = models.BooleanField(
        default=False,
        help_text="True = aprobado por admin, False = pendiente o rechazado"
    )
    rechazado = models.BooleanField(
        default=False,
        help_text="True = fue explícitamente rechazado por el admin"
    )

    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"

    def __str__(self):
        return f"{self.nombre} {self.apellido} ({self.correo})"

    def set_password(self, raw_password):
        """
        Hash y almacena la contraseña en formato seguro.

        Args:
            raw_password (str): Contraseña en texto plano.

        Notes:
            Utiliza make_password() de Django, que por defecto usa
            PBKDF2. No retorna nada; modifica self.contrasena in-place.
        """
        self.contrasena = make_password(raw_password)

    def check_password(self, raw_password):
        """
        Verifica si la contraseña proporcionada coincide con el hash almacenado.

        Args:
            raw_password (str): Contraseña en texto plano a verificar.

        Returns:
            bool: True si la contraseña es correcta, False en caso contrario.

        Notes:
            Utiliza check_password() de Django para comparación segura
            contra ataques de timing.
        """
        from django.contrib.auth.hashers import check_password
        return check_password(raw_password, self.contrasena)

    @property
    def nombre_completo(self):
        """
        Retorna el nombre completo del usuario.

        Returns:
            str: Concatenación de nombre y apellido separados por espacio.
        """
        return f"{self.nombre} {self.apellido}"

    @property
    def prioridad(self):
        """
        Retorna la prioridad jerárquica del usuario.

        Returns:
            int: Número de prioridad del cargo asociado. Menor número
                indica mayor jerarquía (utilizado en HU 4.2 y 4.3).
        """
        return self.id_cargo.prioridad


class Vehiculo(models.Model):
    """
    Representa un vehículo en la flota corporativa.

    Los vehículos son el recurso central que se reserva mediante tickets.
    La disponibilidad se determina por conflictos de tiempo en tickets
    aprobados (ver HU 3.1 y HU 4.1).

    Attributes:
        marca (CharField): Fabricante del vehículo (ej: Toyota, Mercedes).
        modelo (CharField): Modelo específico (ej: Hilux 2023).
        cant_pasajeros (PositiveIntegerField): Capacidad de ocupantes.
            Debe coincidir o superar la solicitada en tickets.
        activo (BooleanField): Indica disponibilidad operativa.
            False = dado de baja (ej: taller permanente, jubilado).
            Solo vehículos activos aparecen en formularios de reserva.
    """

    marca = models.CharField(max_length=100)
    modelo = models.CharField(max_length=100)
    cant_pasajeros = models.PositiveIntegerField()
    activo = models.BooleanField(
        default=True,
        help_text="False = dado de baja (ej: fue al taller permanente)"
    )

    class Meta:
        verbose_name = "Vehículo"
        verbose_name_plural = "Vehículos"

    def __str__(self):
        return f"{self.marca} {self.modelo} ({self.cant_pasajeros} pasajeros)"


class Ticket(models.Model):
    """
    Representa una solicitud de reserva de vehículo.

    Un ticket encapsula el acto de reservar un vehículo para un período
    específico. La creación está regida por reglas de conflicto y jerarquía
    implementadas en services.crear_ticket_con_reglas() (HU 4.2 y 4.3).

    Estados:
        - ESTADO_PENDIENTE: No usado actualmente; se crean directamente
          como APROBADO o se rechazan.
        - ESTADO_APROBADO: Reserva activa; se considera en cálculos
          de conflictos.
        - ESTADO_CANCELADO: Reserva anulada. Se registra observación
          con motivo.

    Atributos:
        id_usuario (ForeignKey): Usuario solicitante. Eliminar usuario
            elimina sus tickets (CASCADE).
        id_vehiculo (ForeignKey): Vehículo reservado. No puede eliminarse
            si tiene tickets (PROTECT).
        destino (CharField): Ubicación o propósito del viaje.
        cant_pasajeros (PositiveIntegerField): Ocupantes confirmados.
            No se valida contra vehiculo.cant_pasajeros en el modelo;
            esa validación ocurre en formularios/servicios.
        descripcion (TextField): Motivo, notas adicionales del viaje.
        hora_inicio (DateTimeField): Fecha y hora de salida.
        hora_fin (DateTimeField, null=True): Estimado de regreso.
            Opcional (permitido en formulario si se deja vacío,
            se asigna predeterminado en vistas).
        estado (CharField): Estado actual del ticket (enum mediante choices).
        fecha (DateField): Fecha de creación, auto_now_add=True.
            Metadato de auditoría.
        observacion (TextField): Notas administrativas.
            Se completa automáticamente si el ticket se cancela por
            sobrescritura jerárquica (ver services.crear_ticket_con_reglas).

    Validaciones adicionales:
        - Realizada en forms.TicketForm.clean(): hora_inicio > now(),
          hora_fin > hora_inicio.
        - Conflictos de disponibilidad: services.obtener_tickets_en_conflicto().
        - Resolución de conflictos: services.crear_ticket_con_reglas().
    """

    ESTADO_PENDIENTE = "pendiente"
    ESTADO_APROBADO = "aprobado"
    ESTADO_CANCELADO = "cancelado"

    ESTADOS = [
        (ESTADO_PENDIENTE, "Pendiente"),
        (ESTADO_APROBADO, "Aprobado"),
        (ESTADO_CANCELADO, "Cancelado"),
    ]

    id_usuario = models.ForeignKey(
        Usuario, on_delete=models.CASCADE, related_name="tickets"
    )
    id_vehiculo = models.ForeignKey(
        Vehiculo, on_delete=models.PROTECT, related_name="tickets"
    )
    destino = models.CharField(max_length=255)
    cant_pasajeros = models.PositiveIntegerField()
    descripcion = models.TextField(blank=True)
    hora_inicio = models.DateTimeField()
    hora_fin = models.DateTimeField(
        null=True, blank=True,
        help_text="Opcional: hora estimada de regreso"
    )
    estado = models.CharField(
        max_length=20, choices=ESTADOS, default=ESTADO_PENDIENTE
    )
    fecha = models.DateField(auto_now_add=True)
    observacion = models.TextField(
        blank=True,
        help_text="Se completa automáticamente si el ticket es cancelado por jerarquía"
    )

    class Meta:
        verbose_name = "Ticket"
        verbose_name_plural = "Tickets"
        ordering = ["-hora_inicio"]

    def __str__(self):
        return f"Ticket #{self.pk} - {self.id_usuario} -> {self.destino} ({self.estado})"


class NotificationLog(models.Model):
    """
    Registro de notificaciones enviadas para evitar reenvíos duplicados.

    Se usa para marcar que un `Ticket` ya recibió cierto tipo de notificación
    (recordatorio 3 días, recordatorio mismo día, aviso de cancelación, etc.).
    """

    TYPE_CREATED = "created"
    TYPE_CANCELLED = "cancelled"
    TYPE_REMINDER_3_DAYS = "reminder_3_days"
    TYPE_REMINDER_SAME_DAY = "reminder_same_day"

    TYPES = [
        (TYPE_CREATED, "Creación"),
        (TYPE_CANCELLED, "Cancelación"),
        (TYPE_REMINDER_3_DAYS, "Recordatorio 3 días"),
        (TYPE_REMINDER_SAME_DAY, "Recordatorio mismo día"),
    ]

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="notification_logs")
    notification_type = models.CharField(max_length=50, choices=TYPES)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Notification Log"
        verbose_name_plural = "Notification Logs"
        indexes = [models.Index(fields=["notification_type", "sent_at"])]

    def __str__(self):
        return f"{self.notification_type} @ {self.ticket_id} -> {self.sent_at.isoformat()}"



# ══════════════════════════════════════════════════════════════════════════════
# NUEVO: Verificación de correo electrónico
# ══════════════════════════════════════════════════════════════════════════════

class VerificacionCorreo(models.Model):
    """
    Almacena el token/código de verificación de correo electrónico.

    Cada usuario tiene como máximo UN registro activo a la vez. Al solicitar
    un reenvío el registro anterior se elimina y se genera uno nuevo.

    Soporta dos métodos de verificación en simultáneo (ambos en el mismo envío):
        1. Código de 6 dígitos: el usuario lo escribe en el formulario.
        2. Token UUID:          se incluye como enlace mágico en el correo.

    Ambos métodos expiran 30 minutos desde la creación. Una vez usado
    cualquiera de los dos, el campo 'usado' pasa a True e invalida ambos.

    Flujo completo:
        registro() → crear_verificacion() → enviar_correo_verificacion()
              ↓ usuario recibe email con código y enlace
        verificar_correo()          ← opción 1: formulario con código
        verificar_correo_enlace()   ← opción 2: clic en el enlace

    Attributes:
        usuario (OneToOneField): Relación 1-a-1 con Usuario. Si el usuario
            se elimina, su verificación también (CASCADE).
        codigo (CharField): Código numérico de 6 dígitos con zero-padding
            (ej: "048721"). Generado con random.randint(0, 999999).
        token (UUIDField): UUID v4 único para construir la URL del enlace
            mágico (ej: /verificar-correo/550e8400-e29b-41d4-...).
        creado_en (DateTimeField): Timestamp automático. Base para calcular
            la expiración de 30 minutos en esta_vigente().
        usado (BooleanField): True si ya fue verificado (por cualquier método).
            Previene reutilización del mismo código o enlace.

    Methods:
        esta_vigente(): Retorna True si no fue usado y no expiró.
    """

    usuario = models.OneToOneField(
        Usuario,
        on_delete=models.CASCADE,
        related_name="verificacion",
        help_text="Usuario propietario de esta verificación"
    )
    codigo = models.CharField(
        max_length=6,
        help_text="Código numérico de 6 dígitos enviado por correo"
    )
    token = models.UUIDField(
        unique=True,
        help_text="Token UUID v4 para el enlace mágico del correo"
    )
    creado_en = models.DateTimeField(
        auto_now_add=True,
        help_text="Momento de generación. El registro expira a los 30 minutos."
    )
    usado = models.BooleanField(
        default=False,
        help_text="True = ya verificado. Invalida tanto el código como el token."
    )

    class Meta:
        verbose_name = "Verificación de correo"
        verbose_name_plural = "Verificaciones de correo"

    def __str__(self):
        estado = "usada" if self.usado else "pendiente"
        return f"Verificación de {self.usuario.correo} ({estado})"

    def esta_vigente(self):
        """
        Determina si el código/token todavía puede usarse para verificar.

        Evalúa dos condiciones:
            1. El registro no fue marcado como usado.
            2. No pasaron más de 30 minutos desde su creación.

        Returns:
            bool: True si está vigente y puede verificar, False si no.

        Notes:
            Usa timezone.now() para ser compatible con USE_TZ=True
            configurado en settings.py.
        """
        from django.utils import timezone
        from datetime import timedelta
        return (
            not self.usado
            and timezone.now() < self.creado_en + timedelta(minutes=30)
        )
