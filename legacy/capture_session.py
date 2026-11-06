"""
capture_session.py
-------------------
Ejecuta ESTO UNA VEZ, a mano, para generar el archivo de sesión que el
agente diario reutilizará sin volver a pedirte login.

Uso:
    python src/capture_session.py

Qué hace:
    1. Abre un navegador Chromium visible (headless=False).
    2. Te deja iniciar sesión tú mismo en advertising.amazon.es
       (usuario, contraseña, 2FA si aplica).
    3. Cuando confirmes en la terminal que ya has entrado, guarda las
       cookies/tokens de sesión en .auth/session.json.

El agente diario (run_daily.py) carga ese archivo y navega ya autenticado,
sin que vuelvas a escribir tu contraseña.

Cuándo tienes que volver a ejecutar esto:
    - Si run_daily.py te avisa de que la sesión ha caducado.
    - Amazon suele forzar reautenticación cada cierto tiempo; es normal
      tener que repetir este paso de vez en cuando.
"""

from pathlib import Path
from playwright.sync_api import sync_playwright

AUTH_DIR = Path(__file__).resolve().parent.parent / ".auth"
SESSION_FILE = AUTH_DIR / "session.json"
START_URL = "https://advertising.amazon.es/campaign-manager/all-campaigns"


def main():
    AUTH_DIR.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(START_URL)

        print("\n--- ACCIÓN REQUERIDA ---")
        print("1. Inicia sesión en la ventana de Chrome que se ha abierto.")
        print("2. Navega hasta que veas la lista de campañas de FreshFinder.")
        print("3. Vuelve aquí y pulsa Enter para guardar la sesión.\n")
        input("Pulsa Enter cuando hayas iniciado sesión correctamente... ")

        context.storage_state(path=str(SESSION_FILE))
        print(f"\nSesión guardada en: {SESSION_FILE}")
        print("Ya puedes cerrar esta ventana. run_daily.py la usará a partir de ahora.")

        browser.close()


if __name__ == "__main__":
    main()
