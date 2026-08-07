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

import logging
from datetime import timedelta

import requests
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ..models import Ticket, to_local_date

logger = logging.getLogger(__name__)


def evaluar_ventana_anticipacion(usuario, hora_inicio, ahora=None):
    """
    Evalúa si `hora_inicio` respeta la ventana de anticipación configurada
    (ConfiguracionGlobal.dias_anticipacion_reservas / dias_maximo_anticipacion_reservas).

    Única autoridad para esta regla: antes vivía por separado en TicketForm.clean()
    y en crear_ticket_con_reglas(), escrita dos veces con arithmetic independiente.
    Ya habían divergido sin que nadie lo notara: el service se saltaba también la
    anticipación MÁXIMA cuando había un permiso de emergencia vigente (estaba bajo
    el mismo `if` que la mínima), mientras que el form solo eximía la mínima. El
    permiso es para poder reservar pronto tras una cancelación forzada — no tiene
    relación con cuánto a futuro se puede reservar, así que ese salto de la máxima
    era un bug, no una decisión de diseño.

    No tiene efectos secundarios: NO marca ningún PermisoReservaExtraordinaria como
    usado, aunque sí lo devuelve si aplica. Es responsabilidad de quien efectivamente
    cree el ticket (crear_ticket_con_reglas) volver a buscarlo y marcarlo `usado=True`
    después de un éxito real — evaluar la ventana no debe consumir el permiso.

    Args:
        usuario (Usuario | None): Solicitante. None se trata como "no-admin, sin
            permiso de emergencia posible" — usado por TicketForm en el único call
            site donde todavía no se conoce el usuario (precarga por GET).
        hora_inicio (datetime): Inicio propuesto del viaje.
        ahora (datetime, optional): Instante de referencia. Por defecto timezone.now().

    Returns:
        dict con:
            bloqueado (bool): True si la reserva debe rechazarse por esta regla.
            campo (str | None): "hora_inicio", para adjuntar el error a ese campo.
            mensaje (str | None): Mensaje para mostrar al usuario.
            permiso_emergencia (PermisoReservaExtraordinaria | None): el permiso
                vigente que eximió la anticipación mínima, si aplica.

    Notes:
        No aplica a administradores (prioridad 0): no tienen límite de anticipación.
    """
    from ..models import ConfiguracionGlobal, PermisoReservaExtraordinaria

    if ahora is None:
        ahora = timezone.now()

    resultado = {
        "bloqueado": False,
        "campo": None,
        "mensaje": None,
        "permiso_emergencia": None,
    }

    es_admin = usuario is not None and usuario.id_cargo.prioridad == 0
    if es_admin:
        return resultado

    config = ConfiguracionGlobal.get_solo()
    dias_anticipacion = config.dias_anticipacion_reservas
    dias_maximo = config.dias_maximo_anticipacion_reservas

    # Anticipación máxima: se aplica siempre a no-admins, tengan o no permiso
    # de emergencia vigente (el permiso solo exime la mínima, ver docstring).
    if hora_inicio > ahora + timedelta(days=dias_maximo):
        resultado.update(
            bloqueado=True,
            campo="hora_inicio",
            mensaje=f"No se pueden realizar reservas con más de {dias_maximo} días de antelación.",
        )
        return resultado

    # Permiso de emergencia: exime la anticipación mínima si hora_inicio cae
    # dentro de los próximos dias_anticipacion días desde hoy. Sin usuario no
    # hay a quién buscarle el permiso.
    permiso = None
    if usuario is not None:
        ahora_date = timezone.localdate()
        permiso = PermisoReservaExtraordinaria.objects.filter(
            usuario=usuario,
            usado=False,
            valido_hasta__gte=ahora_date,
        ).first()
    tiene_permiso_activo = False
    if permiso:
        limite_permitido = ahora_date + timedelta(days=dias_anticipacion)
        if to_local_date(hora_inicio) <= limite_permitido:
            tiene_permiso_activo = True
            resultado["permiso_emergencia"] = permiso

    if not tiene_permiso_activo and hora_inicio < ahora + timedelta(
        days=dias_anticipacion
    ):
        resultado.update(
            bloqueado=True,
            campo="hora_inicio",
            mensaje=f"Debe reservar con al menos {dias_anticipacion} días de anticipación.",
        )

    return resultado


def calcular_distancia_y_tiempo_osrm(destino):
    """
    Calcula la distancia en kilómetros desde UTN FRRE hasta el destino usando OSRM.
    Devuelve (0.0, 0.0) si ocurre algún error o si el destino no es geocodificable.
    """
    if not destino:
        return 0.0, 0.0

    # Coordenadas de UTN FRRE
    lat_origen = -27.4511
    lon_origen = -58.9786

    try:
        # 1. Geocodificar el destino con Nominatim
        headers = {"User-Agent": "UTN_FRRE_Reserva_Vehiculos/1.0"}
        resp_geocode = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": destino, "format": "json", "limit": 1},
            headers=headers,
            timeout=3,
        )
        if resp_geocode.status_code != 200 or not resp_geocode.json():
            return 0.0, 0.0

        datos_destino = resp_geocode.json()[0]
        lat_destino = float(datos_destino["lat"])
        lon_destino = float(datos_destino["lon"])

        # 2. Calcular la ruta con OSRM
        url_osrm = f"http://router.project-osrm.org/route/v1/driving/{lon_origen},{lat_origen};{lon_destino},{lat_destino}?overview=false"
        resp_osrm = requests.get(url_osrm, timeout=3)

        if resp_osrm.status_code != 200:
            return 0.0, 0.0

        data_osrm = resp_osrm.json()
        if data_osrm.get("code") != "Ok" or not data_osrm.get("routes"):
            return 0.0, 0.0

        distancia_metros = data_osrm["routes"][0]["distance"]
        duracion_segundos = data_osrm["routes"][0]["duration"]

        return round((distancia_metros / 1000.0) * 2, 2), round(
            duracion_segundos * 2, 2
        )

    except Exception as e:
        logger.warning(f"Error calculando distancia a {destino}: {e}")
        return 0.0, 0.0


# ══════════════════════════════════════════════
# HU 4.1 — Detección de Colisiones
# ══════════════════════════════════════════════


def _get_horas_margen():
    """
    Obtiene el margen configurable de horas entre reservas (mismo vehículo),
    combinando horas y minutos configurados.

    Returns:
        float: Cantidad de horas de margen (default=1 si no hay configuración).
    """
    try:
        from ..models import ConfiguracionGlobal

        config = ConfiguracionGlobal.get_solo()
        horas = max(0, config.horas_margen_entre_reservas or 0)
        minutos = max(0, config.minutos_margen_entre_reservas or 0)
        return horas + minutos / 60.0
    except Exception:
        return 1.0


def obtener_tickets_en_conflicto(
    vehiculo, hora_inicio, hora_fin, excluir_ticket_id=None, horas_margen=None
):
    """
    Obtiene todos los tickets APROBADOS que se solapan con un rango de horario.

    La detección incluye un margen configurable de horas entre reservas (mismo vehículo).
    Un solapamiento con margen ocurre cuando:

        ticket_existente.hora_inicio < hora_fin + margen
        AND ticket_existente.hora_fin + margen > hora_inicio

    Equivale a: las franjas [hora_inicio, hora_fin) y [hora_inicio_existente, hora_fin_existente)
    están separadas por menos de `horas_margen` horas en CUALQUIER Extremo.

    Args:
        vehiculo (Vehiculo): Vehículo para el cual buscar conflictos.
        hora_inicio (datetime): Inicio de la franja solicitada.
        hora_fin (datetime): Fin de la franja solicitada.
        excluir_ticket_id (int, optional): ID de ticket a ignorar.
            Utilizado en ediciones para no compararse contra sí mismo.
        horas_margen (int, optional): Horas de margen. Si es None, se lee de ConfiguracionGlobal.

    Returns:
        QuerySet: Tickets en conflicto (sin evaluarse, puede estar vacío).

    Notes:
        - Solo considera tickets con estado APROBADO.
        - Los tickets PENDIENTE o CANCELADO no bloquean nuevas reservas.
        - El margen se aplica simétricamente: después del fin y antes del inicio.
    """
    if horas_margen is None:
        horas_margen = _get_horas_margen()
    margen = timedelta(hours=horas_margen)

    qs = Ticket.objects.filter(
        id_vehiculo=vehiculo,
        estado=Ticket.ESTADO_APROBADO,
        hora_inicio__lt=hora_fin + margen,
        hora_fin__gt=hora_inicio - margen,
    )
    if excluir_ticket_id:
        qs = qs.exclude(pk=excluir_ticket_id)
    return qs


def hay_conflicto_por_margen(
    vehiculo, hora_inicio, hora_fin, excluir_ticket_id=None, horas_margen=None
):
    """
    Indica si el conflicto detectado es SOLO por margen, sin solapamiento real.

    Esto se usa para mostrar un mensaje distinto al usuario: en vez de decir
    'ya está reservado por X', informa que debe respetar el margen mínimo.
    """
    conflictos = list(
        obtener_tickets_en_conflicto(
            vehiculo, hora_inicio, hora_fin, excluir_ticket_id, horas_margen
        )
    )
    if not conflictos:
        return False

    # Solapamiento real, SIN margen
    solapamientos_reales = Ticket.objects.filter(
        id_vehiculo=vehiculo,
        estado=Ticket.ESTADO_APROBADO,
        hora_inicio__lt=hora_fin,
        hora_fin__gt=hora_inicio,
    )
    if excluir_ticket_id:
        solapamientos_reales = solapamientos_reales.exclude(pk=excluir_ticket_id)

    if solapamientos_reales.exists():
        return False

    return True


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
    BLOQUEADO = "bloqueado"  # El solicitante tiene MENOR prioridad
    SOBRESCRITO = "sobrescrito"  # El solicitante tiene MAYOR prioridad → canceló otros
    REQUIERE_CONFIRMACION = "requiere_confirmacion"  # El solicitante tiene MAYOR prioridad pero debe confirmar

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
def crear_ticket_con_reglas(
    usuario, vehiculo, hora_inicio, hora_fin, confirmado=False, **kwargs
):
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
    from ..models import ConfiguracionGlobal, Vehiculo

    # ── Lock pesimista sobre el vehículo ────────────────────────────────────────────
    # Serializa todas las reservas concurrentes del MISMO vehículo. Sin esto, dos
    # requests simultáneos pueden leer ambos "sin conflicto" y crear dos tickets
    # aprobados solapados: @transaction.atomic da rollback, no exclusión mutua.
    # Se re-lee la fila para no operar sobre una instancia obsoleta del caller.
    vehiculo = Vehiculo.objects.select_for_update().get(pk=vehiculo.pk)

    config_global = ConfiguracionGlobal.get_solo()
    dias_cancelacion = config_global.dias_anticipacion_cancelacion

    prioridad_solicitante = usuario.prioridad  # número: menor = más alto en jerarquía

    # ── Regla: Vehículo en mantenimiento permanente ─────────────────────────────────
    if not vehiculo.activo:
        return ResultadoCreacion(
            estado=ResultadoCreacion.BLOQUEADO,
            mensaje="El vehículo seleccionado se encuentra en mantenimiento o inactivo.",
        )

    # ── Regla: Vehículo en baja temporal (inactivo_hasta) ───────────────────────────
    from datetime import timedelta as _td

    _fecha_inicio_date = to_local_date(hora_inicio)
    _hora_fin_tmp = hora_fin or (hora_inicio + _td(hours=2))
    _fecha_fin_date = to_local_date(_hora_fin_tmp)
    if vehiculo.esta_inactivo_en_rango(_fecha_inicio_date, _fecha_fin_date):
        return ResultadoCreacion(
            estado=ResultadoCreacion.BLOQUEADO,
            mensaje=(
                f"El vehículo seleccionado está temporalmente inactivo hasta el "
                f"{vehiculo.inactivo_hasta.strftime('%d/%m/%Y')}. "
                "Por favor, seleccioná otro vehículo o una fecha fuera de ese período."
            ),
        )

    # ── Regla: Días feriados ─────────────────────────────────────────────────────────
    # Vivía solo en TicketForm.clean(), así que cualquier caller que no pasara por ese
    # form (creación por admin, reasignación automática, poblar_bd, uso directo del
    # servicio) se lo saltaba entero. Se agrega acá para que sea la única autoridad;
    # TicketForm.clean() sigue teniendo su propio chequeo, que corre antes y da un
    # error específico por campo (mejor UX) — este es el que realmente bloquea.
    from ..models import Feriado

    if Feriado.objects.filter(fecha__in=[_fecha_inicio_date, _fecha_fin_date]).exists():
        return ResultadoCreacion(
            estado=ResultadoCreacion.BLOQUEADO,
            mensaje="No se pueden realizar reservas que inicien o finalicen en días feriados.",
        )

    # ── Regla: Vehículo exclusivo del Decanato ───────────────────────────────────────
    from ..models import Cargo

    if vehiculo.exclusivo_decanato and usuario.id_cargo.nombre != Cargo.DECANO:
        return ResultadoCreacion(
            estado=ResultadoCreacion.BLOQUEADO,
            mensaje="Este vehículo es de uso exclusivo del Decanato.",
        )

    # ── Regla: Capacidad de pasajeros ────────────────────────────────────────────────
    cant_pasajeros = kwargs.get("cant_pasajeros")
    if cant_pasajeros is not None and cant_pasajeros > vehiculo.cant_pasajeros:
        return ResultadoCreacion(
            estado=ResultadoCreacion.BLOQUEADO,
            mensaje=f"La cantidad de pasajeros solicitada ({cant_pasajeros}) excede la capacidad del vehículo ({vehiculo.cant_pasajeros}).",
        )

    # ── Regla: Chofer obligatorio y disponibilidad ──────────────────────────────────
    requiere_chofer = kwargs.get("requiere_chofer", False)
    if vehiculo.requiere_chofer:
        requiere_chofer = True
    kwargs["requiere_chofer"] = requiere_chofer

    if requiere_chofer:
        from ..models import Cargo, Usuario

        total_choferes = Usuario.objects.filter(
            id_cargo__nombre=Cargo.CHOFER, valido=True
        ).count()
        es_admin = usuario.id_cargo.prioridad == 0
        horas_margen = 0 if es_admin else _get_horas_margen()
        margen = timedelta(hours=horas_margen)

        tickets_chofer_conflicto = Ticket.objects.filter(
            estado__in=[Ticket.ESTADO_APROBADO, Ticket.ESTADO_EN_CURSO],
            requiere_chofer=True,
            hora_inicio__lt=hora_fin + margen,
            hora_fin__gt=hora_inicio - margen,
        )
        if tickets_chofer_conflicto.count() >= total_choferes:
            if vehiculo.requiere_chofer:
                return ResultadoCreacion(
                    estado=ResultadoCreacion.BLOQUEADO,
                    mensaje="El vehículo seleccionado requiere obligatoriamente la asignación de un chofer autorizado para su uso y no hay choferes disponibles para la fecha y el horario seleccionados. Intenta con otro rango de tiempo.",
                )
            else:
                return ResultadoCreacion(
                    estado=ResultadoCreacion.BLOQUEADO,
                    mensaje="No hay choferes disponibles para la fecha y el horario seleccionados. Intenta con otro rango de tiempo.",
                )

    # ── Reglas Temporales: anticipación mínima/máxima ────────────────────────────────
    # evaluar_ventana_anticipacion() es la única autoridad para esta regla (antes
    # estaba reimplementada acá y en TicketForm.clean(), y habían divergido -
    # ver docstring de la función para el detalle del bug que eso causaba).
    ahora = timezone.now()
    es_admin = usuario.id_cargo.prioridad == 0

    ventana = evaluar_ventana_anticipacion(usuario, hora_inicio, ahora=ahora)
    if ventana["bloqueado"]:
        return ResultadoCreacion(
            estado=ResultadoCreacion.BLOQUEADO, mensaje=ventana["mensaje"]
        )
    # Permiso de emergencia vigente que eximió la anticipación mínima (o None). Si la
    # creación del ticket termina en éxito, se marca usado=True más abajo - evaluar
    # la ventana no lo consume por sí sola.
    permiso_emergencia = ventana["permiso_emergencia"]

    tickets_conflicto = list(
        obtener_tickets_en_conflicto(
            vehiculo, hora_inicio, hora_fin, horas_margen=0 if es_admin else None
        )
    )

    # ── Si hay conflicto, diferenciar "solo margen" vs "solapamiento real" ───────
    if tickets_conflicto and not es_admin:
        solo_margen = hay_conflicto_por_margen(
            vehiculo, hora_inicio, hora_fin, horas_margen=0 if es_admin else None
        )
        if solo_margen:
            from ..models import ConfiguracionGlobal

            config = ConfiguracionGlobal.get_solo()
            margen_txt = f"{config.horas_margen_entre_reservas}h"
            if config.minutos_margen_entre_reservas:
                margen_txt += f" {config.minutos_margen_entre_reservas}min"
            return ResultadoCreacion(
                estado=ResultadoCreacion.BLOQUEADO,
                mensaje=(
                    f"Debés esperar al menos {margen_txt} desde la finalización de la reserva existente "
                    "para solicitar un nuevo turno para el mismo vehículo."
                ),
            )

    # ── Calcular kilometraje automáticamente ──────────────────────────────────────────
    destino = kwargs.get("destino", "")
    distancia_est, duracion_est = calcular_distancia_y_tiempo_osrm(destino)

    estado_inicial = Ticket.ESTADO_APROBADO
    if es_admin and hora_inicio < ahora:
        estado_inicial = Ticket.ESTADO_FINALIZADO
        # Cargar variables de finalización para consistencia del reporte
        kwargs["hora_inicio_real"] = hora_inicio
        if hora_fin:
            kwargs["hora_fin_real"] = hora_fin
        kwargs["kilometraje_inicio"] = 0.0
        kwargs["kilometraje_fin"] = distancia_est

    # ── Caso 1: Sin conflictos ──────────────────────────────────────────────────────
    if not tickets_conflicto:
        ticket = Ticket.objects.create(
            id_usuario=usuario,
            id_vehiculo=vehiculo,
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
            estado=estado_inicial,
            distancia_est=distancia_est,
            **kwargs,
        )
        # Consumir permiso de emergencia si fue usado en esta reserva
        if permiso_emergencia:
            permiso_emergencia.usado = True
            permiso_emergencia.save(update_fields=["usado"])
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

    if not confirmado:
        nombres_cancelados = ", ".join(
            t.id_usuario.nombre_completo for t in tickets_conflicto
        )
        return ResultadoCreacion(
            estado=ResultadoCreacion.REQUIERE_CONFIRMACION,
            mensaje=f"Su reserva se solapa con la de {nombres_cancelados}. ¿Está seguro de que desea cancelar su reserva para darle prioridad a la suya?",
            tickets_cancelados=tickets_conflicto,
        )

    from ..models import PermisoReservaExtraordinaria
    from ..utils.notifications import notify_priority_cancelled

    tickets_cancelados = []
    correos_notificados = set()
    for t_existente in tickets_conflicto:
        cargo_solicitante = usuario.id_cargo.nombre
        motivo = (
            f"Reserva cancelada automáticamente el {timezone.now().strftime('%d/%m/%Y %H:%M')} "
            f"porque {usuario.nombre_completo} ({cargo_solicitante}) "
            f"con mayor jerarquía tomó el vehículo para la misma franja horaria."
        )
        t_existente.estado = Ticket.ESTADO_CANCELADO
        t_existente.observacion = motivo
        t_existente._suppress_signals = True
        t_existente.save(update_fields=["estado", "observacion"])
        tickets_cancelados.append(t_existente)

        # ── Reasignación automática (si hay vehículo y chofer disponibles) ──
        from ..utils.notifications import notify_priority_reassigned

        nuevo_ticket_prioridad = _reasignar_ticket(t_existente, contexto="prioridad")

        # Permiso de emergencia solo si NO hubo reasignación
        # y la salida era en los próximos dias_cancelacion días
        hoy_local = timezone.localdate()
        salida_date = to_local_date(t_existente.hora_inicio)
        tiene_permiso_excepcional = (
            nuevo_ticket_prioridad is None
            and salida_date <= hoy_local + timedelta(days=dias_cancelacion)
        )
        if tiene_permiso_excepcional:
            PermisoReservaExtraordinaria.objects.create(
                usuario=t_existente.id_usuario,
                ticket_cancelado=t_existente,
                motivo=PermisoReservaExtraordinaria.MOTIVO_PRIORIDAD,
                valido_hasta=hoy_local + timedelta(days=dias_cancelacion),
            )

        # Notificar por correo con template amigable (una vez por usuario)
        correo_usuario = t_existente.id_usuario.correo
        if correo_usuario not in correos_notificados:
            try:
                if nuevo_ticket_prioridad:
                    notify_priority_reassigned(t_existente, nuevo_ticket_prioridad)
                else:
                    notify_priority_cancelled(
                        t_existente,
                        tiene_permiso=tiene_permiso_excepcional,
                        dias_gracia=dias_cancelacion,
                    )
                correos_notificados.add(correo_usuario)
            except Exception:
                pass

    ticket = Ticket.objects.create(
        id_usuario=usuario,
        id_vehiculo=vehiculo,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        estado=estado_inicial,
        distancia_est=distancia_est,
        **kwargs,
    )

    # Consumir permiso de emergencia del solicitante si fue usado
    if permiso_emergencia:
        permiso_emergencia.usado = True
        permiso_emergencia.save(update_fields=["usado"])

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

    Regla: Cancelación permitida según configuración global de días de anticipación.

    Args:
        ticket (Ticket): El ticket a cancelar.
        usuario (Usuario): El usuario que intenta cancelar.

    Returns:
        tuple (bool, str): (Éxito, Mensaje descriptivo o de error)
    """
    if ticket.id_usuario != usuario:
        return False, "No tienes permiso para cancelar este ticket."

    if ticket.estado != Ticket.ESTADO_APROBADO:
        return False, "El ticket ya no está activo."

    hoy = timezone.localdate()
    from ..models import ConfiguracionGlobal

    dias_cancelacion = ConfiguracionGlobal.get_solo().dias_anticipacion_cancelacion

    fecha_inicio = to_local_date(ticket.hora_inicio)

    if fecha_inicio < hoy + timedelta(days=dias_cancelacion):
        return (
            False,
            f"No se puede cancelar la reserva con menos de {dias_cancelacion} días de anticipación.",
        )

    ticket.estado = Ticket.ESTADO_CANCELADO
    ahora = timezone.now()
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
    Obtiene todos los tickets aprobados de un vehículo que se solapan con un mes específico.

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
    import calendar
    from datetime import date

    from django.db.models import Q

    ultimo_dia = calendar.monthrange(anio, mes)[1]
    fecha_inicio_mes = date(anio, mes, 1)
    fecha_fin_mes = date(anio, mes, ultimo_dia)

    return (
        Ticket.objects.filter(
            id_vehiculo=vehiculo,
            estado=Ticket.ESTADO_APROBADO,
        )
        .filter(hora_inicio__date__lte=fecha_fin_mes)
        .filter(
            Q(hora_fin__date__gte=fecha_inicio_mes)
            | Q(hora_fin__isnull=True, hora_inicio__date__gte=fecha_inicio_mes)
        )
        .select_related("id_usuario")
    )


def get_tickets_del_dia(vehiculo, fecha):
    """
    Obtiene todos los tickets aprobados de un vehículo que cubren una fecha específica.

    Utilizado en vista de línea de tiempo (HU 3.3) para mostrar ocupación horaria.

    Args:
        vehiculo (Vehiculo): Vehículo a consultar.
        fecha (date): Fecha específica (YYYY-MM-DD).

    Returns:
        QuerySet: Tickets APROBADOS ordenados por hora_inicio ascendente,
            con usuario asociado pre-cargado.

    Notes:
        - Filtra por tickets que cubren la fecha seleccionada.
        - Solo considera tickets APROBADOS.
        - Orden ascendente para mostrar cronológicamente en templates.
    """
    from django.db.models import Q

    return (
        Ticket.objects.filter(
            id_vehiculo=vehiculo,
            estado=Ticket.ESTADO_APROBADO,
        )
        .filter(hora_inicio__date__lte=fecha)
        .filter(
            Q(hora_fin__date__gte=fecha)
            | Q(hora_fin__isnull=True, hora_inicio__date=fecha)
        )
        .order_by("hora_inicio")
        .select_related("id_usuario")
    )


# ══════════════════════════════════════════════════════════════════════════════
# HU 6.x — Baja temporal de vehículo (Admin)
# ══════════════════════════════════════════════════════════════════════════════


def _reasignar_ticket(ticket_original, contexto="baja_temporal"):
    """
    Intenta reasignar automáticamente un ticket cancelado a otro vehículo disponible.

    Args:
        ticket_original (Ticket): Ticket cancelado que se intenta reasignar.
        contexto (str): "baja_temporal" o "prioridad" — usado en la observación del nuevo ticket.

    Criterios de selección:
      - Activo y sin baja temporal en la franja del ticket.
      - No exclusivo_decanato, salvo que el usuario sea Decano.
      - cant_pasajeros >= ticket.cant_pasajeros.
      - Sin conflicto de horario en esa franja.
      - Si requiere chofer: verifica disponibilidad.
      - Ordena por cant_pasajeros ASC (menor suficiente primero).

    Returns:
        Ticket | None: Nuevo ticket APROBADO si pudo reasignar, None si no.
    """
    from ..models import Cargo, Vehiculo
    from ..models import Usuario as UsuarioModel

    hora_inicio = ticket_original.hora_inicio
    hora_fin = ticket_original.hora_fin or (hora_inicio + timedelta(hours=2))
    usuario = ticket_original.id_usuario

    candidatos = (
        Vehiculo.objects.filter(
            activo=True,
            cant_pasajeros__gte=ticket_original.cant_pasajeros,
        )
        .exclude(pk=ticket_original.id_vehiculo_id)
        .order_by("cant_pasajeros")
    )

    if usuario.id_cargo.nombre != Cargo.DECANO:
        candidatos = candidatos.filter(exclusivo_decanato=False)

    for vehiculo_cand in candidatos:
        # Mismo lock pesimista que en crear_ticket_con_reglas: sin él, la comprobación
        # de conflictos de abajo puede quedar obsoleta antes del save() y generar un
        # solapamiento. Ambos call sites de esta función corren dentro de @transaction.atomic.
        vehiculo_cand = Vehiculo.objects.select_for_update().get(pk=vehiculo_cand.pk)

        fecha_inicio_date = to_local_date(hora_inicio)
        fecha_fin_date = to_local_date(hora_fin)
        if vehiculo_cand.esta_inactivo_en_rango(fecha_inicio_date, fecha_fin_date):
            continue

        conflictos = Ticket.objects.filter(
            id_vehiculo=vehiculo_cand,
            estado=Ticket.ESTADO_APROBADO,
            hora_inicio__lt=hora_fin,
            hora_fin__gt=hora_inicio,
        )
        if conflictos.exists():
            continue

        if ticket_original.requiere_chofer:
            total_choferes = UsuarioModel.objects.filter(
                id_cargo__nombre=Cargo.CHOFER, valido=True
            ).count()
            tickets_chofer = Ticket.objects.filter(
                estado__in=[Ticket.ESTADO_APROBADO, Ticket.ESTADO_EN_CURSO],
                requiere_chofer=True,
                hora_inicio__lt=hora_fin,
                hora_fin__gt=hora_inicio,
            )
            if tickets_chofer.count() >= total_choferes:
                continue

        nuevo_ticket = Ticket(
            id_usuario=usuario,
            id_vehiculo=vehiculo_cand,
            hora_inicio=hora_inicio,
            hora_fin=ticket_original.hora_fin,
            estado=Ticket.ESTADO_APROBADO,
            destino=ticket_original.destino,
            cant_pasajeros=ticket_original.cant_pasajeros,
            descripcion=ticket_original.descripcion,
            requiere_chofer=ticket_original.requiere_chofer,
            para_tercero=ticket_original.para_tercero,
            distancia_est=ticket_original.distancia_est,
            observacion=(
                f"Reasignado automáticamente desde ticket #{ticket_original.pk} "
                f"({'vehículo original en baja temporal' if contexto == 'baja_temporal' else 'cancelado por prioridad de otro usuario'})."
            ),
        )
        nuevo_ticket._suppress_signals = True
        nuevo_ticket.save()
        return nuevo_ticket

    return None


@transaction.atomic
def dar_baja_temporal_vehiculo(vehiculo, dias, admin_usuario):
    """
    Marca un vehículo como temporalmente inactivo por N días y cancela/reasigna
    todos los tickets futuros APROBADOS solapados con ese período.

    Args:
        vehiculo (Vehiculo): Vehículo a dar de baja temporalmente.
        dias (int): Cantidad de días de inactividad (> 0).
        admin_usuario (Usuario): Administrador que ejecuta la acción.

    Returns:
        dict: {cancelados, reasignados, total_afectados, inactivo_hasta}
    """
    from ..models import ConfiguracionGlobal, PermisoReservaExtraordinaria
    from ..utils.notifications import (
        notify_vehicle_inactive_cancelled,
        notify_vehicle_inactive_reassigned,
    )

    if not isinstance(dias, int) or dias <= 0:
        raise ValueError("`dias` debe ser un entero positivo mayor a 0.")

    config_global = ConfiguracionGlobal.get_solo()
    dias_cancelacion = config_global.dias_anticipacion_cancelacion

    hoy = timezone.localdate()
    inactivo_hasta = hoy + timedelta(days=dias)

    vehiculo.inactivo_hasta = inactivo_hasta
    vehiculo.save(update_fields=["inactivo_hasta"])

    tickets_afectados = (
        Ticket.objects.filter(
            id_vehiculo=vehiculo,
            estado=Ticket.ESTADO_APROBADO,
        )
        .filter(
            # Solapamiento con [hoy, inactivo_hasta]:
            #   ticket.hora_inicio <= inactivo_hasta
            #   Y (ticket.hora_fin >= hoy  O  ticket es mismo-día Y empieza hoy o después)
            Q(hora_inicio__date__lte=inactivo_hasta)
            & (
                Q(hora_fin__date__gte=hoy)
                | Q(hora_fin__isnull=True, hora_inicio__date__gte=hoy)
            )
        )
        .select_related("id_usuario", "id_vehiculo")
    )

    cancelados = 0
    reasignados = 0

    for ticket in tickets_afectados:
        motivo = (
            f"Reserva cancelada automáticamente el {timezone.now().strftime('%d/%m/%Y %H:%M')} "
            f"porque el vehículo {vehiculo} fue dado de baja temporal por "
            f"{dias} día{'s' if dias != 1 else ''} "
            f"(hasta el {inactivo_hasta.strftime('%d/%m/%Y')}) "
            f"por el administrador {admin_usuario.nombre_completo}."
        )
        ticket.estado = Ticket.ESTADO_CANCELADO
        ticket.observacion = motivo
        ticket._suppress_signals = True
        ticket.save(update_fields=["estado", "observacion"])

        nuevo_ticket = _reasignar_ticket(ticket)
        if nuevo_ticket:
            reasignados += 1
            try:
                notify_vehicle_inactive_reassigned(ticket, nuevo_ticket)
            except Exception:
                pass
        else:
            cancelados += 1
            # Solo si NO se pudo reasignar, otorgar permiso de emergencia (si aplica)
            salida_date = to_local_date(ticket.hora_inicio)
            tiene_permiso_excepcional = salida_date <= hoy + timedelta(
                days=dias_cancelacion
            )
            if tiene_permiso_excepcional:
                PermisoReservaExtraordinaria.objects.create(
                    usuario=ticket.id_usuario,
                    ticket_cancelado=ticket,
                    motivo=PermisoReservaExtraordinaria.MOTIVO_BAJA_VEHICULO,
                    valido_hasta=hoy + timedelta(days=dias_cancelacion),
                )
            try:
                notify_vehicle_inactive_cancelled(
                    ticket,
                    inactivo_hasta=inactivo_hasta,
                    tiene_permiso=tiene_permiso_excepcional,
                    dias_gracia=dias_cancelacion,
                )
            except Exception:
                pass

    return {
        "cancelados": cancelados,
        "reasignados": reasignados,
        "total_afectados": cancelados + reasignados,
        "inactivo_hasta": inactivo_hasta,
    }
