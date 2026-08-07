"""
password_recovery.py — Servicio de recuperación de contraseñas.

Responsabilidades:
    1. Crear el registro RecuperacionPassword con código OTP + token UUID.
    2. Enviar el correo con el código de recuperación y el enlace rápido
       (vía send_templated_email/enviar_correo_templated_async — la plantilla
       vive en templates/reservas/emails/password_recovery.html, no acá).
    3. Validar el código ingresado o el enlace rápido.
"""

import logging
import random
import uuid

from django.urls import reverse
from django_q.tasks import async_task

from ..models import RecuperacionPassword

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# Creación del registro
# ══════════════════════════════════════════════════════════════════════════════


def crear_recuperacion(usuario):
    """
    Crea (o reemplaza) el registro RecuperacionPassword para el usuario.
    """
    RecuperacionPassword.objects.filter(usuario=usuario).delete()

    recuperacion = RecuperacionPassword.objects.create(
        usuario=usuario,
        codigo=f"{random.randint(0, 999999):06d}",
        token=uuid.uuid4(),
        usado=False,
    )
    return recuperacion


# ══════════════════════════════════════════════════════════════════════════════
# Envío de correo
# ══════════════════════════════════════════════════════════════════════════════


def enviar_correo_recuperacion(usuario, recuperacion, request):
    """
    Envía el correo de recuperación con código y enlace mágico.

    Usa send_templated_email (vía la tarea async enviar_correo_templated_async):
    renderiza templates/reservas/emails/password_recovery.html y genera el
    texto plano automáticamente con strip_tags(), en vez de mantener dos
    versiones del cuerpo a mano.
    """
    enlace = _construir_enlace_recuperacion(recuperacion.token, request)
    asunto = "Sistema de Reservas — Recuperación de Contraseña"
    contexto = {"usuario": usuario, "codigo": recuperacion.codigo, "enlace": enlace}

    try:
        async_task(
            "reservas.tasks.enviar_correo_templated_async",
            asunto,
            "reservas/emails/password_recovery",
            contexto,
            usuario.correo,
        )
        logger.info("Correo de recuperación enviado a %s", usuario.correo)
        return True
    except Exception as exc:
        logger.error("Error al enviar recuperación a %s: %s", usuario.correo, exc)
        return False


def _construir_enlace_recuperacion(token, request):
    path = reverse("verificar_recuperacion_enlace", kwargs={"token": str(token)})
    return request.build_absolute_uri(path)


# ══════════════════════════════════════════════════════════════════════════════
# Validación
# ══════════════════════════════════════════════════════════════════════════════


class ResultadoRecuperacion:
    OK = "ok"
    EXPIRADO = "expirado"
    INCORRECTO = "incorrecto"
    YA_USADO = "ya_usado"
    DEMASIADOS_INTENTOS = "demasiados_intentos"

    MENSAJES = {
        OK: "Validado correctamente.",
        EXPIRADO: "El código/enlace expiró (30 minutos). Solicitá uno nuevo.",
        INCORRECTO: "Código incorrecto.",
        YA_USADO: "Este código ya fue utilizado.",
        DEMASIADOS_INTENTOS: "Agotaste los intentos permitidos para este código. Solicitá uno nuevo.",
    }

    def __init__(self, estado):
        self.estado = estado
        self.mensaje = self.MENSAJES[estado]

    @property
    def exito(self):
        return self.estado == self.OK


def verificar_recuperacion_por_codigo(usuario, codigo_ingresado):
    """
    Valida el código de 6 dígitos.

    Rate limiting: el código tiene 10**6 combinaciones posibles. Alguien con
    la sesión apuntando a este registro de recuperación -algo que se consigue
    con solo saber el correo de la víctima, sin necesitar el código real: ver
    el comentario en views/email_auth.solicitar_recuperacion()- podría
    probarlas todas dentro de la ventana de 30 minutos si no hubiera límite
    de intentos. Cada código incorrecto suma uno a `intentos_fallidos`; al
    llegar a RecuperacionPassword.MAX_INTENTOS_CODIGO, esta_vigente() empieza
    a devolver False (mismo efecto que si hubiera expirado por tiempo).
    """
    try:
        v = RecuperacionPassword.objects.get(usuario=usuario)
    except RecuperacionPassword.DoesNotExist:
        return ResultadoRecuperacion(ResultadoRecuperacion.EXPIRADO)

    if v.usado:
        return ResultadoRecuperacion(ResultadoRecuperacion.YA_USADO)
    if not v.esta_vigente():
        return ResultadoRecuperacion(ResultadoRecuperacion.EXPIRADO)
    if v.codigo != codigo_ingresado.strip():
        v.intentos_fallidos += 1
        v.save(update_fields=["intentos_fallidos"])
        if v.intentos_fallidos >= RecuperacionPassword.MAX_INTENTOS_CODIGO:
            return ResultadoRecuperacion(ResultadoRecuperacion.DEMASIADOS_INTENTOS)
        return ResultadoRecuperacion(ResultadoRecuperacion.INCORRECTO)

    return ResultadoRecuperacion(ResultadoRecuperacion.OK)


def verificar_recuperacion_por_token(token_str):
    """Valida el UUID."""
    try:
        token_uuid = uuid.UUID(str(token_str))
        v = RecuperacionPassword.objects.select_related("usuario").get(token=token_uuid)
    except (ValueError, RecuperacionPassword.DoesNotExist):
        return ResultadoRecuperacion(ResultadoRecuperacion.INCORRECTO), None

    if v.usado:
        return ResultadoRecuperacion(ResultadoRecuperacion.YA_USADO), v.usuario
    if not v.esta_vigente():
        return ResultadoRecuperacion(ResultadoRecuperacion.EXPIRADO), v.usuario

    return ResultadoRecuperacion(ResultadoRecuperacion.OK), v.usuario


def consumir_recuperacion(usuario):
    """Marca el registro como usado (se llama una vez que cambia la pass)."""
    RecuperacionPassword.objects.filter(usuario=usuario, usado=False).update(usado=True)
