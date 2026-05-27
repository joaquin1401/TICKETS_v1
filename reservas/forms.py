"""
Forms para validación y captura de datos del sistema de reservas.

Incluye formularios para autenticación, creación de tickets,
búsqueda y administración de flota. Todos heredan de Django forms
y aplican validaciones tanto a nivel de campo como de formulario.

Convención de sesión utilizada en vistas:
    request.session["usuario_id"]   → PK del usuario logueado
    request.session["es_admin"]     → bool (True si prioridad == 0)
"""

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Usuario, Cargo, Vehiculo, Ticket


# ══════════════════════════════════════════════
# Épica 1 — Autenticación
# ══════════════════════════════════════════════

class RegistroForm(forms.ModelForm):
    """
    Formulario para registro de cuenta de usuario (HU 1.1).

    Valida que las contraseñas coincidan y asegura que los nuevos
    usuarios se crean con estado pendiente (valido=False, rechazado=False).

    Fields:
        nombre (CharField): Nombre de pila.
        apellido (CharField): Apellido.
        correo (EmailField): Email único (validado por modelo).
        id_cargo (ModelChoiceField): Cargo a solicitar.
        contrasena (CharField): Contraseña en texto plano (se hashea en save()).
        confirmar_contrasena (CharField): Validación de coincidencia.

    Validaciones:
        - Las dos contraseñas deben coincidir (método clean).
        - Email debe ser único (validación del modelo).

    Save behavior:
        - Hashea la contraseña usando Usuario.set_password().
        - Establece valido=False y rechazado=False por defecto.
    """

    contrasena = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Contraseña"}),
        label="Contraseña",
    )
    confirmar_contrasena = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Confirmar contraseña"}),
        label="Confirmar contraseña",
    )

    class Meta:
        model = Usuario
        fields = ["nombre", "apellido", "correo", "id_cargo", "contrasena"]
        labels = {
            "nombre": "Nombre",
            "apellido": "Apellido",
            "correo": "Correo electrónico",
            "id_cargo": "Cargo",
        }
        widgets = {
            "nombre":   forms.TextInput(attrs={"placeholder": "Nombre"}),
            "apellido": forms.TextInput(attrs={"placeholder": "Apellido"}),
            "correo":   forms.EmailInput(attrs={"placeholder": "correo@empresa.com"}),
        }

    def clean(self):
        """
        Valida que ambas contraseñas coincidan.

        Raises:
            ValidationError: Si contrasena y confirmar_contrasena no coinciden.

        Returns:
            dict: Datos limpios del formulario.
        """
        cleaned = super().clean()
        p1 = cleaned.get("contrasena")
        p2 = cleaned.get("confirmar_contrasena")
        if p1 and p2 and p1 != p2:
            raise ValidationError("Las contraseñas no coinciden.")
        return cleaned

    def save(self, commit=True):
        """
        Guarda el usuario con contraseña hasheada y estado inicial.

        Args:
            commit (bool): Si False, retorna instancia sin guardar en BD.

        Returns:
            Usuario: Instancia guardada o no según commit.

        Notes:
            Se aseguran los valores iniciales:
            - valido=False (requiere aprobación del admin).
            - rechazado=False (no está explícitamente rechazado).
        """
        usuario = super().save(commit=False)
        usuario.set_password(self.cleaned_data["contrasena"])
        usuario.valido = False
        usuario.rechazado = False
        if commit:
            usuario.save()
        return usuario


class LoginForm(forms.Form):
    """
    Formulario para inicio de sesión (HU 1.2).

    Captura credenciales sin crear registros en BD. La autenticación
    se realiza manualmente en vistas.login_view() contra Usuario.check_password().

    Fields:
        correo (EmailField): Identificador único del usuario.
        contrasena (CharField): Contraseña en texto plano.
    """

    correo = forms.EmailField(
        widget=forms.EmailInput(attrs={"placeholder": "correo@empresa.com"}),
        label="Correo electrónico",
    )
    contrasena = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Contraseña"}),
        label="Contraseña",
    )


# ══════════════════════════════════════════════
# Épica 2 — Creación de Tickets
# ══════════════════════════════════════════════

class TicketForm(forms.ModelForm):
    """
    Formulario para creación rápida de ticket (HU 2.1).

    Captura datos de una reserva de vehículo. Solo muestra vehículos
    activos. La validación temporal y la lógica de conflictos se aplican
    en services.crear_ticket_con_reglas() (HU 4.2, 4.3).

    Fields:
        id_vehiculo (ModelChoiceField): Vehículo a reservar (solo activos).
        destino (CharField): Ubicación de viaje.
        cant_pasajeros (PositiveIntegerField): Ocupantes.
        descripcion (TextField): Motivo, notas.
        hora_inicio (DateTimeField): Fecha y hora de salida.
        hora_fin (DateTimeField, optional): Estimado de regreso.

    Validaciones:
        - hora_inicio debe ser en el futuro.
        - hora_fin, si se proporciona, debe ser > hora_inicio.
        - hora_fin es opcional en el formulario pero requerido en servicios
          (vistas asignan default si está vacío).

    Notes:
        No valida la capacidad del vehículo vs. pasajeros solicitados.
        Esa lógica puede añadirse a nivel de servicios en futuras iteraciones.
    """

    class Meta:
        model = Ticket
        fields = ["id_vehiculo", "destino", "cant_pasajeros", "descripcion", "hora_inicio", "hora_fin"]
        labels = {
            "id_vehiculo":    "Vehículo",
            "destino":        "Destino",
            "cant_pasajeros": "Cantidad de pasajeros",
            "descripcion":    "Descripción / motivo",
            "hora_inicio":    "Fecha y hora de salida",
            "hora_fin":       "Fecha y hora de regreso (estimado)",
        }
        widgets = {
            "destino":     forms.TextInput(attrs={"placeholder": "Ej: Sede central Tucumán"}),
            "descripcion": forms.Textarea(attrs={"rows": 3, "placeholder": "Motivo del viaje"}),
            "hora_inicio": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-control"}, format="%Y-%m-%dT%H:%M"
            ),
            "hora_fin": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-control"}, format="%Y-%m-%dT%H:%M"
            ),
        }

    def __init__(self, *args, **kwargs):
        """
        Inicializa el formulario con configuración de campos.

        - Filtra vehículos para mostrar solo los activos.
        - Establece formatos de entrada para datetime.
        - hora_fin es opcional (required=False).
        """
        super().__init__(*args, **kwargs)
        # Solo mostrar vehículos activos
        self.fields["id_vehiculo"].queryset = Vehiculo.objects.filter(activo=True)
        self.fields["hora_inicio"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["hora_fin"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["hora_fin"].required = False

    def clean(self):
        """
        Valida la lógica temporal del ticket.

        Raises:
            ValidationError: Si hora_inicio <= ahora o hora_fin <= hora_inicio.

        Returns:
            dict: Datos limpios del formulario.
        """
        cleaned = super().clean()
        hora_inicio = cleaned.get("hora_inicio")
        hora_fin = cleaned.get("hora_fin")

        if hora_inicio:
            if hora_inicio <= timezone.now():
                raise ValidationError("La hora de inicio debe ser en el futuro.")

        if hora_inicio and hora_fin:
            if hora_fin <= hora_inicio:
                raise ValidationError("La hora de regreso debe ser posterior a la de salida.")

        return cleaned


# ══════════════════════════════════════════════
# Épica 3 — Consulta de Calendario
# ══════════════════════════════════════════════

class VehiculoSelectorForm(forms.Form):
    """
    Formulario para seleccionar vehículo en vista de calendario (HU 3.1, 3.2).

    Fields:
        vehiculo (ModelChoiceField): Vehículo cuyo calendario se quiere ver.
            Solo muestra vehículos activos.
    """

    vehiculo = forms.ModelChoiceField(
        queryset=Vehiculo.objects.filter(activo=True),
        label="Seleccionar vehículo",
        empty_label="-- Elegir vehículo --",
    )


# ══════════════════════════════════════════════
# Épica 5 — Administración
# ══════════════════════════════════════════════

class FiltroUsuariosForm(forms.Form):
    """
    Formulario de filtrado para directorio de usuarios (HU 5.1).

    Permite buscar usuarios por nombre/apellido/correo y filtrar por cargo.

    Fields:
        busqueda (CharField): Búsqueda libre (icontains en BD).
        cargo (ModelChoiceField): Filtro por cargo (opcional).
    """

    busqueda = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Buscar por nombre o correo..."}),
        label="",
    )
    cargo = forms.ModelChoiceField(
        queryset=Cargo.objects.all(),
        required=False,
        empty_label="Todos los cargos",
        label="Cargo",
    )


# ══════════════════════════════════════════════
# Épica 6 — ABM de Flota
# ══════════════════════════════════════════════

class VehiculoForm(forms.ModelForm):
    """
    Formulario para alta y edición de vehículos (HU 6.2, 6.3).

    Permite crear y modificar registros de vehículos en la flota.
    El flag 'activo' controla si el vehículo aparece en formularios de reserva.

    Fields:
        marca (CharField): Fabricante del vehículo.
        modelo (CharField): Modelo específico.
        cant_pasajeros (PositiveIntegerField): Capacidad.
        activo (BooleanField): Disponibilidad operativa.
    """

    class Meta:
        model = Vehiculo
        fields = ["marca", "modelo", "cant_pasajeros", "activo"]
        labels = {
            "marca":          "Marca",
            "modelo":         "Modelo",
            "cant_pasajeros": "Capacidad de pasajeros",
            "activo":         "Vehículo activo (disponible para reservas)",
        }
        widgets = {
            "marca":  forms.TextInput(attrs={"placeholder": "Ej: Toyota"}),
            "modelo": forms.TextInput(attrs={"placeholder": "Ej: Hilux 2023"}),
        }
