---
name: revision-semanal
description: Revisión semanal de las campañas de Amazon Ads de FreshFinder a partir de la hoja masiva descargada por Juan — analiza cada keyword/ASIN con las reglas acordadas, actualiza la memoria de seguimiento, genera un bulk de cambios (pujas, pausas, negativas) y un informe. Úsala en la tarea programada de cada lunes o cuando Juan diga "revisa los ads", "revisión semanal" o suba una descarga nueva de Operaciones en bloque.
---

# Revisión semanal de Amazon Ads

**Tú no tocas la cuenta.** Solo lees lo que Juan sube y le devuelves archivos. Él decide y sube el bulk.
Todo en español, claro, sin jerga. Rama de trabajo: `claude/eager-pascal-g76q2i` (hasta que se fusione a `main`).

## 1. Buscar los datos de la semana

```bash
git fetch origin && git checkout claude/eager-pascal-g76q2i && git merge --no-edit origin/main
ls -t datos/ 2>/dev/null
```

Entrada esperada (la sube Juan a `datos/`):
- **Preferida:** la hoja masiva descargada de Amazon Ads → Operaciones en bloque → "Crear hoja de cálculo para descargar" (Sponsored Products, rango **desde la creación de las campañas hasta hoy**, incluyendo campañas en pausa). Trae IDs y métricas (impresiones, clics, gasto, ventas, pedidos, ACOS).
- **Alternativa:** exports de "Segmentación" de cada campaña (CSV/XLSX) — sin IDs, así que el bulk de cambios no se podrá generar; solo informe + memoria.

Si **no hay ningún archivo nuevo** desde la última revisión (compara con `resultados/revision_*.md`): no inventes nada. Escribe `resultados/revision_<hoy>.md` con "No hay datos nuevos: sube la hoja masiva descargada a datos/" y termina (sin commit si no cambió nada más que eso: sí haz commit del aviso).

Antes de analizar, abre el archivo y **mira las cabeceras reales** (español): no supongas nombres de columna. Localiza por nombre: Entidad, Operación, ID de campaña/grupo/palabra clave/segmentación, Nombre de campaña, Estado, Puja, Texto de palabra clave, Tipo de coincidencia, Fórmula de segmentación, Impresiones, Clics, Gasto/Coste, Ventas, Pedidos/Compras, ACOS.

## 2. Comprobaciones de seguridad (paran la revisión)

- Todas las campañas en pausa sin que Juan lo pidiera, 0 impresiones en todo, o señales de problema de cuenta → **no propongas cambios de puja**; el informe dice qué has visto y que revise Seller Central (saldo, Buy Box, stock). CLAUDE.md: nunca "reactivar" por iniciativa propia.
- Gasto del mes proyectado (gasto del mes / días transcurridos × días del mes) ≥ 90 % del tope de `CLAUDE.md` (hoy 630 €) → **solo bajadas y pausas**.

## 3. Reglas de decisión (acordadas con Juan — `marketingV2.md` §5)

Por cada keyword / ASIN activo de las campañas V2 y de pruebas:

| Situación | Acción |
|---|---|
| < 10 clics | No tocar (esperar) |
| ≥ 15 clics y 0 ventas | **Pausar** (stop-loss) |
| Puja ya en el mínimo (original −50 %), ≥ 20 clics y ACOS > 50 % | **Pausar** |
| ACOS < 30 % | Subir 10–25 %, sin pasar de la original +50 % ni de la puja máx. rentable (conversión × ticket medio × 35 %) |
| ACOS 30–35 % | No tocar |
| ACOS 35–50 % | Bajar 10–25 %, sin bajar de la original −50 % |
| ACOS > 50 % | Bajar 25–50 %, sin bajar de la original −50 % |
| Keyword que ya pasó 2 veces por stop-loss | No reactivar; marcar para Juan |

- **Puja original** = la de creación (hoja "Segmentación" de la memoria, columna "Puja original"). El rango ±50 % es sobre ella, no acumulativo.
- **Atribución de 7 días:** las ventas de los últimos 7 días aún pueden llegar. Si una keyword solo tiene clics recientes, sé prudente (preferir "esperar" a "pausar" salvo stop-loss claro).
- No cambies una keyword que ya cambiaste hace < 7 días (mira los tickets): su efecto aún no se puede medir.
- **Pruebas → graduación:** una prueba (ASIN o keyword) con ≥ 2 ventas y ACOS ≤ 35 % se propone para pasar a la campaña principal (keywords en Exacta con su CPC medio). Proponer, no ejecutar.
- Si hay informe de **términos de búsqueda** en `datos/`: términos con ≥ 10 clics y 0 ventas → negativa exacta; con ventas, ACOS ≤ 35 % y que no son keyword → keyword nueva en Exacta (máx. 3 por semana).
- Nunca subir presupuestos ni crear campañas: eso lo decide Juan (CLAUDE.md, regla 4). Si ves que una campaña se queda sin presupuesto a diario y rinde bien, **recomiéndalo** en el informe.

## 4. Salidas

1. **`resultados/bulk_cambios_<AAAA-MM-DD>.xlsx`** — sobre `plantillas/AdvertisingBulksheetTemplate-seller.xlsx`, hoja "Camp. de Sponsored Products", con los IDs reales del archivo descargado:
   - Cambio de puja: Entidad "Palabra clave" (o "Segmentación por productos"), Operación de actualización, IDs de campaña/grupo/palabra clave, nueva Puja.
   - Pausa: igual, Estado "En pausa".
   - Negativa nueva: Entidad "Palabra clave negativa", Operación "Crear", Tipo "Frase negativa"/"Exacta negativa".
   - ✔ Valores ya aceptados por Amazon: ver la tabla del Paso 5 de `.claude/skills/crear-campana/SKILL.md`. ⚠ El valor de la **Operación de actualización** ("Actualizar") aún no está confirmado: la primera vez díselo a Juan; si Amazon lo rechaza, no se aplica nada (rechaza el archivo entero) y se corrige con su informe. Apunta el resultado en esa tabla.
   - Si no hay cambios que proponer, no generes bulk.
2. **Memoria** — en la memoria que corresponda (`resultados/memoria.xlsx`, `resultados/memoria_<producto>.xlsx`): **solo añadir**, nunca borrar lo que Juan rellenó.
   - "Seguimiento": una fila por keyword con la fecha de la descarga y sus datos acumulados.
   - "Tickets": un ticket nuevo por cada cambio propuesto (Estado "Pendiente de aplicar", Base = acumulado actual, motivo con los números).
   - Recalcula con el script `recalc.py` de la skill `xlsx` (0 errores).
3. **`resultados/revision_<AAAA-MM-DD>.md`** — informe corto:
   - Resumen por campaña: gasto, ventas, ACOS, compras (semana y acumulado) y gasto del mes vs tope.
   - Tabla de cambios propuestos (keyword, antes → después, motivo con números).
   - Veredictos de tickets que ya cumplen 7 días (Mejora / Empeora).
   - Alertas (stop-loss, cuenta, presupuesto) y recomendaciones que solo Juan puede decidir.
   - Qué tiene que hacer Juan: revisar, subir `bulk_cambios_<fecha>.xlsx`, poner "Fecha aplicado" en los tickets.

## 5. Entregar

`git add` + commit en español + `git push -u origin claude/eager-pascal-g76q2i` (reintentar con espera si falla la red). Termina con un resumen de 5–10 líneas (es lo que le llega a Juan como aviso): nº de cambios, lo más importante, y el nombre del bulk a subir.
