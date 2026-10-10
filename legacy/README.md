# legacy/ — el sistema anterior (ya no se usa)

Retirado el 27/09/2026 al implementar el agente autónomo (`AGENTE_AUTONOMO.md` §6, paso 10). Se guarda como referencia; **no se ejecuta** y no se mantiene.

| Archivo | Qué era | Por qué se retira |
|---|---|---|
| `browser_agent.py`, `capture_session.py` | Leer y cambiar la cuenta con un navegador automático (Playwright) y una sesión guardada | Sustituido por la Amazon Ads API oficial (`ads_api.py`) y, sin API, por la hoja masiva (`fuente_bulk.py`). Nunca llegó a funcionar (7 `NotImplementedError`) |
| `ai_marketing_agent.py`, `keyword_generator.py` | Un LLM decidía pujas e inventaba keywords experimentales | "Camino A": el dinero lo deciden reglas fijas. El LLM solo investiga (`investigacion.py`) |
| `run_daily.py`, `marketing_agent.py`, `commands.py` | Orquestador y contrato entre agente y navegador | Sustituidos por `agente.py` y `modelo.py` |
| `analyzer.py`, `safety.py`, `learner.py` | Reglas anteriores (±20 % por cambio, 24 h, 3 keywords/día, fondo de 20 €/mes, log `decisions.jsonl`) | Reescritos con las reglas nuevas en la raíz. El `learner.py` antiguo además buscaba el log fuera del repo |
| `import_historical_data.py` | Importar exports CSV a `logs/historical_keywords.json` para el LLM | El histórico ya se lee del Excel (`prediccion.py`, hoja Histórico del documento único) |

Los imports entre estos archivos apuntan unos a otros por su nombre antiguo: si algún día hiciera falta ejecutar algo de aquí, hay que hacerlo desde esta carpeta.
