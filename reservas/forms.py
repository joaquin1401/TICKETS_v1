from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Usuario, Cargo, Vehiculo, Ticket


# ──────────────────────────────────────────────
# Épica 1 — Autenticación
# ──────────────────────────────────────────────

class RegistroForm(forms.ModelForm):
    """HU 1.1 — Registro de cuenta."""
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
        cleaned = super().clean()
        p1 = cleaned.get("contrasena")
        p2 = cleaned.get("confirmar_contrasena")
        if p1 and p2 and p1 != p2:
            raise ValidationError("Las contraseñas no coinciden.")
        return cleaned

    def save(self, commit=True):
        usuario = super().save(commit=False)
        usuario.set_password(self.cleaned_data["contrasena"])
        usuario.valido = False
        usuario.rechazado = False
        if commit:
            usuario.save()
        return usuario


class LoginForm(forms.Form):
    """HU 1.2 — Inicio de sesión."""
    correo = forms.EmailField(
        widget=forms.EmailInput(attrs={"placeholder": "correo@empresa.com"}),
        label="Correo electrónico",
    )
    contrasena = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Contraseña"}),
        label="Contraseña",
    )


# ──────────────────────────────────────────────
# Épica 2 — Tickets (usuario normal)
# ──────────────────────────────────────────────

class TicketForm(forms.ModelForm):
    """HU 2.1 — Creación rápida de ticket."""

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
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "hora_fin": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo mostrar vehículos activos
        self.fields["id_vehiculo"].queryset = Vehiculo.objects.filter(activo=True)
        self.fields["hora_inicio"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["hora_fin"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["hora_fin"].required = False

    def clean(self):
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


# ──────────────────────────────────────────────
# Épica 3 — Consulta de calendario
# ──────────────────────────────────────────────

class VehiculoSelectorForm(forms.Form):
    """HU 3.1 — Selección de vehículo para ver calendario."""
    vehiculo = forms.ModelChoiceField(
        queryset=Vehiculo.objects.filter(activo=True),
        label="Seleccionar vehículo",
        empty_label="-- Elegir vehículo --",
    )


# ──────────────────────────────────────────────
# Épica 5 — Administración
# ──────────────────────────────────────────────

class FiltroUsuariosForm(forms.Form):
    """HU 5.1 — Filtro del directorio de usuarios."""
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


# ──────────────────────────────────────────────
# Épica 6 — ABM de flota
# ──────────────────────────────────────────────

class VehiculoForm(forms.ModelForm):
    """HU 6.2 / 6.3 — Alta y edición de vehículo."""

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
