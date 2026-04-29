from django.contrib import admin
from .models import Cargo, Usuario, Vehiculo, Ticket


@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "prioridad")
    ordering = ("prioridad",)


@admin.register(Usuario)
class UsuarioAdmin(admin.ModelAdmin):
    list_display = ("nombre_completo", "correo", "id_cargo", "valido", "rechazado")
    list_filter = ("valido", "rechazado", "id_cargo")
    search_fields = ("nombre", "apellido", "correo")
    readonly_fields = ("contrasena",)

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
