# entradas/

Una carpeta por día con el nombre `AAAA-MM-DD` (por ejemplo `entradas/2026-09-28/`). Dentro:

- **La hoja masiva descargada** de Amazon Ads (Operaciones en bloque → Sponsored Products, desde la creación de las campañas hasta hoy, con campañas en pausa). Cualquier nombre `.xlsx`.
- **`investigacion_<día>.csv`** (lo genera Cowork): cabecera exacta `ASIN;Palabra clave;Motivo;Fuente;Volumen;Puja sugerida (€)`, separador `;`, UTF-8. El agente añade a la hoja "Investigación" de la memoria las frases que el producto aún no tenía (nunca se repiten); solo entran en campaña si pasan su filtro (ACOS predicho ≤ 30 %). Un día puede traer solo la investigación: se importa en la siguiente ejecución.

`python agente.py` usa la hoja masiva de la carpeta más reciente y deja el resultado en `salidas/<hoy>/`: la memoria actualizada (`memoria_agente.xlsx`), la hoja de cambios para subir a Amazon (`bulk_cambios_<fecha>.xlsx`), `Documento_investigacion_keywords.xlsx` (todas las frases puntuadas) y los correos que no se pudieron enviar. La memoria de cada día parte de la del día anterior más reciente.

Antes de investigar: `python investigacion.py --ya-vistas` → `salidas/<hoy>/frases_ya_vistas.csv`, lo que ya no hace falta buscar.
