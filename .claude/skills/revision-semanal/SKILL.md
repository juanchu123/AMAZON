---
name: revision-semanal
description: Revisión semanal de las campañas de Amazon Ads de FreshFinder. Ejecuta el agente autónomo (agente.py) con la hoja masiva que Juan sube a datos/ (modo sin API), o, si el agente ya corre con la API en el ordenador de Juan, solo resume el documento único. Úsala en la tarea programada de cada lunes o cuando Juan diga "revisa los ads", "revisión semanal" o suba una descarga nueva de Operaciones en bloque.
---

# Revisión semanal de Amazon Ads

Las reglas ya no se aplican a mano: las aplica **`agente.py`** (`AGENTE_AUTONOMO.md`, `CLAUDE.md`). Tu trabajo es ejecutarlo con los datos de la semana, comprobar que todo ha ido bien y contárselo a Juan.
Todo en español, claro, sin jerga. Rama de trabajo: `claude/eager-pascal-g76q2i` (hasta que se fusione a `main`).

**Tú nunca tocas la cuenta de Amazon.** En la nube no hay credenciales de la API: el agente solo lee la hoja masiva y prepara otra con los cambios para que Juan la suba.

## 1. Preparar

```bash
git fetch origin && git checkout claude/eager-pascal-g76q2i && git merge --no-edit origin/main
pip install -q -r requirements.txt
ls -t datos/ resultados/ 2>/dev/null | head -30
```

## 2. ¿Quién lleva la cuenta esta semana?

Abre `resultados/memoria_agente.xlsx`, hoja **Resumen** ("Fuente de datos" y "Fecha").

- Si la última ronda fue con la **API de Amazon Ads** hace menos de 7 días: el agente ya corre solo en el ordenador de Juan. **No lo ejecutes** (duplicarías decisiones): salta al paso 4 y solo resume.
- Si no: sigue con el paso 3.

## 3. Ejecutar el agente con la hoja masiva

Entrada: la **hoja masiva descargada** de Amazon Ads → Operaciones en bloque (Sponsored Products, desde la creación de las campañas hasta hoy, con campañas en pausa), en `datos/`.

Si no hay ninguna descarga más nueva que la última ronda: no inventes nada. Escribe `resultados/revision_<hoy>.md` con "No hay datos nuevos: sube la hoja masiva descargada a datos/", haz commit y termina.

```bash
python agente.py --fuente bulk --bulk "datos/<descarga>.xlsx" --sin-investigacion
echo "salida: $?"      # 0 bien · 2 parado por la cuenta (todo en pausa / problema de pago) · 1 error
python -m pytest tests/ -q   # por si alguien ha tocado el código
```

- Salida 2: la cuenta está parada. Es correcto que no cambie nada: díselo a Juan (revisar Seller Central: saldo, pago, Oferta Destacada, stock). Nunca reactives nada.
- Salida 1: lee el error. Si es de lectura de la descarga (cabeceras distintas), mira las cabeceras reales del archivo y corrige `fuente_bulk.py` (búsqueda por nombre de columna); vuelve a ejecutar. No cambies reglas de negocio para "hacer que pase".
- Si genera `resultados/bulk_cambios_<fecha>.xlsx`: es lo que Juan tiene que subir. ⚠️ El valor "Actualizar" de la columna Operación aún no está confirmado: si Amazon lo rechaza, no se aplica nada (rechaza el archivo entero) y se corrige con su informe de errores (`fuente_bulk.OP_ACTUALIZAR` y la tabla del Paso 5 de la skill `crear-campana`).

## 4. Informe: `resultados/revision_<AAAA-MM-DD>.md`

Sácalo del documento único (`resultados/memoria_agente.xlsx`), no de tu cabeza:

- **Resumen**: gasto del mes, proyectado, tope del día, nº de cambios.
- **Campañas**: fondo (probado / experimentación), presupuesto actual → objetivo, ACOS 30 días.
- **Cambios de la semana** (hoja Tickets): tabla con campaña, keyword, antes → después, motivo y estado (confirmado / enviado en hoja masiva / fallido).
- **Veredictos** que han madurado esta semana (mejora / empeora).
- **Avisos** (hoja Alertas) y keywords con "Requiere revisión de Juan".
- **Qué tiene que hacer Juan**: subir `bulk_cambios_<fecha>.xlsx` (si lo hay), revisar las marcadas, confirmar ASIN en la hoja Competencia, y la próxima semana volver a subir la descarga (así se confirman los cambios).

## 5. Entregar

`git add resultados/ datos/` + commit en español + `git push -u origin claude/eager-pascal-g76q2i` (reintentar con espera si falla la red). El documento único **se commitea siempre**: es la memoria del agente. Termina con un resumen de 5–10 líneas (es lo que le llega a Juan como aviso): nº de cambios, lo más importante y el nombre de la hoja masiva a subir.
