"""
password_recovery.py — Servicio de recuperación de contraseñas.

Responsabilidades:
    1. Crear el registro RecuperacionPassword con código OTP + token UUID.
    2. Enviar el correo HTML con el código de recuperación y el enlace rápido.
    3. Validar el código ingresado o el enlace rápido.
"""

import uuid
import random
import logging

from django_q.tasks import async_task
from django.conf import settings
from django.utils import timezone
from django.urls import reverse

from .models import RecuperacionPassword

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
    """
    enlace = _construir_enlace_recuperacion(recuperacion.token, request)
    asunto = "Sistema de Reservas — Recuperación de Contraseña"

    try:
        async_task(
            "reservas.tasks.enviar_correo_async",
            subject=asunto,
            message=_cuerpo_texto(usuario, recuperacion.codigo, enlace),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[usuario.correo],
            html_message=_cuerpo_html(usuario, recuperacion.codigo, enlace),
            fail_silently=False,
        )
        logger.info("Correo de recuperación enviado a %s", usuario.correo)
        return True
    except Exception as exc:
        logger.error("Error al enviar recuperación a %s: %s", usuario.correo, exc)
        return False

def _construir_enlace_recuperacion(token, request):
    path = reverse("verificar_recuperacion_enlace", kwargs={"token": str(token)})
    return request.build_absolute_uri(path)

def _cuerpo_texto(usuario, codigo, enlace):
    return f"""Hola {usuario.nombre},

Recibimos una solicitud para restablecer tu contraseña.

OPCIÓN 1 — Ingresá este código numérico:
  {codigo}

OPCIÓN 2 — Hacé clic en este enlace:
  {enlace}

Si no solicitaste recuperar tu contraseña, podés ignorar este correo de forma segura. El código expirará en 30 minutos.

— Sistema de Reserva de Vehículos
"""

def _cuerpo_html(usuario, codigo, enlace):
    return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#0f1014;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f1014;padding:40px 16px;">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0" style="background:#181b22;border:1px solid #2a2f3d;border-radius:8px;max-width:520px;width:100%;">
        <tr>
          <td style="padding:24px 32px 20px;border-bottom:1px solid #2a2f3d;">
            <span style="font-size:18px;color:#e8a020;font-weight:700;">Sistema de Reservas</span>
          </td>
        </tr>
        <tr>
          <td style="padding:28px 32px;">
            <p style="margin:0 0 8px;font-size:17px;color:#dde1ea;font-weight:500;">Hola, {usuario.nombre} 👋</p>
            <p style="margin:0 0 24px;font-size:14px;color:#9aa0ad;line-height:1.6;">Recibimos una solicitud para restablecer tu contraseña. Elegí una opción:</p>
            
            <div style="background:#1f232d;border:1px solid #2a2f3d;border-radius:6px;padding:20px 24px;margin-bottom:16px;">
              <p style="margin:0 0 12px;font-size:11px;font-family:monospace;color:#6b7280;text-transform:uppercase;">Opción 1 — Código numérico</p>
              <div style="text-align:center;">
                <span style="font-size:40px;font-family:monospace;font-weight:700;color:#e8a020;letter-spacing:12px;">{codigo}</span>
              </div>
            </div>

            <div style="background:#1f232d;border:1px solid #2a2f3d;border-radius:6px;padding:20px 24px;margin-bottom:24px;">
              <p style="margin:0 0 12px;font-size:11px;font-family:monospace;color:#6b7280;text-transform:uppercase;">Opción 2 — Enlace rápido</p>
              <a href="{enlace}" style="display:block;text-align:center;background:#e8a020;color:#0f1014;padding:12px 24px;border-radius:5px;text-decoration:none;font-weight:600;font-size:14px;">
                Restablecer Contraseña
              </a>
            </div>

            <p style="margin:0;font-size:12px;color:#6b7280;text-align:center;">⏱ Expira en <strong style="color:#9aa0ad;">30 minutos</strong></p>
          </td>
        </tr>
        <tr>
          <td style="padding:16px 32px;border-top:1px solid #2a2f3d;background:#0f1014;">
            <p style="margin:0;font-size:11px;color:#6b7280;text-align:center;">Si no solicitaste esto, ignorá el mensaje.</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body></html>"""

# ══════════════════════════════════════════════════════════════════════════════
# Validación
# ══════════════════════════════════════════════════════════════════════════════

class ResultadoRecuperacion:
    OK         = "ok"
    EXPIRADO   = "expirado"
    INCORRECTO = "incorrecto"
    YA_USADO   = "ya_usado"

    MENSAJES = {
        OK:         "Validado correctamente.",
        EXPIRADO:   "El código/enlace expiró (30 minutos). Solicitá uno nuevo.",
        INCORRECTO: "Código incorrecto.",
        YA_USADO:   "Este código ya fue utilizado.",
    }

    def __init__(self, estado):
        self.estado  = estado
        self.mensaje = self.MENSAJES[estado]

    @property
    def exito(self):
        return self.estado == self.OK


def verificar_recuperacion_por_codigo(usuario, codigo_ingresado):
    """Valida el código de 6 dígitos."""
    try:
        v = RecuperacionPassword.objects.get(usuario=usuario)
    except RecuperacionPassword.DoesNotExist:
        return ResultadoRecuperacion(ResultadoRecuperacion.EXPIRADO)

    if v.usado: return ResultadoRecuperacion(ResultadoRecuperacion.YA_USADO)
    if not v.esta_vigente(): return ResultadoRecuperacion(ResultadoRecuperacion.EXPIRADO)
    if v.codigo != codigo_ingresado.strip(): return ResultadoRecuperacion(ResultadoRecuperacion.INCORRECTO)

    return ResultadoRecuperacion(ResultadoRecuperacion.OK)


def verificar_recuperacion_por_token(token_str):
    """Valida el UUID."""
    try:
        token_uuid = uuid.UUID(str(token_str))
        v = RecuperacionPassword.objects.select_related("usuario").get(token=token_uuid)
    except (ValueError, RecuperacionPassword.DoesNotExist):
        return ResultadoRecuperacion(ResultadoRecuperacion.INCORRECTO), None

    if v.usado: return ResultadoRecuperacion(ResultadoRecuperacion.YA_USADO), v.usuario
    if not v.esta_vigente(): return ResultadoRecuperacion(ResultadoRecuperacion.EXPIRADO), v.usuario

    return ResultadoRecuperacion(ResultadoRecuperacion.OK), v.usuario


def consumir_recuperacion(usuario):
    """Marca el registro como usado (se llama una vez que cambia la pass)."""
    RecuperacionPassword.objects.filter(usuario=usuario, usado=False).update(usado=True)
