"""
Rate limiting simple para el login (HU 1.2).

No usa el framework de cache de Django: LocMemCache no comparte estado entre
procesos worker de gunicorn (cada uno tendría su propio contador, sin ningún
límite real bajo un deploy con más de un worker), y DatabaseCache exige un
paso de deploy nuevo (`createcachetable`) fácil de olvidar. En cambio, sigue
el mismo patrón que ya usa el resto del proyecto para "no dejar que algo pase
demasiado seguido": un modelo dedicado (IntentoLoginFallido) + conteo por
ventana de tiempo, igual que NotificationLog.

Se aplican dos límites independientes, pensados para amenazas distintas:
    - por IP: alguien probando muchas combinaciones correo:contraseña
      distintas desde un mismo origen (credential stuffing / scaneo).
    - por correo intentado: alguien probando muchas contraseñas contra UNA
      cuenta puntual, sin importar desde qué IP (protege la cuenta aunque el
      atacante rote de IP).
"""

from datetime import timedelta

from django.utils import timezone

from ..models import IntentoLoginFallido

MAX_INTENTOS_POR_IP = 10
MAX_INTENTOS_POR_CORREO = 5
VENTANA_MINUTOS = 15


def obtener_ip(request):
    """
    IP del cliente, considerando un proxy inverso delante de gunicorn
    (Render, Heroku, Nginx) vía X-Forwarded-For. Si hay varios proxies
    encadenados, la primera IP de la lista es la del cliente original.
    """
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or "0.0.0.0"


def login_bloqueado(request, correo):
    """
    True si login_view debe rechazar el intento sin siquiera validar
    credenciales: ya sea la IP o el correo intentado acumularon demasiados
    intentos fallidos en los últimos VENTANA_MINUTOS minutos.
    """
    desde = timezone.now() - timedelta(minutes=VENTANA_MINUTOS)
    ip = obtener_ip(request)

    intentos_ip = IntentoLoginFallido.objects.filter(
        ip=ip, creado_en__gte=desde
    ).count()
    if intentos_ip >= MAX_INTENTOS_POR_IP:
        return True

    if correo:
        intentos_correo = IntentoLoginFallido.objects.filter(
            correo_intentado__iexact=correo, creado_en__gte=desde
        ).count()
        if intentos_correo >= MAX_INTENTOS_POR_CORREO:
            return True

    return False


def registrar_intento_fallido(request, correo):
    """Registra un intento de login fallido (credenciales inválidas)."""
    IntentoLoginFallido.objects.create(
        ip=obtener_ip(request), correo_intentado=correo or ""
    )
