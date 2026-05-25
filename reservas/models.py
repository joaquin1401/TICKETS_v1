"""
models.py - Definición de modelos de datos para el sistema de reservas.

Principios aplicados:
- Separación de responsabilidades: modelos contienen solo definición de datos y validación de integridad
- No contiene lógica de negocio compleja (eso va en services.py)
- Utiliza custom managers para consultas frecuentes
- Type hints para mejor documentación
- Métodos clean() para validaciones antes de guardar

Nota de arquitectura:
La lógica de contraseña (set_password, check_password) se mantiene aquí por ser
responsabilidad del modelo Usuario mantener su integridad de autenticación.
El validador de colisiones de tickets y reglas de prioridad están en services.py.
"""

from typing import Optional
from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from django.core.exceptions import ValidationError
from django.utils import timezone


# ─────────────────────────────────────────────────────────────────────────────
# Managers Personalizados (reutilizables en consultas)
# ─────────────────────────────────────────────────────────────────────────────

class UsuarioManager(models.Manager):
    """
    Manager para modelo Usuario.
    
    Propósito: Encapsular consultas frecuentes de Usuario para evitar duplicación
    en vistas y mantener optimizaciones centralizadas (select_related, prefetch_related).
    """
    
    def activos(self) -> models.QuerySet:
        """
        Retorna solo usuarios aprobados (válidos).
        
        Optimización: incluye cargo para evitar consultas N+1
        cuando se accede a id_cargo.nombre o id_cargo.prioridad.
        """
        return self.filter(valido=True).select_related("id_cargo")
    
    def pendientes(self) -> models.QuerySet:
        """Retorna usuarios pendientes de aprobación."""
        return self.filter(valido=False, rechazado=False).select_related("id_cargo")
    
    def rechazados(self) -> models.QuerySet:
        """Retorna usuarios explícitamente rechazados."""
        return self.filter(rechazado=True).select_related("id_cargo")
    
    def con_cargo(self) -> models.QuerySet:
        """Retorna todos con cargo (select_related para evitar N+1)."""
        return self.select_related("id_cargo")


class VehiculoManager(models.Manager):
    """Manager para modelo Vehiculo."""
    
    def disponibles(self) -> models.QuerySet:
        """Retorna solo vehículos activos (no dados de baja)."""
        return self.filter(activo=True)


class TicketManager(models.Manager):
    """
    Manager para modelo Ticket.
    
    Propósito: Consultas frecuentes de tickets evitando N+1 queries.
    """
    
    def aprobados(self) -> models.QuerySet:
        """
        Retorna tickets aprobados con relaciones precargadas.
        
        select_related: usuario, vehículo, y cargo del usuario
        Evita 3 queries (N+1) por cada acceso a estas relaciones.
        """
        return self.filter(
            estado=Ticket.ESTADO_APROBADO
        ).select_related("id_usuario", "id_vehiculo", "id_usuario__id_cargo")
    
    def del_usuario(self, usuario) -> models.QuerySet:
        """Retorna todos los tickets de un usuario con optimizaciones."""
        return self.filter(
            id_usuario=usuario
        ).select_related("id_vehiculo", "id_usuario__id_cargo").order_by("-hora_inicio")
    
    def del_vehiculo_en_rango(self, vehiculo, hora_inicio, hora_fin) -> models.QuerySet:
        """
        Retorna tickets aprobados de un vehículo que solapan con rango de tiempo.
        
        Parámetros:
            vehiculo: Instancia de Vehiculo
            hora_inicio: datetime de inicio del rango
            hora_fin: datetime de fin del rango
        
        Lógica: Detecta solapamiento si:
            ticket.hora_inicio < hora_fin AND ticket.hora_fin > hora_inicio
        """
        return self.filter(
            id_vehiculo=vehiculo,
            estado=Ticket.ESTADO_APROBADO,
            hora_inicio__lt=hora_fin,
            hora_fin__gt=hora_inicio,
        ).select_related("id_usuario", "id_usuario__id_cargo")


# ─────────────────────────────────────────────────────────────────────────────
# Modelos
# ─────────────────────────────────────────────────────────────────────────────

class Cargo(models.Model):
    """
    Modelo para cargos/roles del sistema (Decano, Secretario, Usuario).
    
    Atributos:
        nombre: Cargo único (choice restringido a 3 valores)
        prioridad: Número que define jerarquía (menor = mayor autoridad)
                   Ejemplo: Decano=0, Secretario=1, Usuario=2
    
    Notas de diseño:
    - Los cargos son configuración estática, no deberían cambiar frecuentemente
    - La prioridad numérica permite comparaciones simples (x <= y)
    - NEVER permitir delete en cascada de usuarios (PROTECT)
    """
    
    DECANO = "Decano"
    SECRETARIO = "Secretario"
    USUARIO = "Usuario"

    CARGOS_CHOICES = [
        (DECANO, "Decano"),
        (SECRETARIO, "Secretario"),
        (USUARIO, "Usuario"),
    ]

    nombre = models.CharField(
        max_length=100,
        choices=CARGOS_CHOICES,
        unique=True,
        help_text="Cargo único (Decano, Secretario, Usuario)"
    )
    prioridad = models.PositiveIntegerField(
        help_text="Número menor = mayor jerarquía (0=Decano=máxima, 2=Usuario=mínima)"
    )

    class Meta:
        verbose_name = "Cargo"
        verbose_name_plural = "Cargos"
        ordering = ["prioridad"]

    def __str__(self) -> str:
        return f"{self.nombre} (prioridad {self.prioridad})"


class Usuario(models.Model):
    """
    Modelo de Usuario del sistema.
    
    Estados posibles:
    1. valido=False, rechazado=False → Pendiente de aprobación
    2. valido=True, rechazado=False → Aprobado y activo
    3. valido=False, rechazado=True → Rechazado (no puede ingresar)
    
    Responsabilidades:
    - Gestionar credenciales (contrasena hasheada)
    - Mantener referencia a cargo (prioridad heredada)
    - Validar estado de aprobación
    
    Nota: La validación de colisiones y prioridad entre tickets está en services.py,
    NO aquí, porque es lógica de negocio, no integridad de datos.
    """
    
    objects = UsuarioManager()
    
    id_cargo = models.ForeignKey(
        Cargo,
        on_delete=models.PROTECT,
        related_name="usuarios",
        help_text="Cargo del usuario (determina prioridad)"
    )
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    contrasena = models.CharField(max_length=255)
    correo = models.EmailField(unique=True)
    valido = models.BooleanField(
        default=False,
        db_index=True,  # Índice porque se filtra frecuentemente
        help_text="True = aprobado por admin, False = pendiente o rechazado"
    )
    rechazado = models.BooleanField(
        default=False,
        db_index=True,  # Índice porque se filtra frecuentemente
        help_text="True = fue explícitamente rechazado por el admin"
    )
    creado_el = models.DateTimeField(auto_now_add=True)
    actualizado_el = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"
        indexes = [
            models.Index(fields=["valido", "rechazado"]),  # Para queries de filtrado
            models.Index(fields=["correo"]),  # Para login
        ]

    def __str__(self) -> str:
        return f"{self.nombre} {self.apellido} ({self.correo})"

    def set_password(self, raw_password: str) -> None:
        """
        Hashea y almacena la contraseña de forma segura.
        
        Parámetros:
            raw_password: Contraseña en texto plano a hashear
        
        Nota: Usa Django's make_password (PBKDF2 por defecto)
        """
        self.contrasena = make_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        """
        Verifica si la contraseña proporcionada coincide con la almacenada.
        
        Parámetros:
            raw_password: Contraseña en texto plano a verificar
        
        Retorna:
            True si coincide, False si no
        """
        return check_password(raw_password, self.contrasena)

    def puede_ingresar(self) -> bool:
        """
        Determina si el usuario puede ingresar al sistema.
        
        Retorna True solo si está aprobado (valido=True) y no rechazado.
        """
        return self.valido and not self.rechazado

    def clean(self) -> None:
        """
        Validaciones de integridad antes de guardar.
        
        Nota: Django llama esto en formularios y algunas vistas,
        pero NO automáticamente en model.save(). Debe llamarse manualmente
        o desde forms/serializers.
        """
        if self.valido and self.rechazado:
            raise ValidationError(
                "Un usuario no puede estar simultáneamente aprobado y rechazado."
            )

    @property
    def nombre_completo(self) -> str:
        """Retorna el nombre completo formateado."""
        return f"{self.nombre} {self.apellido}"

    @property
    def prioridad(self) -> int:
        """
        Retorna el número de prioridad del usuario (heredado de su cargo).
        
        Nota: Accede a id_cargo.prioridad. Si no está cargado (select_related),
        esto genera una query extra. Considerar usar select_related en consultas.
        """
        return self.id_cargo.prioridad

    @property
    def es_admin(self) -> bool:
        """
        Determina si el usuario tiene permisos de administrador.
        
        Lógica: Admin es quien tiene el cargo con prioridad 0 (Decano).
        
        Nota: Accede a id_cargo, requiere select_related para evitar N+1.
        """
        return self.id_cargo.prioridad == 0


class Vehiculo(models.Model):
    """
    Modelo de Vehículos de la flota.
    
    Responsabilidades:
    - Definir características del vehículo (marca, modelo, capacidad)
    - Mantener estado (activo/dado de baja)
    
    Nota: La lógica de disponibilidad/colisiones está en services.py
    """
    
    objects = VehiculoManager()
    
    marca = models.CharField(max_length=100)
    modelo = models.CharField(max_length=100)
    cant_pasajeros = models.PositiveIntegerField()
    activo = models.BooleanField(
        default=True,
        db_index=True,
        help_text="False = dado de baja (ej: fue al taller permanente)"
    )
    placa = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        null=True,
        help_text="Placa o identificador único del vehículo"
    )
    creado_el = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Vehículo"
        verbose_name_plural = "Vehículos"
        ordering = ["marca", "modelo"]

    def __str__(self) -> str:
        return f"{self.marca} {self.modelo} ({self.cant_pasajeros} pasajeros)"


class Ticket(models.Model):
    """
    Modelo de Ticket/Reserva de vehículo.
    
    Estados:
    - "pendiente": Recién creado, esperando procesamiento (NO SE USA actualmente)
    - "aprobado": Reserva confirmada (puede ser sobrescrita si otra tiene mayor prioridad)
    - "cancelado": Cancelada (por usuario, por admin, o por sobrescritura de jerarquía)
    
    Flujo de creación (ver services.tickets_service.crear_ticket_con_reglas):
    1. Usuario solicita reserva → se ejecuta lógica de prioridad
    2. Si no hay conflictos → ticket se crea como APROBADO
    3. Si hay conflictos:
       a. Si solicitante tiene MENOR prioridad → RECHAZADO (no crea ticket)
       b. Si solicitante tiene MAYOR prioridad → crea APROBADO y cancela otros
    
    Nota de diseño:
    - hora_fin puede ser NULL porque algunos casos no necesitan retorno exacto
    - observacion se llena automáticamente cuando se cancela por jerarquía
    - La detección de conflictos está en services.py (lógica de negocio)
    """
    
    # Constantes de estado
    ESTADO_PENDIENTE = "pendiente"
    ESTADO_APROBADO = "aprobado"
    ESTADO_CANCELADO = "cancelado"

    ESTADOS = [
        (ESTADO_PENDIENTE, "Pendiente"),
        (ESTADO_APROBADO, "Aprobado"),
        (ESTADO_CANCELADO, "Cancelado"),
    ]
    
    objects = TicketManager()

    id_usuario = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name="tickets",
        help_text="Usuario que solicitó la reserva"
    )
    id_vehiculo = models.ForeignKey(
        Vehiculo,
        on_delete=models.PROTECT,
        related_name="tickets",
        help_text="Vehículo reservado"
    )
    destino = models.CharField(max_length=255)
    cant_pasajeros = models.PositiveIntegerField()
    descripcion = models.TextField(
        blank=True,
        help_text="Motivo o detalles de la reserva"
    )
    hora_inicio = models.DateTimeField(
        db_index=True,
        help_text="Hora de salida"
    )
    hora_fin = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Hora estimada de regreso (opcional)"
    )
    estado = models.CharField(
        max_length=20,
        choices=ESTADOS,
        default=ESTADO_PENDIENTE,
        db_index=True,
        help_text="Estado actual de la reserva"
    )
    fecha = models.DateField(
        auto_now_add=True,
        help_text="Fecha en que se creó la solicitud"
    )
    observacion = models.TextField(
        blank=True,
        help_text="Se completa automáticamente si el ticket es cancelado por jerarquía"
    )
    creado_el = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ticket"
        verbose_name_plural = "Tickets"
        ordering = ["-hora_inicio"]
        indexes = [
            models.Index(fields=["id_vehiculo", "estado", "hora_inicio"]),
            models.Index(fields=["id_usuario", "-hora_inicio"]),
        ]

    def __str__(self) -> str:
        return f"Ticket #{self.pk} - {self.id_usuario.nombre_completo} → {self.destino}"

    def puede_ser_cancelado(self) -> bool:
        """
        Determina si el ticket puede ser cancelado por usuario.
        
        Lógica: Solo tickets aprobados en el futuro pueden ser cancelados.
        
        Retorna:
            True si puede ser cancelado, False si no
        """
        return (
            self.estado == self.ESTADO_APROBADO
            and self.hora_inicio > timezone.now()
        )
    
    def esta_en_progreso(self) -> bool:
        """Determina si el ticket está en curso (entre hora_inicio y hora_fin)."""
        ahora = timezone.now()
        return (
            self.hora_inicio <= ahora
            and (self.hora_fin is None or ahora <= self.hora_fin)
        )
