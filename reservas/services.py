"""
services.py — Motor de reglas de negocio (Épica 4)

Centraliza toda la lógica de colisiones y prioridad de cargos
para mantener las vistas limpias y facilitar el testing.
"""

from django.db import transaction
from django.utils import timezone
from .models import Ticket


# ──────────────────────────────────────────────
# HU 4.1  Detección de colisiones
# ──────────────────────────────────────────────

def obtener_tickets_en_conflicto(vehiculo, hora_inicio, hora_fin, excluir_ticket_id=None):
    """
    Devuelve todos los tickets APROBADOS del vehículo que se solapan
    con la franja [hora_inicio, hora_fin).

    Un solapamiento ocurre cuando:
        ticket_existente.hora_inicio < hora_fin
        AND ticket_existente.hora_fin   > hora_inicio
    """
    qs = Ticket.objects.filter(
        id_vehiculo=vehiculo,
        estado=Ticket.ESTADO_APROBADO,
        hora_inicio__lt=hora_fin,
        hora_fin__gt=hora_inicio,
    )
    if excluir_ticket_id:
        qs = qs.exclude(pk=excluir_ticket_id)
    return qs


def hay_conflicto(vehiculo, hora_inicio, hora_fin, excluir_ticket_id=None):
    """Retorna True si existe al menos un ticket en conflicto."""
    return obtener_tickets_en_conflicto(
        vehiculo, hora_inicio, hora_fin, excluir_ticket_id
    ).exists()


# ──────────────────────────────────────────────
# HU 4.2 + 4.3  Creación de ticket con reglas de prioridad
# ──────────────────────────────────────────────

class ResultadoCreacion:
    """Objeto de resultado para la creación de un ticket."""

    OK = "ok"
    BLOQUEADO = "bloqueado"          # El solicitante tiene MENOR prioridad
    SOBRESCRITO = "sobrescrito"      # El solicitante tiene MAYOR prioridad → canceló otros

    def __init__(self, estado, ticket=None, tickets_cancelados=None, mensaje=""):
        self.estado = estado
        self.ticket = ticket
        self.tickets_cancelados = tickets_cancelados or []
        self.mensaje = mensaje

    @property
    def exito(self):
        return self.estado in (self.OK, self.SOBRESCRITO)


@transaction.atomic
def crear_ticket_con_reglas(usuario, vehiculo, hora_inicio, hora_fin, **kwargs):
    """
    Crea un nuevo ticket aplicando las reglas de jerarquía de cargos.

    Flujo:
    1. Busca tickets aprobados en conflicto.
    2. Si no hay conflicto → crea el ticket como APROBADO directamente.
    3. Si hay conflicto:
       a. Compara la prioridad del solicitante con cada ticket en conflicto.
       b. Si el solicitante tiene MAYOR prioridad (número menor) que TODOS
          los conflictos → cancela esos tickets y crea el nuevo como APROBADO.
       c. Si algún conflicto pertenece a alguien con IGUAL O MAYOR prioridad
          → rechaza la solicitud y retorna BLOQUEADO.

    Parámetros extra (**kwargs): destino, cant_pasajeros, descripcion.
    """
    prioridad_solicitante = usuario.prioridad  # número: menor = más alto en jerarquía
    tickets_conflicto = list(
        obtener_tickets_en_conflicto(vehiculo, hora_inicio, hora_fin)
    )

    # ── Sin conflictos ──────────────────────────────────────────────────────
    if not tickets_conflicto:
        ticket = Ticket.objects.create(
            id_usuario=usuario,
            id_vehiculo=vehiculo,
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
            estado=Ticket.ESTADO_APROBADO,
            **kwargs,
        )
        return ResultadoCreacion(
            estado=ResultadoCreacion.OK,
            ticket=ticket,
            mensaje="Reserva creada exitosamente.",
        )

    # ── Con conflictos: evaluar jerarquía ───────────────────────────────────
    for t_existente in tickets_conflicto:
        prioridad_existente = t_existente.id_usuario.prioridad
        # Si algún ticket existente pertenece a alguien de IGUAL o MAYOR jerarquía
        # (número <= al solicitante) → no podemos sobrescribir
        if prioridad_existente <= prioridad_solicitante:
            propietario = t_existente.id_usuario.nombre_completo
            return ResultadoCreacion(
                estado=ResultadoCreacion.BLOQUEADO,
                mensaje=(
                    f"El vehículo ya está reservado por {propietario} "
                    f"({t_existente.id_usuario.id_cargo.nombre}), "
                    f"quien tiene igual o mayor jerarquía que usted."
                ),
            )

    # El solicitante tiene MAYOR jerarquía que todos los conflictos → sobrescribir
    tickets_cancelados = []
    for t_existente in tickets_conflicto:
        propietario = t_existente.id_usuario.nombre_completo
        cargo_solicitante = usuario.id_cargo.nombre
        t_existente.estado = Ticket.ESTADO_CANCELADO
        t_existente.observacion = (
            f"Reserva cancelada automáticamente el {timezone.now().strftime('%d/%m/%Y %H:%M')} "
            f"porque {usuario.nombre_completo} ({cargo_solicitante}) "
            f"con mayor jerarquía tomó el vehículo para la misma franja horaria."
        )
        t_existente.save(update_fields=["estado", "observacion"])
        tickets_cancelados.append(t_existente)

    ticket = Ticket.objects.create(
        id_usuario=usuario,
        id_vehiculo=vehiculo,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        estado=Ticket.ESTADO_APROBADO,
        **kwargs,
    )

    nombres_cancelados = ", ".join(
        t.id_usuario.nombre_completo for t in tickets_cancelados
    )
    return ResultadoCreacion(
        estado=ResultadoCreacion.SOBRESCRITO,
        ticket=ticket,
        tickets_cancelados=tickets_cancelados,
        mensaje=(
            f"Reserva creada. Se cancelaron las reservas de: {nombres_cancelados} "
            f"por jerarquía de cargo."
        ),
    )


# ──────────────────────────────────────────────
# Helpers de disponibilidad (Épica 3)
# ──────────────────────────────────────────────

def get_tickets_del_mes(vehiculo, anio, mes):
    """Devuelve los tickets aprobados de un vehículo en un mes dado."""
    return Ticket.objects.filter(
        id_vehiculo=vehiculo,
        estado=Ticket.ESTADO_APROBADO,
        hora_inicio__year=anio,
        hora_inicio__month=mes,
    ).select_related("id_usuario")


def get_tickets_del_dia(vehiculo, fecha):
    """Devuelve los tickets aprobados de un vehículo en una fecha específica."""
    return Ticket.objects.filter(
        id_vehiculo=vehiculo,
        estado=Ticket.ESTADO_APROBADO,
        hora_inicio__date=fecha,
    ).order_by("hora_inicio").select_related("id_usuario")
