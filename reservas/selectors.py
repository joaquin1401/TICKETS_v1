"""
selectors.py - Funciones de lectura (queries) complejas y reutilizables.

Patrón: "Selectors" o "Queries"
────────────────────────────────
Las funciones aquí son READ-ONLY (no modifican BD).
Encapsulan queries complejas con optimizaciones (select_related, prefetch_related)
para evitar N+1 y duplicación de lógica en vistas.

Beneficios:
✓ Centraliza queries frecuentes
✓ Garantiza optimizaciones (select_related/prefetch_related)
✓ Fácil de testear
✓ Documentación clara de qué devuelve cada query

Diferencia con managers.py:
- managers.py: Métodos del QuerySet directamente en el modelo (ej: Usuario.objects.activos())
- selectors.py: Funciones que reciben instancias y retornan resultados formateados
"""

from datetime import date, datetime
from typing import List, Set, Optional
from django.db.models import QuerySet, Prefetch
from .models import Usuario, Ticket, Vehiculo, Cargo


# ─────────────────────────────────────────────────────────────────────────────
# Selectors de Usuario
# ─────────────────────────────────────────────────────────────────────────────

def get_usuario_por_correo_con_cargo(correo: str) -> Optional[Usuario]:
    """
    Obtiene un usuario por correo con cargo precargado (evita N+1).
    
    Parámetros:
        correo: Email del usuario a buscar
    
    Retorna:
        Usuario con cargo cargado, o None si no existe
    
    Optimización: select_related("id_cargo") evita query adicional
                  al acceder a usuario.id_cargo.prioridad
    
    Uso típico: En login (necesitamos correo + prioridad)
    """
    return (
        Usuario.objects
        .select_related("id_cargo")
        .filter(correo=correo)
        .first()
    )


def get_usuarios_pendientes_aprobacion() -> QuerySet:
    """
    Obtiene todos los usuarios pendientes de aprobación.
    
    Retorna:
        QuerySet de usuarios con cargo precargado
    
    Nota: Usa manager Usuario.objects.pendientes() pero aquí lo exponemos
          como selector por consistencia arquitectónica.
    """
    return Usuario.objects.pendientes()


def get_usuarios_aprobados_por_cargo(cargo: Cargo) -> QuerySet:
    """
    Obtiene todos los usuarios aprobados con un cargo específico.
    
    Parámetros:
        cargo: Instancia de Cargo a filtrar
    
    Retorna:
        QuerySet de usuarios aprobados del cargo
    """
    return (
        Usuario.objects
        .activos()
        .filter(id_cargo=cargo)
        .order_by("apellido", "nombre")
    )


def buscar_usuarios(
    busqueda: Optional[str] = None,
    cargo: Optional[Cargo] = None,
) -> QuerySet:
    """
    Búsqueda avanzada de usuarios aprobados con filtros opcionales.
    
    Parámetros:
        busqueda: Texto a buscar en nombre, apellido o correo (case-insensitive)
        cargo: Filtrar por cargo específico
    
    Retorna:
        QuerySet de usuarios que coinciden con criterios
    
    Ejemplo:
        usuarios = buscar_usuarios(busqueda="juan", cargo=cargo_secretario)
    """
    qs = Usuario.objects.activos()
    
    if busqueda:
        from django.db.models import Q
        qs = qs.filter(
            Q(nombre__icontains=busqueda)
            | Q(apellido__icontains=busqueda)
            | Q(correo__icontains=busqueda)
        )
    
    if cargo:
        qs = qs.filter(id_cargo=cargo)
    
    return qs


# ─────────────────────────────────────────────────────────────────────────────
# Selectors de Ticket
# ─────────────────────────────────────────────────────────────────────────────

def get_tickets_usuario(usuario: Usuario) -> QuerySet:
    """
    Obtiene todos los tickets de un usuario ordenados por fecha.
    
    Parámetros:
        usuario: Instancia de Usuario
    
    Retorna:
        QuerySet de tickets del usuario con relaciones precargadas
    
    Optimización: select_related evita 2 queries extras al acceder a
                  ticket.id_vehiculo y ticket.id_usuario.id_cargo
    """
    return (
        usuario.tickets
        .select_related("id_vehiculo", "id_usuario__id_cargo")
        .order_by("-hora_inicio")
    )


def get_tickets_aprobados_mes(
    vehiculo: Vehiculo,
    anio: int,
    mes: int,
) -> QuerySet:
    """
    Obtiene tickets aprobados de un vehículo en un mes específico.
    
    Parámetros:
        vehiculo: Instancia de Vehiculo
        anio: Año (ej: 2025)
        mes: Mes (1-12)
    
    Retorna:
        QuerySet de tickets aprobados del mes
    
    Uso típico: Vista de calendario para mostrar días con reservas
    """
    return (
        Ticket.objects
        .filter(
            id_vehiculo=vehiculo,
            estado=Ticket.ESTADO_APROBADO,
            hora_inicio__year=anio,
            hora_inicio__month=mes,
        )
        .select_related("id_usuario", "id_usuario__id_cargo")
        .order_by("hora_inicio")
    )


def get_tickets_aprobados_dia(
    vehiculo: Vehiculo,
    fecha: date,
) -> QuerySet:
    """
    Obtiene tickets aprobados de un vehículo en un día específico.
    
    Parámetros:
        vehiculo: Instancia de Vehiculo
        fecha: date del día a consultar
    
    Retorna:
        QuerySet ordenado por hora_inicio
    
    Uso típico: Timeline horario del día (ver qué horas están ocupadas)
    """
    return (
        Ticket.objects
        .filter(
            id_vehiculo=vehiculo,
            estado=Ticket.ESTADO_APROBADO,
            hora_inicio__date=fecha,
        )
        .select_related("id_usuario", "id_usuario__id_cargo")
        .order_by("hora_inicio")
    )


def get_dias_con_reservas(
    vehiculo: Vehiculo,
    anio: int,
    mes: int,
) -> Set[date]:
    """
    Obtiene conjunto de días que tienen al menos una reserva aprobada.
    
    Parámetros:
        vehiculo: Instancia de Vehiculo
        anio: Año
        mes: Mes
    
    Retorna:
        Set de objetos date con reservas
    
    Nota de diseño: Retorna Set (no QuerySet) porque el calendario necesita
                    una colección en memoria para marcar en template.
                    La query devuelve solo la fecha (evita cargar tickets completos).
    """
    tickets = (
        Ticket.objects
        .filter(
            id_vehiculo=vehiculo,
            estado=Ticket.ESTADO_APROBADO,
            hora_inicio__year=anio,
            hora_inicio__month=mes,
        )
        .values_list("hora_inicio", flat=True)
    )
    return {ticket_datetime.date() for ticket_datetime in tickets}


def get_tickets_activos_empresa() -> QuerySet:
    """
    Obtiene todos los tickets aprobados futuros (para monitor admin).
    
    Retorna:
        QuerySet de tickets aprobados ordenados por fecha
    
    Optimización: select_related precarga todas las relaciones necesarias
                  para evitar N+1 cuando se accede a usuario/vehículo en template
    """
    from datetime import datetime
    from django.utils import timezone
    
    return (
        Ticket.objects
        .filter(
            estado=Ticket.ESTADO_APROBADO,
            hora_inicio__gte=timezone.now(),
        )
        .select_related("id_usuario", "id_vehiculo", "id_usuario__id_cargo")
        .order_by("hora_inicio")
    )


def get_tickets_auditoria() -> QuerySet:
    """
    Obtiene todos los tickets históricos y cancelados (para auditoría admin).
    
    Retorna:
        QuerySet de tickets cancelados o pasados
    
    Nota de diseño: Esta query puede retornar muchos registros.
                    En producción, considerar agregar paginación en vista.
    """
    from django.utils import timezone
    from django.db.models import Q
    
    return (
        Ticket.objects
        .filter(
            Q(estado=Ticket.ESTADO_CANCELADO) | Q(hora_inicio__lt=timezone.now())
        )
        .select_related("id_usuario", "id_vehiculo", "id_usuario__id_cargo")
        .order_by("-hora_inicio")
    )


def get_conflictos_ticket(
    vehiculo: Vehiculo,
    hora_inicio: datetime,
    hora_fin: datetime,
    excluir_ticket_id: Optional[int] = None,
) -> QuerySet:
    """
    Obtiene tickets aprobados que solapan con un rango horario.
    
    Parámetros:
        vehiculo: Vehiculo a verificar
        hora_inicio: Inicio del rango (inclusive)
        hora_fin: Fin del rango (exclusive)
        excluir_ticket_id: ID de ticket a ignorar (útil para ediciones)
    
    Retorna:
        QuerySet de tickets en conflicto
    
    Lógica de solapamiento:
        Existe conflicto si: ticket.hora_inicio < hora_fin AND ticket.hora_fin > hora_inicio
    
    Ejemplo:
        conflictos = get_conflictos_ticket(vehiculo, inicio, fin)
        if conflictos.exists():
            # hay conflicto
    """
    qs = Ticket.objects.del_vehiculo_en_rango(
        vehiculo, hora_inicio, hora_fin
    )
    
    if excluir_ticket_id:
        qs = qs.exclude(pk=excluir_ticket_id)
    
    return qs


# ─────────────────────────────────────────────────────────────────────────────
# Selectors de Vehículo
# ─────────────────────────────────────────────────────────────────────────────

def get_vehiculos_disponibles() -> QuerySet:
    """
    Obtiene todos los vehículos activos (no dados de baja).
    
    Retorna:
        QuerySet de vehículos ordenados por marca/modelo
    
    Uso típico: Dropdown en formulario de reserva
    """
    return Vehiculo.objects.disponibles().order_by("marca", "modelo")


def get_vehiculo_detalle(vehiculo_id: int) -> Optional[Vehiculo]:
    """
    Obtiene un vehículo específico por ID.
    
    Parámetros:
        vehiculo_id: PK del vehículo
    
    Retorna:
        Vehiculo o None si no existe
    """
    return Vehiculo.objects.filter(pk=vehiculo_id, activo=True).first()
