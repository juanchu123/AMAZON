"""
comprobar_adjunto.py — ¿el Excel que le llegó a Juan es idéntico al que generó el motor?

El adjunto se manda a Gmail en base64 copiado a mano, y una sola letra mal copiada deja el
Excel dañado (le pasó al de 19/10: Amazon lo rechazó con "El archivo de entrada no es válido
o está dañado"). Después de enviar, se lee el mensaje con get_message (messageFormat RAW): el
correo queda en la transcripción de la sesión, de donde este script lo saca y compara el
adjunto con el archivo local, byte a byte.

    python agente_ads/comprobar_adjunto.py salidas/<día>/bulk_cambios_<día>.xlsx

Sale con 0 si coincide; con 1 si no coincide o no lo encuentra (entonces se reenvía).
"""

import base64
import email
import hashlib
import re
import sys
from pathlib import Path

TRANSCRIPCIONES = Path.home() / ".claude" / "projects"
BASE64URL = re.compile(r"[A-Za-z0-9_\-]{2000,}={0,2}")


def adjuntos_enviados(nombre):
    """Los adjuntos llamados `nombre` de los correos RAW leídos en las sesiones, del más reciente al más antiguo."""
    rutas = sorted(TRANSCRIPCIONES.glob("**/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for ruta in rutas:
        for bloque in reversed(BASE64URL.findall(ruta.read_text(encoding="utf-8", errors="ignore"))):
            try:
                correo = email.message_from_bytes(base64.urlsafe_b64decode(bloque + "=="))
            except ValueError:
                continue
            for parte in correo.walk():
                if parte.get_filename() == nombre:
                    yield parte.get_payload(decode=True)


def main(ruta):
    local = Path(ruta).read_bytes()
    enviado = next(adjuntos_enviados(Path(ruta).name), None)
    if enviado is None:
        print(f"No encuentro el adjunto {Path(ruta).name}: lee el correo enviado con get_message RAW.")
        return 1
    if enviado != local:
        print(f"MAL: el adjunto enviado ({len(enviado)} bytes, md5 {hashlib.md5(enviado).hexdigest()}) "
              f"no es el local ({len(local)} bytes, md5 {hashlib.md5(local).hexdigest()}). Reenvíalo.")
        return 1
    print(f"OK: el adjunto enviado es idéntico al local (md5 {hashlib.md5(local).hexdigest()}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
