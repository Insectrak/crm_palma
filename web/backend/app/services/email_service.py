"""
Servicio de envío de email usando configuración SMTP guardada en app_settings.
"""
import html
import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

logger = logging.getLogger(__name__)


def _get_smtp_config() -> Optional[dict]:
    """Lee la configuración SMTP desde app_settings en la BD."""
    try:
        from app.database import get_db
        from psycopg2.extras import RealDictCursor

        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT value FROM public.app_settings WHERE key = 'smtp_config'"
                )
                row = cur.fetchone()
                if row:
                    return row["value"]
    except Exception as e:
        logger.error(f"[Email] Error leyendo config SMTP: {e}")
    return None


def send_email(to: str, subject: str, html_body: str) -> dict:
    """
    Envía un email usando la config SMTP almacenada.
    Retorna dict con 'success' (bool) y 'error' (str o None).
    """
    config = _get_smtp_config()
    if not config:
        logger.warning("[Email] No hay configuración SMTP — email no enviado")
        return {"success": False, "error": "No hay configuración SMTP guardada"}

    smtp_server = config.get("smtp_server", "")
    smtp_port = config.get("smtp_port", 587)
    username = config.get("username", "")
    password = config.get("password", "")
    from_address = config.get("from_address", username)
    use_ssl = config.get("use_ssl", False)
    ignore_tls_errors = config.get("ignore_tls_errors", False)

    if not smtp_server or not username or not password:
        msg = f"Config SMTP incompleta: server={bool(smtp_server)}, user={bool(username)}, pass={bool(password)}"
        logger.warning(f"[Email] {msg}")
        return {"success": False, "error": msg}

    msg = MIMEMultipart("alternative")
    msg["From"] = from_address
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        context = ssl.create_default_context()
        if ignore_tls_errors:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

        if use_ssl:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, context=context, timeout=15)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)
            server.starttls(context=context)

        server.login(username, password)
        server.sendmail(from_address, to, msg.as_string())
        server.quit()
        logger.info(f"[Email] Enviado a {to}: {subject}")
        return {"success": True, "error": None}
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[Email] Error enviando a {to}: {error_msg}")
        return {"success": False, "error": error_msg}


_ROLE_DESCRIPTIONS = {
    "admin": (
        "Como administrador podrás gestionar usuarios, configurar la marca, "
        "ver reportes y administrar todos los leads del CRM."
    ),
    "supervisor": (
        "Como supervisor podrás administrar a tu equipo de asesores, ver el "
        "desempeño en tiempo real y reasignar leads cuando lo necesites."
    ),
    "asesor": (
        "Como asesor recibirás leads asignados, podrás contactarlos, agendar "
        "citas y darles seguimiento desde el CRM web o la app móvil."
    ),
}


def send_invitation_email(to: str, invite_url: str, role: str, invited_by: str) -> bool:
    """Envia email de invitacion con link para crear cuenta.

    Diseño table-based (estándar de email marketing — soporta correo profesional, Outlook,
    estilo elegante Mail, Yahoo). Branding dinámico vía brand_service.

    Decisión de diseño: el header es 100% tipográfico (sin <img> ni avatar
    inicial). Dos motivos:
      1. correo profesional/Outlook bloquean data URLs y muchas instalaciones del CRM
         corren con cert self-signed → la imagen sale rota en el cliente.
      2. Estética patrón premium/estilo elegante: wordmark elegante > avatar genérico.
    El branding sigue vivo: banda superior + color del CTA usan primary_color.

    Multi-worker safety: `force_refresh=True` evita que un worker con cache
    stale (hasta 60s) muestre datos viejos del brand cuando el cliente acabó
    de cambiar nombre/color desde otro worker.
    """
    from app.services.brand_service import get_brand

    # force_refresh = True: cada worker uvicorn tiene su propio cache. Si
    # otro worker recibió el PUT /brand recientemente, este worker podría
    # tener una versión vieja. Re-leer de DB para invitaciones es barato
    # (no es un endpoint hot).
    brand    = get_brand(force_refresh=True)
    company  = brand.get("company_name") or "Mi CRM"
    subtitle = brand.get("subtitle") or "Plataforma de Gestión"
    primary  = brand.get("primary_color") or "#4F46E5"
    primary_hover = brand.get("primary_hover") or primary
    role_label = {
        "admin":      "Administrador",
        "supervisor": "Supervisor",
        "asesor":     "Asesor",
    }.get(role, role.capitalize())
    role_blurb = _ROLE_DESCRIPTIONS.get(role, "")

    # Escapamos input dinámico que se interpola en HTML (defense in depth —
    # invited_by viene de auth.users.first_name del que invitó).
    e_company    = html.escape(company)
    e_subtitle   = html.escape(subtitle)
    e_invited_by = html.escape(invited_by or "Un administrador")
    e_role       = html.escape(role_label)
    e_invite_url = html.escape(invite_url, quote=True)

    # Preheader (texto que correo profesional muestra en la lista de inbox antes de abrir)
    preheader = (
        f"{e_invited_by} te invitó a unirte a {e_company} como {e_role}."
    )

    html_body = f"""\
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Invitación a {e_company}</title>
</head>
<body style="margin:0;padding:0;background-color:#F1F5F9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#0F172A;-webkit-font-smoothing:antialiased;">
  <!-- preheader: oculto pero visible en preview del inbox -->
  <div style="display:none;max-height:0;overflow:hidden;color:transparent;line-height:0;font-size:0;">{preheader}</div>

  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color:#F1F5F9;">
    <tr>
      <td align="center" style="padding:40px 16px;">
        <table role="presentation" width="560" cellspacing="0" cellpadding="0" border="0" style="max-width:560px;width:100%;background-color:#FFFFFF;border-radius:18px;overflow:hidden;box-shadow:0 8px 28px rgba(15,23,42,0.08);">

          <!-- Banda superior con color de marca (acento visual) -->
          <tr>
            <td height="4" style="background-color:{primary};font-size:0;line-height:0;">&nbsp;</td>
          </tr>

          <!-- Header tipográfico (wordmark patrón premium/estilo elegante).
               Sin <img> a propósito: evita que correo profesional muestre imagen rota
               cuando el cert HTTPS del CRM es self-signed. -->
          <tr>
            <td align="center" style="padding:44px 36px 8px 36px;">
              <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td align="center" style="font-size:11px;font-weight:700;color:{primary};letter-spacing:2px;text-transform:uppercase;padding-bottom:14px;">
                    Invitación
                  </td>
                </tr>
                <tr>
                  <td align="center" style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:28px;font-weight:700;color:#0F172A;letter-spacing:-0.6px;line-height:1.2;padding-bottom:6px;">
                    {e_company}
                  </td>
                </tr>
                <tr>
                  <td align="center" style="font-size:13px;font-weight:500;color:#64748B;letter-spacing:0.1px;">
                    {e_subtitle}
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Separador sutil -->
          <tr>
            <td align="center" style="padding:28px 36px 0 36px;">
              <table role="presentation" width="40" cellspacing="0" cellpadding="0" border="0">
                <tr><td height="2" style="background-color:{primary};font-size:0;line-height:0;border-radius:2px;">&nbsp;</td></tr>
              </table>
            </td>
          </tr>

          <!-- Cuerpo principal -->
          <tr>
            <td style="padding:36px 36px 8px 36px;">
              <p style="margin:0 0 12px 0;font-size:15px;color:#475569;line-height:1.6;">Hola,</p>
              <p style="margin:0 0 18px 0;font-size:16px;color:#0F172A;line-height:1.6;">
                <strong>{e_invited_by}</strong> te ha invitado a unirte a
                <strong>{e_company}</strong> como <strong>{e_role}</strong>.
              </p>
              <p style="margin:0 0 28px 0;font-size:15px;color:#475569;line-height:1.6;">
                {html.escape(role_blurb)}
              </p>

              <!-- CTA: tabla bulletproof (renderiza igual en Outlook) -->
              <table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center" style="margin:0 auto;">
                <tr>
                  <td align="center" bgcolor="{primary}" style="border-radius:12px;">
                    <a href="{e_invite_url}"
                       style="display:inline-block;padding:15px 40px;font-size:15px;font-weight:600;color:#FFFFFF;text-decoration:none;border-radius:12px;background-color:{primary};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;mso-padding-alt:15px 40px;">
                      Crear mi cuenta
                    </a>
                  </td>
                </tr>
              </table>

              <p style="margin:24px 0 0 0;font-size:13px;color:#94A3B8;text-align:center;line-height:1.6;">
                O copia este enlace en tu navegador:<br/>
                <a href="{e_invite_url}" style="color:{primary_hover};word-break:break-all;text-decoration:none;">{e_invite_url}</a>
              </p>
            </td>
          </tr>

          <!-- Aviso de expiración -->
          <tr>
            <td style="padding:24px 36px 8px 36px;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color:#F8FAFC;border:1px solid #E2E8F0;border-radius:12px;">
                <tr>
                  <td style="padding:14px 18px;font-size:13px;color:#475569;line-height:1.55;">
                    <strong style="color:#0F172A;">El enlace expira en 48 horas.</strong><br/>
                    Si no esperabas esta invitación, puedes ignorar este mensaje con tranquilidad.
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td align="center" style="padding:28px 36px 32px 36px;border-top:1px solid #F1F5F9;margin-top:24px;">
              <p style="margin:0 0 6px 0;font-size:12px;color:#64748B;letter-spacing:0.2px;">
                {e_company} · {e_subtitle}
              </p>
              <p style="margin:0;font-size:11px;color:#94A3B8;">
                Plataforma CRM
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    result = send_email(
        to,
        f"Te invitaron a {company} ({role_label})",
        html_body,
    )
    return result.get("success", False)


def send_password_reset_email(to: str, reset_url: str, recipient_name: str = "") -> dict:
    """Envia email de restablecimiento de contraseña con link de un uso.

    Reusa el mismo lenguaje visual del email de invitación (table-based,
    branding dinámico, wordmark tipográfico) pero con copy específico de
    reset:
      - Subject: "Restablece tu contraseña en {company}"
      - CTA: "Restablecer mi contraseña"
      - Aviso: link expira en 24 horas, single-use
      - Nota de seguridad: si no pediste el reset, ignorá este correo

    Diferencia con `send_invitation_email`:
      - Retorna dict {"success": bool, "error": str|None} en vez de bool,
        para que el caller pueda registrar el motivo del fallo en el
        audit log (auth.audit_password_resets.smtp_error).
    """
    from app.services.brand_service import get_brand

    brand    = get_brand(force_refresh=True)
    company  = brand.get("company_name") or "Mi CRM"
    subtitle = brand.get("subtitle") or "Plataforma de Gestión"
    primary  = brand.get("primary_color") or "#4F46E5"
    primary_hover = brand.get("primary_hover") or primary

    e_company    = html.escape(company)
    e_subtitle   = html.escape(subtitle)
    e_recipient  = html.escape(recipient_name.strip() or "")
    e_reset_url  = html.escape(reset_url, quote=True)

    greeting = f"Hola {e_recipient}," if e_recipient else "Hola,"

    preheader = (
        f"Restablece tu contraseña de {e_company}. El enlace expira en 24 horas."
    )

    html_body = f"""\
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Restablecer contraseña en {e_company}</title>
</head>
<body style="margin:0;padding:0;background-color:#F1F5F9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#0F172A;-webkit-font-smoothing:antialiased;">
  <div style="display:none;max-height:0;overflow:hidden;color:transparent;line-height:0;font-size:0;">{preheader}</div>

  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color:#F1F5F9;">
    <tr>
      <td align="center" style="padding:40px 16px;">
        <table role="presentation" width="560" cellspacing="0" cellpadding="0" border="0" style="max-width:560px;width:100%;background-color:#FFFFFF;border-radius:18px;overflow:hidden;box-shadow:0 8px 28px rgba(15,23,42,0.08);">

          <tr>
            <td height="4" style="background-color:{primary};font-size:0;line-height:0;">&nbsp;</td>
          </tr>

          <tr>
            <td align="center" style="padding:44px 36px 8px 36px;">
              <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td align="center" style="font-size:11px;font-weight:700;color:{primary};letter-spacing:2px;text-transform:uppercase;padding-bottom:14px;">
                    Restablecer contraseña
                  </td>
                </tr>
                <tr>
                  <td align="center" style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:28px;font-weight:700;color:#0F172A;letter-spacing:-0.6px;line-height:1.2;padding-bottom:6px;">
                    {e_company}
                  </td>
                </tr>
                <tr>
                  <td align="center" style="font-size:13px;font-weight:500;color:#64748B;letter-spacing:0.1px;">
                    {e_subtitle}
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td align="center" style="padding:28px 36px 0 36px;">
              <table role="presentation" width="40" cellspacing="0" cellpadding="0" border="0">
                <tr><td height="2" style="background-color:{primary};font-size:0;line-height:0;border-radius:2px;">&nbsp;</td></tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:36px 36px 8px 36px;">
              <p style="margin:0 0 12px 0;font-size:15px;color:#475569;line-height:1.6;">{greeting}</p>
              <p style="margin:0 0 18px 0;font-size:16px;color:#0F172A;line-height:1.6;">
                Recibimos una solicitud para restablecer tu contraseña en <strong>{e_company}</strong>.
              </p>
              <p style="margin:0 0 28px 0;font-size:15px;color:#475569;line-height:1.6;">
                Haz clic en el botón para elegir una nueva contraseña. El enlace es de un solo uso y expira en 24 horas.
              </p>

              <table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center" style="margin:0 auto;">
                <tr>
                  <td align="center" bgcolor="{primary}" style="border-radius:12px;">
                    <a href="{e_reset_url}"
                       style="display:inline-block;padding:15px 40px;font-size:15px;font-weight:600;color:#FFFFFF;text-decoration:none;border-radius:12px;background-color:{primary};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;mso-padding-alt:15px 40px;">
                      Restablecer mi contraseña
                    </a>
                  </td>
                </tr>
              </table>

              <p style="margin:24px 0 0 0;font-size:13px;color:#94A3B8;text-align:center;line-height:1.6;">
                O copia este enlace en tu navegador:<br/>
                <a href="{e_reset_url}" style="color:{primary_hover};word-break:break-all;text-decoration:none;">{e_reset_url}</a>
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:24px 36px 8px 36px;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color:#FEF3F2;border:1px solid #FECDCA;border-radius:12px;">
                <tr>
                  <td style="padding:14px 18px;font-size:13px;color:#7A271A;line-height:1.55;">
                    <strong style="color:#7A271A;">¿No solicitaste este cambio?</strong><br/>
                    Si no pediste restablecer tu contraseña, ignora este mensaje. Tu contraseña actual seguirá siendo válida y nadie podrá acceder a tu cuenta sin ella.
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td align="center" style="padding:28px 36px 32px 36px;border-top:1px solid #F1F5F9;margin-top:24px;">
              <p style="margin:0 0 6px 0;font-size:12px;color:#64748B;letter-spacing:0.2px;">
                {e_company} · {e_subtitle}
              </p>
              <p style="margin:0;font-size:11px;color:#94A3B8;">
                Plataforma CRM
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    return send_email(
        to,
        f"Restablece tu contraseña en {company}",
        html_body,
    )
