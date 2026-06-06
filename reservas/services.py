"""
Servicios de lógica de negocio para el sistema de reservas (Épica 4).

Centraliza la detección de colisiones de horarios, resolución de conflictos
por jerarquía de cargos y helpers de disponibilidad. Mantiene las vistas limpias
permitiendo testing unitario independiente.

Conceptos clave:
    - Solapamiento: Dos tickets comparten tiempo si:
      ticket_existente.hora_inicio < hora_fin AND ticket_existente.hora_fin > hora_inicio
    - Prioridad: Número menor indica mayor jerarquía (Decano < Secretario < Usuario).
    - Sobrescritura: Usuario de mayor jerarquía puede cancelar reservas de menor jerarquía.
"""

from django.db import transaction
from django.utils import timezone
from .models import Ticket


# ══════════════════════════════════════════════
# HU 4.1 — Detección de Colisiones
# ══════════════════════════════════════════════

def obtener_tickets_en_conflicto(vehiculo, hora_inicio, hora_fin, excluir_ticket_id=None):
    """
    Obtiene todos los tickets APROBADOS que se solapan con un rango de horario.

    La detección de solapamiento es crucial para HU 4.2 (crear con conflicto)
    y HU 4.3 (sobrescribir por jerarquía). Un solapamiento ocurre cuando:

        ticket_existente.hora_inicio < hora_fin
        AND ticket_existente.hora_fin   > hora_inicio

    Args:
        vehiculo (Vehiculo): Vehículo para el cual buscar conflictos.
        hora_inicio (datetime): Inicio de la franja solicitada.
        hora_fin (datetime): Fin de la franja solicitada.
        excluir_ticket_id (int, optional): ID de ticket a ignorar.
            Utilizado en ediciones para no compararse contra sí mismo.

    Returns:
        QuerySet: Tickets en conflicto (sin evaluarse, puede estar vacío).

    Notes:
        - Solo considera tickets con estado APROBADO.
        - Los tickets PENDIENTE o CANCELADO no bloquean nuevas reservas.
        - Se utiliza Q() para lógica AND con comparaciones de rango.
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
    """
    Verifica rápidamente si existe al menos un conflicto.

    Args:
        vehiculo (Vehiculo): Vehículo a verificar.
        hora_inicio (datetime): Inicio de la franja solicitada.
        hora_fin (datetime): Fin de la franja solicitada.
        excluir_ticket_id (int, optional): ID de ticket a ignorar.

    Returns:
        bool: True si existe conflicto, False en caso contrario.

    Notes:
        Utiliza .exists() para optimización en BD (no evalúa todo el queryset).
    """
    return obtener_tickets_en_conflicto(
        vehiculo, hora_inicio, hora_fin, excluir_ticket_id
    ).exists()


# ══════════════════════════════════════════════
# HU 4.2 + 4.3 — Creación con Reglas de Prioridad
# ══════════════════════════════════════════════

class ResultadoCreacion:
    """
    Objeto de respuesta para la creación de un ticket (HU 4.2, 4.3).

    Encapsula el resultado de crear_ticket_con_reglas(), permitiendo
    vistas y tests distinguir entre éxito, sobrescritura y bloqueo.

    Attributes:
        estado (str): Uno de OK, BLOQUEADO o SOBRESCRITO.
        ticket (Ticket, optional): Ticket creado (si estado == OK o SOBRESCRITO).
        tickets_cancelados (list): Tickets cancelados por sobrescritura.
        mensaje (str): Texto descriptivo para mostrar al usuario.

    Properties:
        exito (bool): True si estado es OK o SOBRESCRITO.
            Falso si BLOQUEADO (la solicitud no pudo completarse).
    """

    OK = "ok"
    BLOQUEADO = "bloqueado"          # El solicitante tiene MENOR prioridad
    SOBRESCRITO = "sobrescrito"      # El solicitante tiene MAYOR prioridad → canceló otros

    def __init__(self, estado, ticket=None, tickets_cancelados=None, mensaje=""):
        """
        Inicializa el resultado de creación.

        Args:
            estado (str): Uno de OK, BLOQUEADO, SOBRESCRITO.
            ticket (Ticket, optional): Ticket recién creado.
            tickets_cancelados (list, optional): Tickets cancelados por sobrescritura.
            mensaje (str): Mensaje para usuario final.
        """
        self.estado = estado
        self.ticket = ticket
        self.tickets_cancelados = tickets_cancelados or []
        self.mensaje = mensaje

    @property
    def exito(self):
        """
        Indica si la creación fue exitosa.

        Returns:
            bool: True si estado es OK o SOBRESCRITO (la reserva se completó).
                False si BLOQUEADO (fue rechazada).
        """
        return self.estado in (self.OK, self.SOBRESCRITO)


@transaction.atomic
def crear_ticket_con_reglas(usuario, vehiculo, hora_inicio, hora_fin, **kwargs):
    """
    Crea un nuevo ticket aplicando reglas de jerarquía de cargos (HU 4.2, 4.3).

    Flujo de lógica:

    1. Busca tickets APROBADOS en conflicto con la franja [hora_inicio, hora_fin).
    2. Si no hay conflictos:
        → Crea el ticket como APROBADO.
        → Retorna ResultadoCreacion(OK, ...).

    3. Si hay conflictos, compara la prioridad del solicitante:
        a. Si el solicitante tiene MAYOR jerarquía (prioridad < todos los conflictos):
            → Cancela los tickets en conflicto con observación auto-generada.
            → Crea el nuevo ticket como APROBADO.
            → Retorna ResultadoCreacion(SOBRESCRITO, ...).

        b. Si algún conflicto pertenece a usuario con IGUAL O MAYOR jerarquía:
            → Rechaza la solicitud SIN crear ticket.
            → Retorna ResultadoCreacion(BLOQUEADO, ...).

    Args:
        usuario (Usuario): Solicitante de la reserva (con id_cargo.prioridad).
        vehiculo (Vehiculo): Vehículo a reservar.
        hora_inicio (datetime): Inicio del viaje.
        hora_fin (datetime): Fin del viaje.
        **kwargs: Datos adicionales: destino, cant_pasajeros, descripcion.

    Returns:
        ResultadoCreacion: Resultado de la operación con ticket, tickets cancelados
            y mensaje descriptivo para mostrar al usuario.

    Raises:
        (Transacción): Si hay error en BD durante la creación o cancelación,
            se revierte automáticamente (@transaction.atomic).

    Notes:
        - Los tickets CANCELADO no intervienen en conflictos.
        - La jerarquía se compara por usuario.prioridad (número de cargo).
        - Menor número = mayor jerarquía (ej: Decano=0, Secretario=1, Usuario=2).
        - Los timestamps de observación se generan con timezone.now().
        - Transacción ACID para garantizar consistencia en sobrescrituras.
    """
    prioridad_solicitante = usuario.prioridad  # número: menor = más alto en jerarquía
    
    # ── Regla: Vehículo en mantenimiento ─────────────────────────────────────────────
    if not vehiculo.activo:
        return ResultadoCreacion(
            estado=ResultadoCreacion.BLOQUEADO,
            mensaje="El vehículo seleccionado se encuentra en mantenimiento o inactivo."
        )

    # ── Regla: Vehículo exclusivo del Decanato ───────────────────────────────────────
    from .models import Cargo
    if vehiculo.exclusivo_decanato and usuario.id_cargo.nombre != Cargo.DECANO:
        return ResultadoCreacion(
            estado=ResultadoCreacion.BLOQUEADO,
            mensaje="Este vehículo es de uso exclusivo del Decanato."
        )

    # ── Reglas Temporales: Max 2 meses, Min 3 días ──────────────────────────────────
    from datetime import timedelta
    ahora = timezone.now()
    if hora_inicio > ahora + timedelta(days=60):
        return ResultadoCreacion(
            estado=ResultadoCreacion.BLOQUEADO,
            mensaje="No se pueden realizar reservas con más de 2 meses (60 días) de antelación."
        )
    if hora_inicio < ahora + timedelta(days=3):
        return ResultadoCreacion(
            estado=ResultadoCreacion.BLOQUEADO,
            mensaje="Debe reservar con al menos 3 días de anticipación."
        )

    tickets_conflicto = list(
        obtener_tickets_en_conflicto(vehiculo, hora_inicio, hora_fin)
    )

    # ── Caso 1: Sin conflictos ──────────────────────────────────────────────────────
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

    # ── Caso 2: Con conflictos - evaluar jerarquía ───────────────────────────────────
    for t_existente in tickets_conflicto:
        prioridad_existente = t_existente.id_usuario.prioridad
        # Si algún ticket existente pertenece a alguien de IGUAL o MAYOR jerarquía
        # (número <= al solicitante) → no podemos sobrescribir
        if prioridad_existente <= prioridad_solicitante:
            propietario = t_existente.id_usuario.nombre_completo
            return ResultadoCreacion(
                estado=ResultadoCreacion.BLOQUEADO,
                mensaje=(
                    f"Lamentamos comunicarte que el vehículo ya está reservado por {propietario} "
                    f"({t_existente.id_usuario.id_cargo.nombre})."
                ),
            )

    # ── Caso 3: El solicitante tiene MAYOR jerarquía que todos los conflictos ───────
    # Sobrescribir y notificar
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


@transaction.atomic
def cancelar_ticket_usuario(ticket, usuario):
    """
    Permite a un usuario cancelar su propio ticket si falta tiempo suficiente.
    
    Regla: Cancelación permitida hasta 5 días antes del inicio.
    
    Args:
        ticket (Ticket): El ticket a cancelar.
        usuario (Usuario): El usuario que intenta cancelar.
        
    Returns:
        tuple (bool, str): (Éxito, Mensaje descriptivo o de error)
    """
    from datetime import timedelta
    
    if ticket.id_usuario != usuario:
        return False, "No tienes permiso para cancelar este ticket."
        
    if ticket.estado != Ticket.ESTADO_APROBADO:
        return False, "El ticket ya no está activo."
        
    ahora = timezone.now()
    if ticket.hora_inicio < ahora + timedelta(days=5):
        return False, "No se puede cancelar la reserva con menos de 5 días de anticipación."
        
    ticket.estado = Ticket.ESTADO_CANCELADO
    ticket.observacion = (
        f"Cancelado por el usuario el {ahora.strftime('%d/%m/%Y %H:%M')}."
    )
    ticket.save(update_fields=["estado", "observacion"])
    
    return True, "Reserva cancelada exitosamente."


# ══════════════════════════════════════════════
# HU 3.x — Helpers de Disponibilidad (Épica 3)
# ══════════════════════════════════════════════

def get_tickets_del_mes(vehiculo, anio, mes):
    """
    Obtiene todos los tickets aprobados de un vehículo en un mes específico.

    Utilizado en vista de calendario (HU 3.1, 3.2) para marcar días con reservas.

    Args:
        vehiculo (Vehiculo): Vehículo a consultar.
        anio (int): Año (YYYY).
        mes (int): Mes (1-12).

    Returns:
        QuerySet: Tickets APROBADOS del vehículo en el mes, con usuario asociado
            pre-cargado (select_related). Ordenados por hora_inicio.

    Notes:
        - Solo considera tickets APROBADOS.
        - Utiliza filtrado de fechas en la BD para eficiencia.
    """
    return Ticket.objects.filter(
        id_vehiculo=vehiculo,
        estado=Ticket.ESTADO_APROBADO,
        hora_inicio__year=anio,
        hora_inicio__month=mes,
    ).select_related("id_usuario")


def get_tickets_del_dia(vehiculo, fecha):
    """
    Obtiene todos los tickets aprobados de un vehículo en una fecha específica.

    Utilizado en vista de línea de tiempo (HU 3.3) para mostrar ocupación horaria.

    Args:
        vehiculo (Vehiculo): Vehículo a consultar.
        fecha (date): Fecha específica (YYYY-MM-DD).

    Returns:
        QuerySet: Tickets APROBADOS ordenados por hora_inicio ascendente,
            con usuario asociado pre-cargado.

    Notes:
        - Filtra por la fecha exacta del campo hora_inicio__date.
        - Solo considera tickets APROBADOS.
        - Orden ascendente para mostrar cronológicamente en templates.
    """
    return Ticket.objects.filter(
        id_vehiculo=vehiculo,
        estado=Ticket.ESTADO_APROBADO,
        hora_inicio__date=fecha,
    ).order_by("hora_inicio").select_related("id_usuario")
