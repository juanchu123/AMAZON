# Marketing V2 — FreshFinder en Amazon Ads

Guía para poner en marcha y usar el sistema. El diseño técnico completo está en `CLAUDE.md`. Este documento explica **para qué sirve, cómo pensar y qué ejecutar**.

---

## 1. Objetivo

1. **Mejorar los anuncios**: que salgan en las búsquedas de gente que de verdad compra tu producto, y no en las de curiosos.
2. **Optimizar el beneficio, no las ventas.** Vender 3 unidades en vez de 1 no sirve si cada clic cuesta 2€. Lo que manda es **cuánto te cuesta en publicidad cada venta** y **cuánto te queda limpio después**.
3. **Actuar como un experto en PPC**, con criterio y basándose en datos: subir lo que funciona, cortar rápido lo que no, probar ideas nuevas con poco dinero y aprender de cada prueba.

---

## 2. Las claves para pensar como un experto

### 2.1 Las métricas que importan

| Métrica | Fórmula | Qué te dice |
|---|---|---|
| **ACOS** | gasto en ads ÷ ventas por ads | Qué parte de cada euro vendido se va en publicidad. **Métrica principal.** |
| **Gasto por venta** | gasto ÷ nº de compras | Cuánto pagas en ads para conseguir una venta |
| **Compra por clic** (conversión) | compras ÷ clics | Lo bien que encaja la búsqueda con tu producto. **Depende de la palabra.** |
| **CPC** | gasto ÷ clics | Lo que pagas por clic. **Depende sobre todo de tu puja**, no de la palabra. |
| **Beneficio neto por venta** | precio − coste del producto − comisiones Amazon/FBA − gasto por venta | Lo que realmente ganas |

### 2.2 El ACOS de equilibrio

```
margen antes de ads = precio − coste del producto − comisiones de Amazon
ACOS de equilibrio  = margen antes de ads ÷ precio
```

- ACOS **por debajo** del de equilibrio → ganas dinero con cada venta.
- ACOS **por encima** → pierdes dinero con cada venta, aunque "vendas mucho".

El objetivo actual es un **ACOS del 30-35%**. Para confirmar que ese rango da beneficio, hace falta saber el coste de cada producto y las comisiones de Amazon. **Pendiente de que Juan lo facilite.**

### 2.3 La puja la decides tú; la palabra decide la conversión

- En la subasta de Amazon pagas lo justo para ganar al siguiente anunciante, **nunca más que tu puja** (salvo ajustes de puja activados, como puja dinámica o recargo por "parte superior de búsqueda").
- Lo que depende de la palabra es **cuántos clics hacen falta para vender**. Por eso la pregunta correcta sobre una keyword es:

```
puja máxima rentable = compra/clic × ticket medio × ACOS objetivo
```

Ejemplo: con una conversión del 11% × 11,24€ × 35% ≈ **0,44€**. Si pujas más de eso, esa palabra no llegará al objetivo aunque venda.

- La **puja recomendada** de Amazon indica la competencia: si tu puja máxima rentable queda muy por debajo, casi no ganarás subastas.

### 2.4 Reglas de oro

1. **No decidir con pocos datos.** Menos de ~10 clics es ruido: dejar madurar.
2. **Pujas: cada 3 días, dentro de ±50% de la puja original** (ver 5.1). Entre revisiones no se toca nada, para que los datos maduren.
3. **Las pruebas van aparte:** en una campaña de pruebas con el **50% del presupuesto** (pedido por Juan el 26/09/2026), nunca mezcladas con lo que ya funciona (ver 5.2).
4. **Stop-loss siempre activos:** lo que gasta sin vender se corta sin esperar (ver 5.3).
5. **Promover lo que ya funciona:** términos de búsqueda reales con ventas y buen ACOS pasan a ser keywords en coincidencia **Exacta**.
6. **Aprender por producto, nunca mezclado.** La misma palabra puede funcionar para la pinza y fallar para la rejilla.
7. **Presupuesto duro de 840€/mes** (antes 100€ y 630€; cambiado por Juan el 26/09/2026). Nunca se supera, aunque los datos "lo justifiquen".
8. **Si todas las campañas aparecen en pausa sin que el sistema las haya pausado** (saldo, suspensión…), no reactivar nada: avisar a Juan.

---

## 3. Qué piezas hay y para qué sirve cada una

| Archivo | Qué hace | Estado |
|---|---|---|
| `keyword_ml.py` | **Machine learning de keywords.** Lee los CSV de Amazon Ads, relaciona palabras con producto, aprende qué palabras venden y **recomienda frases nuevas para probar**. | ✅ Funciona |
| `import_historical_data.py` | Importa el rendimiento histórico (CSV) para que la IA lo tenga en cuenta. | ✅ Funciona |
| `ai_marketing_agent.py` | Claude (vía API) razona cada día con los datos y propone pujas y experimentos. `sanitize_commands()` recorta todo a los límites de seguridad. | ⚠️ Necesita `ANTHROPIC_API_KEY` |
| `keyword_generator.py` | Claude inventa frases nuevas para experimentos. | ⚠️ Necesita `ANTHROPIC_API_KEY` |
| `analyzer.py`, `learner.py`, `safety.py`, `marketing_agent.py`, `commands.py` | Reglas de negocio, memoria de decisiones y límites. | ✅ Código listo |
| `browser_agent.py` | Lee y cambia la cuenta de Amazon Ads con un navegador automático. | ❌ Faltan los selectores (7 `NotImplementedError`) |
| `capture_session.py` | Login manual una sola vez; guarda la sesión. | ✅ Listo para usar |
| `run_daily.py` | Orquesta todo cada día. | ❌ Depende de `browser_agent.py` |

---

## 4. Cómo ejecutarlo

### 4.1 Instalación (una vez)

Hace falta Python 3.10 o superior ([python.org](https://www.python.org); en Windows, marca "Add Python to PATH").

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium       # solo si vas a usar el navegador automático
```

> Nota: en esta rama los `.py` están en la raíz del proyecto, no en `src/`. Los comandos de abajo usan esa ruta.

### 4.2 Recomendar keywords nuevas con machine learning — ✅ se puede usar ya

**Fuente preferida: el Excel consolidado `FreshFinder_Amazon_Ads_historico.xlsx`** (hojas *Anuncios* y *Keywords*, con campaña, grupo e IDs). Si está en la carpeta, `keyword_ml.py` lo usa solo. Las keywords de grupos con varios productos cuentan para un producto solo si éste tiene ≥ 90% del gasto del grupo. Para volver al modo antiguo con CSV sueltos: `python keyword_ml.py --csv`. Los pasos de abajo son para ese modo CSV.

1. En Amazon Ads, exporta de cada grupo de anuncios:
   - la pestaña **Anuncios** → `Sponsored_Products_Ad_*.csv` (trae el producto/ASIN);
   - la pestaña **Segmentación** → `Sponsored_Products_Target_*.csv` (trae las palabras).

   **Usa el mismo rango de fechas en los dos exports.** El programa los empareja porque sus totales (gasto, clics, compras, ventas) coinciden; si las fechas no son las mismas, el archivo se descarta.
2. Deja los CSV en la carpeta del proyecto (o en otra y usa `--datos`).
3. Ejecuta:

```bash
python keyword_ml.py                          # soporte de pinza (por defecto; usa el Excel si está)
python keyword_ml.py --producto rejilla       # soporte de rejilla de ventilación (B0DHYBY6MS)
python keyword_ml.py --excel otro_historico.xlsx
python keyword_ml.py --top 20                 # más recomendaciones
python keyword_ml.py --asin B0DHYBY6MS        # otro producto (p. ej. rejilla)
python keyword_ml.py --datos ./exports        # CSV en otra carpeta
```

4. El resultado queda en:
   - `resultados/palabras_recomendadas_<producto>.csv`: la lista para probar, ordenada. Se abre con Excel.
   - `resultados/informe_<producto>.json`: duplicados, emparejamientos, validación y qué aporta cada palabra.

**Cómo leer la pantalla:**
- *"DESCARTADO …"*: ese CSV no cuadra con ningún otro (duplicado o de otras fechas).
- *"Validación … mejora un X%"*: cuánto acierta el modelo frente a usar la media. Si dice **"NO mejora"**, no te fíes de las cifras.
- *"sin datos (se prueba a ciegas)"*: la frase lleva palabras que nunca se han probado.

**Cómo aprende:** vuelve a entrenar desde cero cada vez que lo ejecutas. Para que mejore:

```
probar las recomendadas → esperar 2-4 semanas → exportar CSV nuevos → volver a ejecutar
```

Sin Python instalado también se puede usar en [Google Colab](https://colab.research.google.com): sube `keyword_ml.py` y los CSV, y ejecuta `!python keyword_ml.py`.

### 4.3 Dar contexto histórico a la IA

```bash
python import_historical_data.py export.csv --producto B0DCZS1NR6 --campana "Nombre de la campaña" --ad-group Pinza
```

### 4.4 Sistema automático diario — ❌ todavía no está listo para usar

En este orden, y sin saltarse ninguno:

1. **Clave de API de Claude** (de [console.anthropic.com](https://console.anthropic.com); tiene coste propio):
   ```bash
   export ANTHROPIC_API_KEY=sk-ant-...     # Windows: set ANTHROPIC_API_KEY=sk-ant-...
   ```
2. **Capturar la sesión de Amazon Ads** (login manual, una vez):
   ```bash
   python capture_session.py
   ```
   Se guarda en `.auth/session.json`. **Nunca debe subirse a GitHub** (ver pendientes).
3. **Completar los selectores de `browser_agent.py`.** Abre el navegador con `headless=False`, inspecciona las tablas reales (clic derecho → Inspeccionar) y pásale el HTML a Claude Code para que escriba el scraper exacto. **No se inventan.**
4. **Primera ejecución solo de lectura**, sin aplicar cambios: comprobar que lee bien campañas, keywords y términos de búsqueda.
   ```bash
   python run_daily.py
   ```
5. **Activar los cambios reales** solo cuando las lecturas coincidan con lo que ves en la consola.
6. **Programarlo una vez al día:**
   - Mac/Linux: `crontab -e` → `0 9 * * * cd /ruta/proyecto && venv/bin/python run_daily.py >> logs/run.log 2>&1`
   - Windows: Programador de tareas → `venv\Scripts\python.exe run_daily.py`, con la carpeta del proyecto como directorio de trabajo.
7. **Revisar** `logs/decisions.jsonl`: una línea por cada cambio aplicado y su resultado.

---

## 5. Rutina manual (mientras el sistema diario no esté listo)

Reglas pedidas por Juan (25/09/2026). Los números marcados como *(propuesto)* están pendientes de su confirmación.

### 5.1 Pujas: revisión cada 3 días

- **Frecuencia:** una revisión cada 3 días. En cada revisión se pueden cambiar **tantas keywords como haga falta**.
- **Rango permitido:** cada puja se mueve siempre **entre −50% y +50% de su puja original**, que es la puja que tenía cuando se empezó a gestionar con este método. Anótala la primera vez.
  - Ejemplo: puja original 0,50€ → rango permitido de **0,25€ a 0,75€**.
  - El rango es sobre la original, no acumulativo: tres subidas seguidas nunca pasan de 0,75€.
- **Qué hacer con cada keyword** (con al menos 10 clics; con menos, no se toca):

| Situación (últimos 7-14 días) | Acción |
|---|---|
| ACOS < 30% | Subir la puja un 10-25%, sin pasar de la original + 50% |
| ACOS 30-35% | No tocar: está en el objetivo |
| ACOS 35-50% | Bajar la puja un 10-25% |
| ACOS > 50% | Bajar la puja un 25-50%, sin bajar de la original − 50% |
| Sin ventas | Ver stop-loss (5.3) |

- **Sube solo si el gasto del mes lo permite.** Si el gasto proyectado del mes se acerca a 840€, solo se permiten bajadas.
- **Por qué cada 3 días y no a diario:** Amazon tarda 24-48h en atribuir ventas a un clic. Con cambios diarios se decidiría con datos incompletos.

### 5.2 Campaña de pruebas (50% del presupuesto)

- **Estructura:** una **campaña propia** "Pinza - Pruebas" (el presupuesto en Amazon es por campaña; solo así el 50% es un límite real), con el grupo "Pruebas - Competencia".
- **Presupuesto: 50% = 50 €/mes** (≈1,67 €/día). La campaña principal se queda con los otros ≈1,67 €/día.
- **Qué se prueba:**
  - **Segmentación por producto (ASIN):** salir en las fichas de soportes de pinza de la competencia (OcioDual B07H996QMD, B0BS1TQJH2, BEENLE B08N4KR6PK, AUTOZOCO B09P3SZB6P). ⚠️ Sacados de búsqueda web: verificar en amazon.es que siguen a la venta y que son más caros o con peores reseñas que el tuyo.
  - **Categoría** "Soportes montados en salpicadero para automóviles", filtrada a precio > 12 € y ≤ 4 estrellas.
  - **Keywords nuevas** de `keyword_ml.py` que no estén en el grupo principal: en **Frase**; en **Amplia** solo si llevan "pinza", con puja baja (70% de su puja máx.).
  - Puja inicial **0,30 €** (sin datos) o la **puja máxima rentable** del modelo. Como máximo **3 novedades por revisión**.
- **Producto negativo:** tu propia ficha (B0DCZS1NR6), para no pagar por salir en ella.
- **Graduación:** una prueba con **≥ 2 ventas y ACOS ≤ 35%** *(propuesto)* pasa al grupo principal (keywords en **Exacta**, con su CPC medio como puja) y se pausa en pruebas.

### 5.2b Coincidencia recomendada

| Situación | Coincidencia |
|---|---|
| Frase nueva | **Frase** (volumen con control) |
| Keyword que ya ha demostrado vender | **Exacta** (su tráfico más rentable) |
| Frase con "pinza" | además **Amplia** con puja baja, para descubrir búsquedas |
| Frase genérica sin "pinza" | **nunca Amplia** (en el histórico: ACOS 122%) |

`keyword_ml.py` ya aprende la diferencia entre coincidencias con y sin "pinza", y el CSV da la predicción en las 3.

### 5.2c Negativas, cartera, ubicaciones y atribución

- **Negativas (Frase) en el grupo principal:** ventosa, rejilla, magnetico, iman, parabrisas, moto, bicicleta, cargador. Cada 2 semanas, del informe de términos de búsqueda: **≥ 10 clics y 0 ventas → negativa exacta**.
- **Cartera "FreshFinder - cartera"** con límite mensual recurrente de 840 € y las campañas dentro: el tope lo aplica Amazon.
- **Ajustes por ubicación:** 0% al empezar. A las 2 semanas, con el informe de ubicación, subir +10-25% solo la ubicación con mejor ACOS.
- **Atribución de 7 días:** las ventas llegan hasta 7 días después del clic. Las pujas se siguen revisando cada 3 días, pero **un cambio se evalúa a los 7 días**, y los últimos días de datos siempre parecen peores de lo que son.
- **Términos de búsqueda:** Amazon solo los guarda **65 días** → descargarlos cada 2 semanas y guardarlos.

### 5.3 Stop-loss

| Nivel | Se dispara cuando… | Acción |
|---|---|---|
| **Prueba (keyword, ASIN o categoría)** | **≥ 15 clics sin ventas** *(propuesto)* | Pausar ya, sin esperar a la siguiente revisión |
| **Keyword normal** | **≥ 15 clics sin ventas** *(propuesto)* | Pausar |
| **Keyword normal** | Ya está en la puja mínima (original − 50%) y sigue con **ACOS > 50%** tras ≥ 20 clics *(propuesto)* | Pausar |
| **Keyword pausada** | Ha pasado **2 veces** por un stop-loss | No reactivar; marcar para revisión de Juan |
| **Campaña de pruebas** | Ha gastado los **50 € del mes** | Pausar la campaña hasta el mes siguiente |
| **Cuenta** | El gasto proyectado del mes llega a **840€** | Solo bajadas y pausas hasta fin de mes |
| **Cuenta** | Todas las campañas en pausa sin haberlo hecho tú, suspensión o problema de pago | No reactivar nada; revisar Seller Central |

### 5.4 Calendario

| Cuándo | Qué |
|---|---|
| **Cada 3 días** | Exportar Segmentación (7-14 días). Aplicar 5.1 a las pujas. Revisar los stop-loss de 5.3. Graduar las palabras de prueba que cumplan 5.2. |
| **Cada 7 días tras un cambio** | Evaluar su ticket (hoja Tickets del Excel): antes, las ventas aún no están atribuidas. |
| **Cada 2 semanas** | Descargar y guardar Términos de búsqueda (solo 65 días): **negativos** los de ≥ 10 clics y 0 ventas; a pruebas los que tengan ventas y no sean keyword. Mirar el informe de ubicación. |
| **Cada 2 semanas** | Actualizar el Excel histórico y ejecutar `keyword_ml.py`. Añadir 2-3 frases nuevas a la campaña de pruebas. |
| **Cada mes** | Comprobar el gasto total (≤ 840€; 7 €/día por campaña). Reiniciar el presupuesto de pruebas. Revisar las keywords marcadas para revisión. |

---

## 5.5 Campañas y presupuesto (26/09/2026)

| Campaña | Qué lleva | Presupuesto |
|---|---|---|
| Pinza - Principal V2 | 5 keywords históricas + 5 especiales del modelo, 8 negativas | 7 €/día |
| Pinza - Pruebas | 4 ASIN de competencia + categoría (a mano), tu ficha como negativa | 7 €/día |
| Rejilla - Principal V2 | 4 históricas + 6 especiales del modelo (perfil `rejilla`), 9 negativas (incl. "pinza") | 7 €/día |
| Pou - Principal V2 | 1 histórica + 9 especiales elegidas a mano (perfil `pou`; solo 1 compra en el histórico → pujas ≤ 0,30 €), negativas exactas "peluche"/"peluches" (a mano) | 7 €/día |
| Pou - Pruebas | 3 ASIN de competencia (preparada, **pendiente** de presupuesto) | ? |

- Pedido por Juan: **7 €/día por campaña = 21 €/día (≈630 €/mes)**. Juan sube el tope de la cartera y de CLAUDE.md a **840 €/mes** (4 campañas × 7 €/día).
- **Campaña para un producto nuevo:** skill `/crear-campana <producto>` (`.claude/skills/crear-campana/SKILL.md`): pregunta lo necesario, crea el perfil en `keyword_ml.py`, la campaña en `crear_memoria.py` y genera memoria + bulk solo de lo nuevo (`--solo`).
- `python crear_memoria.py` genera `resultados/memoria.xlsx` (seguimiento y tickets) y `resultados/bulk_AAAA-MM-DD.xlsx` (hoja masiva para subir; todo se crea en pausa) a partir de los mismos datos.

## 6. Resultados actuales (soporte de pinza, B0DCZS1NR6)

- Datos (Excel histórico completo): 8 grupos de anuncios, 43 keywords distintas, 459 clics, 37 compras, ticket medio 11,24€, CPC medio 0,61€. El modelo acierta un **17,7%** mejor que la media (antes, con los CSV, un 7,4%).
- Lo que el modelo ha aprendido: **"pinza"** es con diferencia la palabra que más vende; "soporte" y "móvil" suman; **"sujeta"**, **"teléfono"** y la coincidencia **Amplia** atraen clics que no compran.
- Mejores frases nuevas: *soporte móvil coche pinza 360* (0,45€ de puja máx.), *… para espejo retrovisor* (0,47€), *… para parasol / ajustable / para iphone* (0,46€). Pujando el CPC medio actual (0,61€), todas quedarían por encima del objetivo del 35%.
- Plan aplicado: `resultados/memoria.xlsx` (generado con `python crear_memoria.py`) (grupo nuevo en la campaña "Soporte móvil pinza", 5 keywords históricas + 5 especiales, tickets y seguimiento).

---

## 7. Pendientes conocidos

- [x] ~~Corregir `keyword_ml.py`~~: quitado el modelo de CPC (aprendía de las pujas, no de las palabras). Ahora ordena por compra/clic y da `puja_max_rentable_eur` con ACOS objetivo 35% (`--acos-objetivo` para cambiarlo). Descarta las frases cuya puja máxima no llega a la puja recomendada más baja de Amazon.
- [ ] **Coste del producto y comisiones de Amazon**, para calcular el ACOS de equilibrio y el beneficio neto real.
- [x] ~~`Sponsored_Products_Target_Sep_25_2026 (3).csv`~~: era el grupo "Soporte pinza a ver → Pinza". Ya entra en el entrenamiento a través del Excel histórico.
- [ ] **Falta el `.gitignore`:** su contenido está en un archivo llamado `download`. Hay que renombrarlo antes de capturar la sesión, para que `.auth/` nunca se suba.
- [ ] Selectores de `browser_agent.py` (ver 4.4).
- [ ] **Pasar las reglas nuevas de la sección 5 al código.** `safety.py` todavía tiene ±20% por cambio y 24h entre cambios. Hay que cambiarlo a revisión cada 3 días con rango de ±50% sobre la puja original, añadir la puja original al log, el grupo de pruebas y los stop-loss nuevos. `CLAUDE.md` también debe actualizarse.
- [ ] Confirmar los números marcados como *(propuesto)* en la sección 5.
- [ ] `safety.py` / `CLAUDE.md` siguen con el fondo de exploración de 20 €/mes: pasar a 50% (50 €/mes) cuando se actualice el código.
- [ ] Hablar de las operaciones en bloque (bulk sheets) como alternativa a `browser_agent.py`.
- [ ] **Actualizar el modelo de Claude** en `ai_marketing_agent.py` y `keyword_generator.py`: ahora es `claude-sonnet-4-5`, se puede cambiar con las variables `MARKETING_AGENT_MODEL` y `KEYWORD_GENERATOR_MODEL`.
- [ ] **Estado de la cuenta:** confirmar que las campañas ya no están en pausa por el saldo de Seller Central antes de activar nada.
