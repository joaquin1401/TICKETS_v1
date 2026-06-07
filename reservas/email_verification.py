"""
email_verification.py — Servicio de verificación de correo electrónico.

Este módulo es NUEVO. Se llama desde views.registro() y no toca
ninguna lógica existente del sistema.

Responsabilidades:
    1. Crear el registro VerificacionCorreo con código + token UUID.
    2. Enviar el correo HTML con ambos métodos al usuario.
    3. Validar el código de 6 dígitos ingresado en el formulario.
    4. Validar el token UUID del enlace mágico.

Dos métodos de verificación, un solo correo:
    - Código de 6 dígitos → usuario lo ingresa en /verificar-correo/.
    - Enlace mágico (UUID) → usuario hace clic en el correo.
    Ambos comparten el mismo VerificacionCorreo y expiran a los 30 minutos.

Dependencias:
    - django.core.mail.send_mail  (configurado en settings.py con Gmail SMTP)
    - .models.VerificacionCorreo  (modelo nuevo en models.py)
    - django.urls.reverse          (para construir el enlace absoluto)

Integración con views.py:
    from .email_verification import (
        crear_verificacion,
        enviar_correo_verificacion,
        verificar_por_codigo,
        verificar_por_token,
    )
"""

import uuid
import random
import logging

from django_q.tasks import async_task
from django.conf import settings
from django.utils import timezone
from django.urls import reverse

from .models import VerificacionCorreo

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Creación del registro de verificación
# ══════════════════════════════════════════════════════════════════════════════

def crear_verificacion(usuario):
    """
    Crea (o reemplaza) el registro VerificacionCorreo para el usuario.

    Si ya existe un registro previo (ej: reenvío solicitado), lo elimina
    antes de crear el nuevo. Esto garantiza que solo existe un código/token
    activo por usuario en todo momento.

    Genera simultáneamente:
        - Un código numérico de 6 dígitos con zero-padding (ej: "048721").
        - Un token UUID v4 único para el enlace mágico.

    Args:
        usuario (Usuario): Instancia del modelo Usuario. Debe estar guardada
            en la BD (tener PK asignado) antes de llamar esta función.

    Returns:
        VerificacionCorreo: La instancia recién creada, lista para enviar.

    Example:
        >>> verificacion = crear_verificacion(usuario)
        >>> # verificacion.codigo  → "048721"
        >>> # verificacion.token   → UUID('550e8400-e29b-41d4-...')
    """
    # Eliminar verificación anterior si existe (reenvío o intento previo fallido)
    VerificacionCorreo.objects.filter(usuario=usuario).delete()

    verificacion = VerificacionCorreo.objects.create(
        usuario=usuario,
        codigo=_generar_codigo(),
        token=uuid.uuid4(),
        usado=False,
    )
    return verificacion


def _generar_codigo():
    """
    Genera un código numérico de 6 dígitos con zero-padding.

    Returns:
        str: Código de exactamente 6 dígitos (ej: "004821", "999003").

    Notes:
        El formato ":06d" garantiza que números bajos como 48 se
        representen como "000048" en vez de "48", siempre 6 caracteres.
    """
    return f"{random.randint(0, 999999):06d}"


# ══════════════════════════════════════════════════════════════════════════════
# Envío del correo de verificación
# ══════════════════════════════════════════════════════════════════════════════

def enviar_correo_verificacion(usuario, verificacion, request):
    """
    Envía el correo con el código de 6 dígitos y el enlace mágico.

    Usa send_mail() de Django, que está configurado con Gmail SMTP en
    settings.py (EMAIL_HOST, EMAIL_HOST_USER, etc.).

    El correo se envía con dos partes:
        - cuerpo_texto: versión plana para clientes sin soporte HTML.
        - cuerpo_html:  versión visual con el código grande y botón de enlace.

    Args:
        usuario (Usuario): Destinatario del correo.
        verificacion (VerificacionCorreo): Registro con código y token.
        request (HttpRequest): Necesario para construir la URL absoluta
            del enlace mágico con request.build_absolute_uri().

    Returns:
        bool: True si el correo se envió sin excepciones, False si falló.

    Notes:
        Los errores se registran en el logger pero no se propagan.
        La vista muestra un mensaje de advertencia si retorna False,
        permitiendo al usuario solicitar reenvío manualmente.
    """
    enlace = _construir_enlace(verificacion.token, request)
    asunto = "Sistema de Reserva de Vehículos — Verificá tu correo"

    try:
        async_task(
            "reservas.tasks.enviar_correo_async",
            subject=asunto,
            message=_cuerpo_texto(usuario, verificacion.codigo, enlace),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[usuario.correo],
            html_message=_cuerpo_html(usuario, verificacion.codigo, enlace),
            fail_silently=False,
        )
        logger.info("Correo de verificación enviado a %s", usuario.correo)
        return True
    except Exception as exc:
        logger.error("Error al enviar correo a %s: %s", usuario.correo, exc)
        return False


def _construir_enlace(token, request):
    """
    Construye la URL absoluta del enlace mágico de verificación.

    Usa request.build_absolute_uri() para incluir el esquema (http/https)
    y el dominio correcto según el entorno (desarrollo o producción).

    Args:
        token (UUID): Token de la instancia VerificacionCorreo.
        request (HttpRequest): Request actual para obtener el dominio.

    Returns:
        str: URL completa (ej: "http://localhost:8000/verificar-correo/550e8400-.../").
    """
    path = reverse("verificar_correo_enlace", kwargs={"token": str(token)})
    return request.build_absolute_uri(path)


def _cuerpo_texto(usuario, codigo, enlace):
    """
    Cuerpo del correo en texto plano (fallback para clientes sin HTML).

    Args:
        usuario (Usuario): Para personalizar el saludo.
        codigo (str): Código de 6 dígitos.
        enlace (str): URL del enlace mágico.

    Returns:
        str: Texto plano del correo.
    """
    return f"""Hola {usuario.nombre},

Para verificar tu correo en el Sistema de Reserva de Vehículos tenés dos opciones:

OPCIÓN 1 — Ingresá este código en el formulario:
  {codigo}

OPCIÓN 2 — Hacé clic en este enlace:
  {enlace}

El código y el enlace expiran en 30 minutos.

Si no creaste una cuenta, ignorá este mensaje.

— Sistema de Reserva de Vehículos
"""


def _cuerpo_html(usuario, codigo, enlace):
    """
    Cuerpo del correo en HTML con diseño visual adaptado al sistema.

    El diseño replica la paleta oscura del sistema (--bg: #0f1014,
    --accent: #e8a020) para consistencia visual con la interfaz web.
    Usa estilos inline para máxima compatibilidad con clientes de correo.

    Args:
        usuario (Usuario): Para personalizar el saludo con nombre.
        codigo (str): Código de 6 dígitos a mostrar en grande.
        enlace (str): URL del botón de verificación.

    Returns:
        str: HTML completo del correo.
    """
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#0f1014;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f1014;padding:40px 16px;">
    <tr>
      <td align="center">
        <table width="520" cellpadding="0" cellspacing="0"
               style="background:#181b22;border:1px solid #2a2f3d;border-radius:8px;overflow:hidden;max-width:520px;width:100%;">

          <!-- Header -->
          <tr>
            <td style="padding:24px 32px 20px;border-bottom:1px solid #2a2f3d;">
              <span style="font-size:18px;color:#e8a020;font-weight:700;letter-spacing:0.02em;">
                Sistema de Reserva de Vehículos
              </span>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:28px 32px;">
              <p style="margin:0 0 8px;font-size:17px;color:#dde1ea;font-weight:500;">
                Hola, {usuario.nombre} 👋
              </p>
              <p style="margin:0 0 24px;font-size:14px;color:#9aa0ad;line-height:1.6;">
                Para completar tu registro necesitamos verificar tu correo electrónico.<br>
                Usá cualquiera de estas dos opciones:
              </p>

              <!-- Opción 1: Código -->
              <div style="background:#1f232d;border:1px solid #2a2f3d;border-radius:6px;padding:20px 24px;margin-bottom:16px;">
                <p style="margin:0 0 12px;font-size:11px;font-family:monospace;color:#6b7280;text-transform:uppercase;letter-spacing:0.1em;">
                  Opción 1 — Código de verificación
                </p>
                <div style="text-align:center;">
                  <span style="font-size:40px;font-family:monospace;font-weight:700;color:#e8a020;letter-spacing:12px;">
                    {codigo}
                  </span>
                </div>
                <p style="margin:10px 0 0;font-size:11px;color:#6b7280;text-align:center;">
                  Ingresá este código en el formulario de verificación
                </p>
              </div>

              <!-- Opción 2: Enlace mágico -->
              <div style="background:#1f232d;border:1px solid #2a2f3d;border-radius:6px;padding:20px 24px;margin-bottom:24px;">
                <p style="margin:0 0 12px;font-size:11px;font-family:monospace;color:#6b7280;text-transform:uppercase;letter-spacing:0.1em;">
                  Opción 2 — Enlace mágico
                </p>
                <a href="{enlace}"
                   style="display:block;text-align:center;background:#e8a020;color:#0f1014;padding:12px 24px;border-radius:5px;text-decoration:none;font-weight:600;font-size:14px;">
                  ✓ Verificar mi correo
                </a>
              </div>

              <!-- Expiración -->
              <p style="margin:0;font-size:12px;color:#6b7280;text-align:center;">
                ⏱ El código y el enlace expiran en
                <strong style="color:#9aa0ad;">30 minutos</strong>
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:16px 32px;border-top:1px solid #2a2f3d;background:#0f1014;">
              <p style="margin:0;font-size:11px;color:#6b7280;text-align:center;">
                Si no creaste una cuenta en este sistema, ignorá este mensaje.<br>
                Este correo fue generado automáticamente, por favor no respondas.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# Validación — Código de 6 dígitos
# ══════════════════════════════════════════════════════════════════════════════

class ResultadoVerificacion:
    """
    Objeto de resultado para operaciones de verificación.

    Centraliza los posibles estados y sus mensajes para que las vistas
    no necesiten conocer la lógica interna de validación.

    Estados:
        OK:         Verificación exitosa. correo_verificado pasó a True.
        EXPIRADO:   El código/token tiene más de 30 minutos. Solicitar reenvío.
        INCORRECTO: El código no coincide o el token UUID no existe.
        YA_USADO:   Ya fue verificado anteriormente con este mismo registro.

    Uso en vistas:
        resultado = verificar_por_codigo(usuario, codigo)
        if resultado.exito:
            # redirigir al login
        else:
            messages.error(request, resultado.mensaje)
    """

    OK         = "ok"
    EXPIRADO   = "expirado"
    INCORRECTO = "incorrecto"
    YA_USADO   = "ya_usado"

    MENSAJES = {
        OK:         "¡Correo verificado correctamente!",
        EXPIRADO:   "El código expiró (30 minutos). Hacé clic en 'Reenviar correo'.",
        INCORRECTO: "Código incorrecto. Verificá que lo hayas copiado bien.",
        YA_USADO:   "Este código ya fue utilizado anteriormente.",
    }

    def __init__(self, estado):
        self.estado  = estado
        self.mensaje = self.MENSAJES[estado]

    @property
    def exito(self):
        """Retorna True solo si el estado es OK."""
        return self.estado == self.OK


def verificar_por_codigo(usuario, codigo_ingresado):
    """
    Valida el código de 6 dígitos ingresado en el formulario.

    Busca el registro VerificacionCorreo del usuario, evalúa si está
    vigente y si el código coincide. Si todo es correcto, marca el
    correo como verificado y consume el registro.

    Args:
        usuario (Usuario): El usuario cuyo código se está verificando.
            Se obtiene de request.session["verificacion_uid"] en la vista.
        codigo_ingresado (str): Código de 6 dígitos del formulario
            (ya validado como numérico por VerificacionCodigoForm).

    Returns:
        ResultadoVerificacion: Objeto con estado y mensaje para la vista.

    Side effects:
        Si el código es correcto:
            - usuario.correo_verificado = True (guardado en BD).
            - verificacion.usado = True (guardado en BD).
    """
    try:
        v = VerificacionCorreo.objects.get(usuario=usuario)
    except VerificacionCorreo.DoesNotExist:
        # No existe registro: o nunca se registró o ya fue eliminado
        return ResultadoVerificacion(ResultadoVerificacion.EXPIRADO)

    if v.usado:
        return ResultadoVerificacion(ResultadoVerificacion.YA_USADO)

    if not v.esta_vigente():
        return ResultadoVerificacion(ResultadoVerificacion.EXPIRADO)

    if v.codigo != codigo_ingresado.strip():
        return ResultadoVerificacion(ResultadoVerificacion.INCORRECTO)

    # Todo correcto: marcar como verificado y consumir el registro
    _marcar_verificado(usuario, v)
    return ResultadoVerificacion(ResultadoVerificacion.OK)


# ══════════════════════════════════════════════════════════════════════════════
# Validación — Token UUID (enlace mágico)
# ══════════════════════════════════════════════════════════════════════════════

def verificar_por_token(token_str):
    """
    Valida el token UUID del enlace mágico enviado por correo.

    Se llama desde views.verificar_correo_enlace() cuando el usuario
    hace clic en el botón del email. Django ya validó el formato UUID
    con el conversor <uuid:token> en urls.py, pero esta función también
    maneja el caso de token no encontrado en BD.

    Args:
        token_str (str): Representación string del UUID recibida en la URL.
            Siempre es un UUID válido en formato string gracias al conversor
            <uuid:> de Django, pero puede no existir en la BD.

    Returns:
        tuple[ResultadoVerificacion, Usuario | None]:
            - (OK, usuario)         → verificación exitosa.
            - (EXPIRADO, usuario)   → token expirado; usuario conocido.
            - (YA_USADO, usuario)   → ya verificado; usuario conocido.
            - (INCORRECTO, None)    → token no encontrado en BD.

    Side effects:
        Si el token es correcto:
            - usuario.correo_verificado = True (guardado en BD).
            - verificacion.usado = True (guardado en BD).
    """
    try:
        token_uuid = uuid.UUID(str(token_str))
        v = VerificacionCorreo.objects.select_related("usuario").get(token=token_uuid)
    except (ValueError, VerificacionCorreo.DoesNotExist):
        # Token con formato inválido o no existe en la BD
        return ResultadoVerificacion(ResultadoVerificacion.INCORRECTO), None

    if v.usado:
        return ResultadoVerificacion(ResultadoVerificacion.YA_USADO), v.usuario

    if not v.esta_vigente():
        return ResultadoVerificacion(ResultadoVerificacion.EXPIRADO), v.usuario

    # Todo correcto
    _marcar_verificado(v.usuario, v)
    return ResultadoVerificacion(ResultadoVerificacion.OK), v.usuario


# ══════════════════════════════════════════════════════════════════════════════
# Helper interno
# ══════════════════════════════════════════════════════════════════════════════

def _marcar_verificado(usuario, verificacion):
    """
    Marca el correo como verificado y consume el token/código.

    Operación atómica en dos pasos:
        1. usuario.correo_verificado = True  → permite el login.
        2. verificacion.usado = True         → invalida reutilización.

    Usa update_fields para actualizar solo los campos necesarios,
    evitando sobreescribir otros cambios concurrentes en el modelo.

    Args:
        usuario (Usuario): Usuario a marcar como verificado.
        verificacion (VerificacionCorreo): Registro a consumir.
    """
    usuario.correo_verificado = True
    usuario.save(update_fields=["correo_verificado"])

    verificacion.usado = True
    verificacion.save(update_fields=["usado"])
