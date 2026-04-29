from django.db import models
from django.contrib.auth.hashers import make_password


class Cargo(models.Model):
    nombre = models.CharField(max_length=100)
    prioridad = models.PositiveIntegerField(
        help_text="Número menor = mayor jerarquía (1 = máxima prioridad)"
    )

    class Meta:
        verbose_name = "Cargo"
        verbose_name_plural = "Cargos"
        ordering = ["prioridad"]

    def __str__(self):
        return f"{self.nombre} (prioridad {self.prioridad})"


class Usuario(models.Model):
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
        self.contrasena = make_password(raw_password)

    def check_password(self, raw_password):
        from django.contrib.auth.hashers import check_password
        return check_password(raw_password, self.contrasena)

    @property
    def nombre_completo(self):
        return f"{self.nombre} {self.apellido}"

    @property
    def prioridad(self):
        return self.id_cargo.prioridad


class Vehiculo(models.Model):
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
