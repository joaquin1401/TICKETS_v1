"""
Filtro de template para el color del badge de Ticket.estado.

Antes, 5 templates repetían a mano la misma cadena
{% if estado == 'aprobado' %}success{% elif estado == 'cancelado' %}danger{% else %}warning{% endif %},
que solo distinguía 2 de los 5 estados posibles: en_curso y finalizado
caían en "warning", el mismo color que pendiente, aunque no tengan nada
que ver (un viaje ya terminado se veía "pendiente" en la UI).

Uso en template:
    {% load estado_tags %}
    <span class="badge badge-{{ ticket.estado|badge_estado }}">...</span>
"""

from django import template

from ..models import Ticket

register = template.Library()

_BADGE_POR_ESTADO = {
    Ticket.ESTADO_PENDIENTE: "warning",
    Ticket.ESTADO_APROBADO: "success",
    Ticket.ESTADO_EN_CURSO: "info",
    Ticket.ESTADO_FINALIZADO: "neutral",
    Ticket.ESTADO_CANCELADO: "danger",
}


@register.filter
def badge_estado(estado):
    """
    Devuelve el sufijo de clase CSS (badge-<esto>) para un Ticket.estado.

    Si en el futuro se agrega un estado nuevo al modelo y se olvidan de
    mapearlo acá, cae en "neutral" en vez de heredar el color de otro
    estado por accidente (lo que pasaba antes con el if/elif a mano).
    """
    return _BADGE_POR_ESTADO.get(estado, "neutral")
