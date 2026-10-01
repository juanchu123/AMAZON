"""
emailer.py
----------
Envía el informe por email (SMTP). Con Gmail: activa la verificación en dos
pasos y crea una "contraseña de aplicación"; no uses tu contraseña normal.

Si no hay SMTP configurado, no falla: el informe queda guardado en la
carpeta de informes y se avisa por consola.
"""

import mimetypes
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path


def smtp_configured() -> bool:
    return all(os.environ.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO"))


def send_report(subject: str, body_markdown: str, attachments: list[Path] | None = None) -> bool:
    if not smtp_configured():
        print("[email] SMTP no configurado (SMTP_HOST/SMTP_USER/SMTP_PASSWORD/EMAIL_TO): no se envía.")
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("EMAIL_FROM") or os.environ["SMTP_USER"]
    msg["To"] = os.environ["EMAIL_TO"]
    msg.set_content(body_markdown)
    for path in attachments or []:
        ctype, _ = mimetypes.guess_type(str(path))
        maintype, subtype = (ctype or "text/plain").split("/", 1)
        msg.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=60) as s:
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=60) as s:
            s.starttls(context=ctx)
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
    print(f"[email] Informe enviado a {msg['To']}")
    return True
