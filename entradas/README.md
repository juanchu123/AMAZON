# entradas/

Una carpeta por día con el nombre `AAAA-MM-DD` (por ejemplo `entradas/2026-09-28/`). Dentro:

- **La hoja masiva descargada** de Amazon Ads (Operaciones en bloque → Sponsored Products, desde la creación de las campañas hasta hoy, con campañas en pausa). Cualquier nombre `.xlsx`.
- **`Documento_investigacion_keywords.xlsx`** (lo genera Cowork): las frases investigadas por producto. El agente las importa a la hoja "Investigación" de la memoria; solo entran en campaña si pasan su filtro (ACOS predicho ≤ 30 %).

`python agente.py` usa la carpeta de entrada más reciente y deja el resultado en `salidas/<hoy>/`: la memoria actualizada (`memoria_agente.xlsx`), la hoja de cambios para subir a Amazon (`bulk_cambios_<fecha>.xlsx`) y los correos que no se pudieron enviar. La memoria de cada día parte de la del día anterior más reciente.
