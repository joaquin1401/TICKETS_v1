"""
Configuración de Django Admin para el sistema de reservas.

Define personalizaciones de la interfaz de administración Django para
los modelos Cargo, Usuario, Vehículo y Ticket. Incluye filtros, búsquedas,
formularios especiales y campos calculados para facilitar la gestión.
"""

from django.contrib import admin
from django import forms
from .models import Cargo, Usuario, Vehiculo, Ticket


# ══════════════════════════════════════════════
# Cargo — Administración simple
# ══════════════════════════════════════════════

@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    """
    Interfaz de administración para los cargos jerárquicos.

    Attributes:
        list_display (tuple): Columnas visibles en listado (nombre, prioridad).
        ordering (tuple): Orden predeterminado por prioridad ascendente.
    """
    list_display = ("nombre", "prioridad")
    ordering = ("prioridad",)


# ══════════════════════════════════════════════
# Usuario — Formulario y administración personalizados
# ══════════════════════════════════════════════

class UsuarioForm(forms.ModelForm):
    """
    Formulario personalizado para edición de usuarios en admin.

    Permite editar la contraseña sin forzar obligatoriedad,
    dejando en blanco para mantener la actual. Utiliza set_password()
    automáticamente si se proporciona una nueva contraseña.

    Fields:
        contrasena (CharField): Campo de contraseña opcional.
            Si está vacío, se mantiene la anterior.
    """
    contrasena = forms.CharField(
        widget=forms.PasswordInput,
        required=False,
        label="Contraseña",
        help_text="Dejar en blanco para mantener la contraseña actual."
    )

    class Meta:
        model = Usuario
        fields = "__all__"

    def save(self, commit=True):
        """
        Guarda el usuario hasheando la contraseña si se proporcionó.

        Args:
            commit (bool): Si False, retorna instancia sin guardar en BD.

        Returns:
            Usuario: Instancia guardada o no según commit.

        Notes:
            Si el campo contrasena tiene valor, se usa set_password()
            para hashearla adecuadamente. Si está vacío, se mantiene
            el hash anterior.
        """
        instance = super().save(commit=False)
        password = self.cleaned_data.get("contrasena")
        if password:
            instance.set_password(password)
        if commit:
            instance.save()
        return instance


@admin.register(Usuario)
class UsuarioAdmin(admin.ModelAdmin):
    """
    Interfaz de administración para usuarios.

    Incluye filtros por estado de validación/rechazo, búsqueda por nombre/correo,
    y un campo calculado (nombre_completo) en el listado.

    Attributes:
        form (ModelForm): UsuarioForm personalizado para edición.
        list_display (tuple): Columnas visibles (nombre completo, correo, cargo, validación).
        list_filter (tuple): Filtros disponibles en sidebar (validación, cargo).
        search_fields (tuple): Campos permisos para búsqueda.
    """
    form = UsuarioForm
    list_display = ("nombre_completo", "correo", "id_cargo", "valido", "rechazado")
    list_filter = ("valido", "rechazado", "id_cargo")
    search_fields = ("nombre", "apellido", "correo")

    def nombre_completo(self, obj):
        """
        Método administrativo que retorna el nombre completo del usuario.

        Args:
            obj (Usuario): Instancia de usuario.

        Returns:
            str: Concatenación de nombre y apellido.

        Notes:
            Accesible en list_display como campo personalizado.
        """
        return obj.nombre_completo
    nombre_completo.short_description = "Nombre"


# ══════════════════════════════════════════════
# Vehículo — Administración con filtros
# ══════════════════════════════════════════════

@admin.register(Vehiculo)
class VehiculoAdmin(admin.ModelAdmin):
    """
    Interfaz de administración para los vehículos.

    Permite filtrar vehículos por estado activo/inactivo y marca,
    y buscar por marca y modelo.

    Attributes:
        list_display (tuple): Columnas visibles (marca, modelo, capacidad, estado).
        list_filter (tuple): Filtros disponibles (activo, marca).
        search_fields (tuple): Campos permisos para búsqueda (marca, modelo).
    """
    list_display = ("marca", "modelo", "cant_pasajeros", "activo")
    list_filter = ("activo", "marca")
    search_fields = ("marca", "modelo")


# ══════════════════════════════════════════════
# Ticket — Administración con auditoría
# ══════════════════════════════════════════════

@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    """
    Interfaz de administración para tickets (reservas).

    Proporciona listado de tickets con filtros por estado y vehículo,
    búsqueda por destino y usuario. Los campos fecha y observacion
    son de solo lectura para auditoría.

    Attributes:
        list_display (tuple): Columnas visibles (ID, usuario, vehículo, destino,
            horas, estado).
        list_filter (tuple): Filtros disponibles (estado, vehículo).
        search_fields (tuple): Campos permisos para búsqueda.
        readonly_fields (tuple): Campos no editables en formulario
            (fecha auto-generada, observacion de auditoría).
        ordering (tuple): Orden predeterminado descendente por hora_inicio
            (más recientes primero).
    """
    list_display = ("id", "id_usuario", "id_vehiculo", "destino", "hora_inicio", "hora_fin", "estado")
    list_filter = ("estado", "id_vehiculo")
    search_fields = ("destino", "id_usuario__nombre", "id_usuario__apellido")
    readonly_fields = ("fecha", "observacion")
    ordering = ("-hora_inicio",)
