# FreshFinder — Optimizador de Amazon Ads

Ver `CLAUDE.md` para el diseño completo. Esto es el "cómo lo pongo en marcha".

## 0. Requisitos

- Python 3.10+
- Una cuenta de Amazon Ads con acceso a FreshFinder (la tuya)
- Una API key de Anthropic propia, desde [console.anthropic.com](https://console.anthropic.com) (distinta de tu acceso a Claude en el chat o en Claude Code) — la usa `keyword_generator.py` para inventar ideas de keywords nuevas. Tiene coste propio de uso de API, separado de cualquier suscripción de Claude.

## 1. Instalar dependencias

```bash
cd freshfinder-ads-agent
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

Configura tu API key de Anthropic (para `keyword_generator.py`):
```bash
export ANTHROPIC_API_KEY=sk-ant-...   # Windows: set ANTHROPIC_API_KEY=sk-ant-...
```

## 2. Capturar tu sesión (una vez, a mano)

```bash
python src/capture_session.py
```

Se abrirá una ventana de Chrome. Inicia sesión tú mismo en Amazon Ads
(usuario, contraseña, verificación en dos pasos si la tienes activada).
Cuando veas la lista de campañas de FreshFinder, vuelve a la terminal y
pulsa Enter. Esto guarda `.auth/session.json` — el agente lo reutilizará
sin volver a pedirte credenciales.

**Repite este paso cada vez que `run_daily.py` te avise de que la sesión
ha caducado.**

## 3. ⚠️ Antes de usarlo con dinero real: fijar los selectores

`browser_agent.py` tiene dos funciones sin terminar a propósito:
`get_keyword_performance()` y `update_bid()`. Los selectores exactos de
la tabla de keywords y del campo de puja dependen de la estructura real
del HTML de tu cuenta, que cambia con el tiempo y que yo no puedo fijar
a ciegas sin verlo en directo.

Cómo completarlos:
1. Ejecuta `python src/run_daily.py` una vez cambiando `headless=True`
   por `headless=False` en `BrowserAgent(...)` — así ves el navegador.
2. Con el navegador abierto sobre una campaña real, botón derecho >
   Inspeccionar sobre la tabla de keywords y sobre el campo de puja.
3. Copia los selectores reales (data-testid, clases, etc.) a
   `browser_agent.py`, sustituyendo los `TODO` y el `NotImplementedError`.

Dile a Claude Code "ayúdame a terminar browser_agent.py mirando este HTML"
y pégale el HTML de la tabla — con eso puede escribir el scraper exacto.

## 4. Probar en modo lectura primero

Antes de dejar que aplique cambios reales, comenta las líneas de
`process_keyword()` en `run_daily.py` que llaman a `agent.update_bid(...)`
y ejecuta el script. Debe imprimir qué haría, sin tocar nada. Compara esas
decisiones contra lo que ves tú mismo en la consola de Amazon Ads.

## 5. Programarlo para que corra solo cada día

**Mac/Linux (cron):**
```bash
crontab -e
# Añade (ejecuta cada día a las 9:00):
0 9 * * * cd /ruta/a/freshfinder-ads-agent && venv/bin/python src/run_daily.py >> logs/run.log 2>&1
```

**Windows (Task Scheduler):**
Crea una tarea que ejecute `venv\Scripts\python.exe src\run_daily.py`
diariamente, con el directorio de trabajo en la carpeta del proyecto.

## 6. Revisar el histórico

`logs/decisions.jsonl` — una línea por cambio aplicado. Ábrelo con
cualquier editor de texto, o pídele a Claude que te lo resuma.
