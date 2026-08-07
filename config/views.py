"""
Vistas de infraestructura del proyecto, no ligadas al dominio de reservas.
"""

import logging

from django.db import connection
from django.http import JsonResponse

logger = logging.getLogger(__name__)


def healthz(request):
    """
    Health check para probes de infraestructura (Render, K8s, balanceadores).

    Público y sin CSRF (es un GET simple): no depende de sesión ni de
    autenticación, porque quien lo consulta es el orquestador, no un usuario.

    Verifica conectividad real a la base de datos (no solo que el proceso
    esté vivo) con un SELECT 1: es la dependencia externa que más
    frecuentemente falla en producción y la que un probe "solo devuelve 200"
    no detectaría.

    Returns:
        JsonResponse: 200 {"status": "ok"} si la BD responde.
                      503 {"status": "error", ...} si no.

    Notes:
        Except genérico a propósito: un health check nunca debe devolver un
        500 sin manejar (rompería el contrato que espera el probe). Cualquier
        fallo al hablar con la BD -conexión caída, timeout, lo que sea- se
        traduce siempre a un 503 limpio.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        logger.exception("Health check falló: no se pudo conectar a la base de datos")
        return JsonResponse(
            {"status": "error", "detail": "database unreachable"}, status=503
        )

    return JsonResponse({"status": "ok"})
