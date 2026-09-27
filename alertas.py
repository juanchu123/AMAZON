"""
alertas.py — correos a Juan (AGENTE_AUTONOMO.md §2.9).

  - Un correo por ronda con TODOS los cambios aplicados (no uno por cambio).
  - Aviso inmediato y aparte si la cuenta parece parada (§2.9-bis) o hay anuncios no elegibles.

Envío por SMTP con variables de entorno (nunca en el código):
  SMTP_HOST (p. ej. smtp.gmail.com), SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD, SMTP_FROM (opcional)
Con Gmail, SMTP_PASSWORD es una "contraseña de aplicación" (Cuenta de Google -> Seguridad ->
Verificación en 2 pasos -> Contraseñas de aplicaciones), no tu contraseña normal.

Si no hay SMTP configurado (o falla), el correo se guarda como .eml en
resultados/correos_pendientes/ y queda anotado en la hoja Alertas: nunca se pierde un aviso.
"""

import os
import smtplib
import ssl
from email.message import EmailMessage

import config


def _smtp_configurado():
    return all(os.environ.get(v) for v in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"))


def enviar(asunto, cuerpo, ahora, simular=False):
    """Devuelve cómo se entregó: 'enviado', 'pendiente (<ruta>)'."""
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER") or "agente-freshfinder@localhost"
    msg["To"] = config.EMAIL_DESTINO
    msg.set_content(cuerpo)
    error = ""
    if _smtp_configurado():
        try:
            with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=30) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
                s.send_message(msg)
            return "enviado"
        except (smtplib.SMTPException, OSError) as e:
            error = f" — error SMTP: {e}"
    config.CORREOS_PENDIENTES.mkdir(parents=True, exist_ok=True)
    ruta = config.CORREOS_PENDIENTES / f"{ahora:%Y%m%d_%H%M%S}_{_slug(asunto)}.eml"
    ruta.write_bytes(bytes(msg))
    motivo = "sin SMTP configurado" if not error else error.strip(" —")
    return f"pendiente ({ruta.name}; {motivo})"


def _slug(t):
    return "".join(ch if ch.isalnum() else "_" for ch in t.lower())[:40]


def resumen_cambios(cambios, descartados, alertas, hoy, simular):
    """Cuerpo del correo de la ronda."""
    lineas = [f"Ronda del agente de Amazon Ads — {hoy:%d/%m/%Y}" + (" (SIMULACIÓN: no se ha tocado nada)" if simular else ""), ""]
    for titulo, filtro in (("Aplicados y confirmados en Amazon", "confirmado"),
                           ("Enviados en hoja masiva (se confirmarán al leer la próxima descarga)", "enviado_bulk"),
                           ("Simulados (no aplicados)", "simulado"),
                           ("FALLIDOS (no se aplicaron o Amazon no los refleja)", "fallido")):
        grupo = [c for c in cambios if c.estado == filtro]
        if not grupo:
            continue
        lineas += [f"{titulo}: {len(grupo)}", "-" * 60]
        for c in grupo:
            antes = "—" if c.antes is None else c.antes
            despues = "—" if c.despues is None else c.despues
            lineas.append(f"• [{c.tipo}] {c.campana} | {c.texto} {('(' + c.coincidencia + ')') if c.coincidencia else ''}: "
                          f"{antes} -> {despues}")
            lineas.append(f"    Motivo: {c.motivo}")
            if c.detalle:
                lineas.append(f"    Comprobación: {c.detalle}")
            if c.requiere_revision:
                lineas.append("    ⚠ REQUIERE TU REVISIÓN (no se reactivará sola)")
        lineas.append("")
    if descartados:
        lineas += [f"Descartados por las reglas de seguridad: {len(descartados)}", "-" * 60]
        lineas += [f"• [{c.tipo}] {c.campana} | {c.texto}: {m}" for c, m in descartados]
        lineas.append("")
    if alertas:
        lineas += ["Avisos", "-" * 60] + [f"• {m}" for _, _, m in alertas] + [""]
    lineas.append("Detalle completo en el documento único (hoja Tickets).")
    return "\n".join(lineas)
