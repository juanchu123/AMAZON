---
name: crear-campana
description: Crear una campaña nueva de Amazon Ads (Sponsored Products) para un producto de FreshFinder, con keywords históricas + especiales del modelo de ML, negativas, memoria de seguimiento (Excel con tickets) y hoja masiva (bulk) lista para subir. Úsala cuando Juan diga "crea una campaña para <producto>", "/crear-campana <producto>", "haz como la de la pinza para X" o pida añadir un producto nuevo a las campañas.
---

# Crear campaña para un producto

Juan dice de qué producto hablamos; tú dejas preparados **dos archivos** para que él solo tenga que subir y activar:

1. **Memoria** (`resultados/memoria_<producto>.xlsx`): configuración, segmentación con las columnas de Amazon, seguimiento cada 3 días, un ticket por cambio e histórico.
2. **Bulk** (`resultados/bulk_AAAA-MM-DD.xlsx`): la hoja masiva sobre la plantilla oficial (`plantillas/AdvertisingBulksheetTemplate-seller.xlsx`) para Amazon Ads → Operaciones en bloque. **Todo se crea EN PAUSA.**

Todo lo genera `crear_memoria.py` a partir de `keyword_ml.py` (perfiles de producto + modelo) y del histórico `FreshFinder_Amazon_Ads_historico.xlsx`. No hay que escribir Excel a mano.

Habla con Juan en español, claro y sin jerga. Nunca actives campañas ni toques la cuenta: tú solo generas archivos.

## Paso 0 — Preguntar antes de hacer nada (CLAUDE.md lo exige)

Pregunta en UN solo mensaje lo que falte (usa lo que ya haya dicho):

1. **Producto**: nombre o ASIN. Si no lo sabe, lista los productos de la hoja "Anuncios" del histórico (ASIN, SKU, nombre, gasto, compras).
2. **Presupuesto diario** de la campaña (hasta ahora: 7 €/día por campaña).
3. **Tope mensual**: suma de TODOS los presupuestos diarios activos × 30. Si pasa del "Presupuesto máximo" de `CLAUDE.md` (hoy 630 €/mes), **para y pregunta** si sube el tope. Solo Juan puede cambiarlo; si lo sube, actualiza `CLAUDE.md`, `safety.py` (`MONTHLY_BUDGET_CAP_EUR`), `marketingV2.md` y `CARTERA_MENSUAL` en `crear_memoria.py`.
4. **¿Campaña de pruebas con ASIN de la competencia?** (como "Pinza - Pruebas"). Si sí, necesitas ASIN competidores: búscalos con WebSearch (amazon.es suele estar bloqueado para WebFetch) y márcalos "a verificar por Juan".
5. **Estado de la cuenta**: ¿se resolvió el saldo de Seller Central? (si no, las campañas no servirán anuncios aunque estén activas).

## Paso 1 — Datos

```bash
git fetch origin && git merge origin/main   # por si Juan subió un histórico nuevo
```

- Comprueba que el producto está en `FreshFinder_Amazon_Ads_historico.xlsx` (hojas "Anuncios" y "Keywords"). Si no hay histórico, el modelo no puede aprender: díselo y ofrece una campaña solo con especiales + pujas conservadoras (0,30 €), o pedirle que exporte su histórico (skill `amazon-ads-export-historico`).
- Solo cuentan los grupos donde el producto tiene **≥ 90 %** del gasto (`CUOTA_MIN_GRUPO`).

## Paso 2 — Perfil del producto en `keyword_ml.py`

Si el producto no está en `PERFILES`, añade uno (copia la estructura de "pinza"/"rejilla"):

| Campo | Qué poner |
|---|---|
| `asin` | ASIN del producto |
| `especificas` | palabras (normalizadas, sin acentos) que identifican ESTE producto y no un producto cualquiera del sector (p. ej. `{"pinza"}`, `{"rejilla","ventilacion","aire","gancho","clip"}`) |
| `montaje`, `conector` | la palabra clave del tipo de producto y cómo se une: "soporte móvil para coche **con pinza**", "… **para rejilla**" |
| `lugares`, `atributos` | modificadores; solo se usan si aparecen en el título o en sus keywords reales (no inventar características que no tiene la ficha) |
| `extras` | plantillas de frases propias del producto con `{M}` (montaje) y `{l}` (lugar) |

Si el producto no es un soporte de móvil, revisa también `vocabulario()` (cabezas "soporte/sujeta/porta + móvil/teléfono") y adapta las cabezas al producto en su perfil, sin romper los existentes.

Ejecuta y revisa:
```bash
python keyword_ml.py --producto <perfil> --top 15
python keyword_ml.py            # la pinza debe dar exactamente lo mismo que antes
```
Cuenta a Juan la línea "Validación": si mejora < 5 % sobre la media, avisa de que las especiales van casi a ciegas.

## Paso 3 — Campaña en `crear_memoria.py` (`CAMPANAS`)

Añade un diccionario como los existentes:

- `nombre` y `grupo`: "<Producto> - Principal V2" (y "<Producto> - Pruebas" / "Pruebas - Competencia" si hay pruebas).
- `perfil`, `sku` (el SKU con más gasto en la hoja "Anuncios"), `tipo` ("Palabras clave" o "Productos"), `puja_grupo` (0,40 principal / 0,30 pruebas), `presupuesto` si no es el general.
- `n_hist: 5`, `n_total: 10`, `especiales: None` (= las mejores del modelo) o una lista fija si Juan elige.
- `negativas`: `NEG_COMUNES` + las palabras específicas de los OTROS productos con campaña (la pinza lleva "rejilla"; la rejilla lleva "pinza" y "salpicadero"). Revisa que ninguna negativa bloquee una keyword propia.
- Pruebas: `asins` [(ASIN, motivo)], `categoria` (se hace a mano) y `negativos_producto` [(ASIN propio, motivo)] (a mano).

Reglas que ya aplica el código (no las rompas):
- Históricas = mejor ACOS con ≥ 1 compra, sumando la misma keyword+coincidencia de todos los grupos; **nunca Amplia genérica** (sin palabra específica) ni keywords con palabras de otro producto.
- Puja histórica según la tabla de `marketingV2.md` §5.1, sin pasar la puja máx. rentable; con < 10 clics se usa la conversión media del producto.
- Especiales en **Frase**, puja = puja máx. rentable del modelo (ACOS 35 %); se descartan si no llegan a la puja recomendada mínima.

## Paso 4 — Generar (sin pisar nada)

```bash
python crear_memoria.py --fecha $(date +%F) --solo "<Campaña 1>,<Campaña 2>" --memoria resultados/memoria_<producto>.xlsx
```

- **`--solo` es obligatorio** al añadir campañas: sin él el bulk vuelve a crear las campañas que ya existen → duplicadas en Amazon.
- **Nunca sobrescribas `resultados/memoria.xlsx`** ni otra memoria que Juan esté rellenando (tickets con "Fecha aplicado", filas en "Seguimiento"). Si Juan quiere una sola memoria con todo, primero descarga la suya de GitHub y copia sus datos; si no, memoria separada por producto.
- Si ya existe un `bulk_<hoy>.xlsx` de otra cosa, renombra el anterior o usa otra fecha, no lo pises sin avisar.

Recalcula y verifica (skill `xlsx`):
```bash
python <skill xlsx>/scripts/recalc.py resultados/memoria_<producto>.xlsx 180   # total_errors debe ser 0
```
Si LibreOffice falla: `apt-get install -y libreoffice-calc`.
Comprueba con una copia en el scratchpad: añade una foto falsa en "Seguimiento" y mira que "Segmentación" y el "Veredicto" del ticket reaccionan (stop-loss con ≥ 15 clics sin venta; "Esperando atribución (7 días)").

## Paso 5 — Hoja masiva: valores comprobados con Amazon

Informe real de Amazon (26/09/2026). Si Amazon rechaza una fila, **rechaza el archivo entero** (no aplica nada): es seguro reintentar.

| Columna / entidad | ✔ Aceptado | ✘ Rechazado |
|---|---|---|
| Entidad | Campaña, Grupo de anuncios, Anuncio de producto, Palabra clave, Palabra clave negativa, Segmentación por productos | Segmentación por productos negativa (→ a mano) |
| Operación | Crear | |
| Tipo de segmentación | Manual | |
| Tipo de coincidencia | Amplia, Frase, Exacta, Frase negativa | |
| Estado | *pendiente de confirmar:* Activado / En pausa | Habilitado, Pausado |
| Estrategia de pujas | vacía (por defecto en campañas nuevas: solo reducir) | "Pujas dinámicas: solo reducir" |

Cuando Juan pase un informe de errores nuevo, actualiza esta tabla y los comentarios de `crear_memoria.py` (`BULK_ACTIVO`, `BULK_PAUSA`, `BULK_ESTRATEGIA`).

Siempre a mano (díselo a Juan): cartera con límite mensual, meter la campaña en la cartera, categoría con filtros, producto negativo (su propia ficha), añadir las negativas nuevas a campañas que YA existen (p. ej. el nombre del producto nuevo como negativa en las otras).

## Paso 6 — Entregar

1. Actualiza `marketingV2.md` §5.5 (tabla de campañas y presupuesto).
2. `git add` + commit (mensaje en español) + push a la rama de trabajo.
3. Envía a Juan la memoria y el bulk (SendUserFile).
4. Resumen corto: tabla de las 10 keywords (origen, coincidencia, puja), negativas, presupuesto y tope mensual, qué hay que hacer a mano, y el orden: subir bulk → revisar informe → cartera → pasos manuales → verificar ASIN → activar → poner "Fecha aplicado" en los tickets.
