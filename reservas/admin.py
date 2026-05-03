from django.contrib import admin
from django import forms
from .models import Cargo, Usuario, Vehiculo, Ticket


@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "prioridad")
    ordering = ("prioridad",)


class UsuarioForm(forms.ModelForm):
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
        instance = super().save(commit=False)
        password = self.cleaned_data.get("contrasena")
        if password:
            instance.set_password(password)
        if commit:
            instance.save()
        return instance


@admin.register(Usuario)
class UsuarioAdmin(admin.ModelAdmin):
    form = UsuarioForm
    list_display = ("nombre_completo", "correo", "id_cargo", "valido", "rechazado")
    list_filter = ("valido", "rechazado", "id_cargo")
    search_fields = ("nombre", "apellido", "correo")

    def nombre_completo(self, obj):
        return obj.nombre_completo
    nombre_completo.short_description = "Nombre"


@admin.register(Vehiculo)
class VehiculoAdmin(admin.ModelAdmin):
    list_display = ("marca", "modelo", "cant_pasajeros", "activo")
    list_filter = ("activo", "marca")
    search_fields = ("marca", "modelo")


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("id", "id_usuario", "id_vehiculo", "destino", "hora_inicio", "hora_fin", "estado")
    list_filter = ("estado", "id_vehiculo")
    search_fields = ("destino", "id_usuario__nombre", "id_usuario__apellido")
    readonly_fields = ("fecha", "observacion")
    ordering = ("-hora_inicio",)
