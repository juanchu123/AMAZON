---
name: crear-envio-fba
description: Crear un envío a Amazon FBA (Send to Amazon) para FreshFinder rellenando los dos Excel que pide Seller Central — la plantilla de envío (SKUs y unidades) y el archivo de contenido de cajas por grupo de embalaje (unidades por caja, peso y medidas). Úsalo cuando Juan quiera mandar stock a Amazon, preparar un envío, rellenar la plantilla ManifestFileUpload o el Excel de "Pack Group", o dar la información de cajas de un envío.
---

# Crear envío FBA (FreshFinder)

Un envío en "Send to Amazon" pide **dos Excel en dos momentos distintos**:

| Paso | Archivo que descarga Juan | Qué lleva | Script |
|---|---|---|---|
| 1 | `ManifestFileUpload_Template_MPL.xlsx` (plantilla de envío) | SKU + unidades (y, según cómo se descargó, datos de caja) | `scripts/rellenar_plantilla_envio.py` |
| 2 | `AAAA-MM-DD_hh-mm-ss_<id>.xlsx` con pestañas `Pack Group - N` | Qué unidades van en cada caja, peso y medidas de cada caja | `scripts/rellenar_contenido_cajas.py` |

El paso 2 **no existe hasta que Juan sube el paso 1**: Amazon reparte el envío en grupos de embalaje (a veces 3 grupos para solo 40 uds) y genera ese segundo archivo. No lo anticipes: pide el archivo cuando toque.

## Reglas que no se saltan

- **Tú preparas los archivos; Juan los sube.** Nunca subas envíos, aceptes presupuestos de transporte, confirmes transportistas ni compres etiquetas en Seller Central.
- **No inventes datos.** Si falta algo, pregunta. Solo si Juan dice explícitamente que inventes/estimes un dato (p. ej. peso y medidas), hazlo y márcalo como **estimado** en el resumen, recordándole que lo sustituya por el real antes de subir.
- **No toques la estructura de los Excel** (cabeceras, instrucciones, pestañas, fórmulas, protección). Los scripts solo escriben en celdas de datos; no edites estos archivos con otra herramienta que los reescriba entera.
- **Estado de la cuenta:** la cuenta ha estado "en riesgo" (DAC7/IVA). Antes de preparar nada, confirma con Juan que la cuenta permite crear envíos.
- No cambies precios, anuncios ni campañas: eso es de otros agentes.

## Catálogo

| SKU | ASIN | Producto |
|---|---|---|
| 5E-I8NY-S191 | B0DHYBY6MS | Soporte móvil coche rejilla 360° con clip |
| O8-5W7J-DSK1 | B0DCZS1NR6 | Soporte móvil coche con pinza |
| O4-JMKY-X1L2 | B0DSV986XY | Soporte móvil coche con ventosa 360° |
| 9E-ZZM5-X8ZE | B0F746MFPQ | Soporte móvil coche 3 en 1 |
| NN-8FIP-9ZZT | B0CPHXXHRQ | Peluche Pou (Meokro) |

FNSKU conocidos: 5E-I8NY-S191 → `X00253XINT`, O8-5W7J-DSK1 → `X0023O0ATF` (el Excel del paso 2 los trae todos).
Si aparece un SKU nuevo, añádelo a esta tabla y a `CATALOGO` en `scripts/common.py`.

## Paso 1 — Plantilla de envío

### 1a. Pregunta a Juan (en un solo mensaje, lo que no te haya dicho ya)

1. ¿La cuenta permite crear envíos ahora mismo?
2. **Qué SKUs y cuántas unidades de cada uno.** Si da ASIN o FNSKU, tradúcelos a SKU con el catálogo y confírmalo.
3. ¿Tiene ese stock disponible en origen?
4. **Quién prepara** (embolsado, protección) y **quién etiqueta** (etiqueta FNSKU en cada unidad): *Seller* (vosotros) o *Amazon* (servicio de pago por unidad). Si no necesita preparación, es *Seller*.
5. Que te pase la plantilla descargada de Seller Central (Send to Amazon → crear envío → descargar plantilla).

Caducidad y lote no aplican a este catálogo: no los preguntes salvo que la plantilla traiga esas columnas.

### 1b. Rellena

```bash
S=.claude/skills/crear-envio-fba/scripts
python $S/rellenar_plantilla_envio.py PLANTILLA.xlsx --leer     # qué columnas trae y owners por defecto
```

Escribe una spec JSON en el scratchpad y genera el archivo:

```json
{
  "prep_owner_por_defecto": "Seller",
  "labeling_owner_por_defecto": "Seller",
  "lineas": [
    {"sku": "5E-I8NY-S191", "cantidad": 20},
    {"sku": "O8-5W7J-DSK1", "cantidad": 20}
  ]
}
```

```bash
python $S/rellenar_plantilla_envio.py PLANTILLA.xlsx spec_paso1.json envios/Envio_FBA_<AAAA-MM-DD>.xlsx
```

- Si `--leer` dice que la plantilla **no** lleva datos de caja (lo normal), las cajas se dan en el paso 2: no las pidas todavía.
- Si la plantilla **sí** trae columnas de caja (`Units per box`, `Number of boxes`, `Box length/width/height`, `Box weight`), añade por línea `unidades_por_caja`, `numero_cajas` y `caja: {largo, ancho, alto, peso}`, preguntando antes lo del paso 2a. El script exige que `unidades_por_caja × numero_cajas = cantidad`.
- El script valida SKUs, cantidades y límites de caja, y **no genera nada si hay errores**: corrige preguntando, no forzando.

### 1c. Entrega

Envía el archivo a Juan (SendUserFile) con un resumen corto: SKUs, unidades, quién prepara y quién etiqueta, y lo pendiente. Si el etiquetado es *Seller*, recuérdale el FNSKU que va en cada unidad. Dile que, al subirlo, Seller Central le dará el Excel de contenido de cajas y que te lo pase.

## Paso 2 — Contenido de cajas (Pack Groups)

### 2a. Lee el archivo y enseña a Juan el reparto

```bash
python $S/rellenar_contenido_cajas.py ARCHIVO_PACK_GROUPS.xlsx --leer
```

Devuelve, por grupo: SKUs, unidades que espera Amazon y cajas estimadas. Enséñaselo a Juan en una tabla y pregunta:

1. **Cuántas cajas por grupo y qué unidades van en cada una** (puede mezclar SKUs en una caja; la suma por SKU tiene que dar exactamente lo que espera Amazon en ese grupo).
2. **Peso de cada caja en kg** (ya cerrada, con relleno).
3. **Medidas de cada caja en cm** (ancho × largo × alto).
4. Si no las tiene: ¿quiere que las estimes? Solo con un "sí" explícito. Referencia para estimar un soporte de móvil en su caja: ~15×10×6 cm y 100–150 g por unidad, más cartón y relleno.

Si Amazon ha partido un envío pequeño en varios grupos (p. ej. cajas de 3–4 uds), avísale de que eso suele encarecer mucho el coste por unidad y que compare costes en Seller Central antes de aceptar.

### 2b. Rellena

```json
{
  "grupos": {
    "1": {"cajas": [
      {"unidades": {"5E-I8NY-S191": 2, "O8-5W7J-DSK1": 2}, "peso": 0.9, "ancho": 20, "largo": 30, "alto": 15}
    ]},
    "2": {"cajas": [
      {"unidades": {"5E-I8NY-S191": 2, "O8-5W7J-DSK1": 1}, "peso": 0.8, "ancho": 20, "largo": 30, "alto": 15}
    ]},
    "3": {"cajas": [
      {"unidades": {"5E-I8NY-S191": 16}, "peso": 2.6, "ancho": 30, "largo": 40, "alto": 20},
      {"unidades": {"O8-5W7J-DSK1": 17}, "peso": 2.75, "ancho": 30, "largo": 40, "alto": 20}
    ]}
  }
}
```

```bash
python $S/rellenar_contenido_cajas.py ARCHIVO_PACK_GROUPS.xlsx spec_paso2.json envios/Envio_FBA_<AAAA-MM-DD>_cajas.xlsx
```

El script cambia el "Total box count" de cada grupo al número de cajas de la spec y escribe unidades, peso y medidas por caja. Edita el XML directamente para no romper la protección ni las fórmulas de Amazon. Valida que:
- estén todos los grupos del archivo y ningún grupo que no exista;
- la suma por SKU en cada grupo = unidades esperadas por Amazon;
- cada caja tenga peso y las tres medidas;
- no haya más de 11 cajas por grupo (límite de la plantilla), ni más de ±10 respecto a las estimadas por Amazon.

### 2c. Entrega

Envía el archivo con una tabla por caja (`P<grupo> - B<caja>`: unidades por SKU, peso, medidas), el total de cajas, unidades y kg, y qué datos son **estimados**.

## Límites de caja (Amazon EU, envío de paquetes pequeños)

Los comprueban los scripts (`scripts/common.py`):
- Peso máximo por caja: **23 kg**. Por encima de **15 kg**, la caja necesita etiqueta "Heavy package" (aviso).
- Ningún lado de más de **63,5 cm**.

Si una caja se pasa, propón repartir en más cajas; no lo cambies sin decírselo a Juan. Si Amazon actualiza estos límites en la guía de Seller Central, cambia las constantes.

## Archivos

- Salidas en `envios/`: `Envio_FBA_<AAAA-MM-DD>.xlsx` (paso 1) y `Envio_FBA_<AAAA-MM-DD>_cajas.xlsx` (paso 2). Las specs JSON van al scratchpad, no al repo.
- Tras generar, haz commit y push en la rama de trabajo.
