"""Sirve el simulador ADMET en un servidor local y lo abre en el navegador.

El simulador (`simulador_admet.html`) carga OpenChemLib como módulo ES, y los
navegadores no permiten cargar módulos con `file://`; hace falta servirlo por
HTTP. Este script lo hace en un puerto local:

    python src/servir_simulador.py

Luego abre http://127.0.0.1:8000/simulador_admet.html (se abre solo).
"""

import http.server
import socketserver
import webbrowser
from functools import partial
from pathlib import Path

CARPETA = Path(__file__).parent
PUERTO = 8000


class Handler(http.server.SimpleHTTPRequestHandler):
    """Sirve siempre HTML como UTF-8 para que no se rompan las tildes."""

    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".html": "text/html; charset=utf-8",
                      ".js": "text/javascript; charset=utf-8"}


def main():
    handler = partial(Handler, directory=str(CARPETA))
    with socketserver.TCPServer(("127.0.0.1", PUERTO), handler) as servidor:
        url = f"http://127.0.0.1:{PUERTO}/simulador_admet.html"
        print(f"Simulador ADMET en {url}  (Ctrl+C para parar)")
        try:
            webbrowser.open(url)
        except webbrowser.Error:
            pass
        try:
            servidor.serve_forever()
        except KeyboardInterrupt:
            print("\nServidor detenido.")


if __name__ == "__main__":
    main()
