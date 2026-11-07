# Agente autónomo de Amazon Ads — especificación completa para implementar

> **Actualización 30/09-01/10/2026:** Juan cambió varias reglas (sin reparto 80/20, una candidata basta, reactivar, negativas, emplazamientos, pruebas autónomas). Donde este documento diga otra cosa, manda `CLAUDE.md` (sección "Decisiones de Juan" y "Reglas de decisión").

Este documento recoge **todo lo decidido** en la conversación de diseño (26-27/09/2026, Juan + Claude Sonnet 5) para convertir el proyecto en un sistema autónomo: gestiona pujas, keywords, presupuesto y creación de campañas por sí solo, con reglas fijas (no un LLM decidiendo el dinero) y una capa de investigación de mercado aparte.

**Regla de oro de esta sesión de diseño: aquí no se ha escrito ni una línea de Python.** Todo lo de abajo es especificación para que **Claude Opus** lo implemente en una sesión aparte. Sigue habiendo puntos abiertos marcados con ⚠️ — no son bloqueantes para empezar, pero hay que resolverlos antes de dar el sistema por terminado.

> ✅ **Implementado el 27/09/2026** (Claude Opus). Qué archivo hace cada cosa, cómo se han interpretado los detalles que la especificación dejaba abiertos y qué falta: **sección 8**, al final.

---

## 0. Contexto

- Proyecto: FreshFinder, venta de artículos de coche y juguetes en Amazon.es.
- Productos con histórico/campaña hoy: soporte de pinza (B0DCZS1NR6), soporte de rejilla (B0DHYBY6MS), peluche Pou (B0CPHXXHRQ). Catálogo completo puede tener más (ver `Resumen por producto` del histórico).
- Estado de la cuenta: **todas las campañas en pausa**, nada gastando todavía. El sistema arranca en frío.
- Acceso a Amazon: Juan está gestionando el alta a la **Amazon Ads API** (Client ID, Client Secret, refresh token — Login with Amazon). ⚠️ **Sin esas credenciales, la Fase 1 no se puede probar de verdad**, solo escribir el código a la espera.
- Los datos hoy llegan como el Excel `FreshFinder_Amazon_Ads_historico.xlsx` (hojas Resumen por producto / Anuncios / Keywords / una hoja por ASIN / Notas) — **son totales acumulados de toda la vida**, sin fecha por fila.

---

## 1. Decisión de arquitectura: "Camino A"

**No hay un LLM decidiendo pujas, presupuesto ni qué keywords tocar.** Todo eso son reglas fijas, deterministas, que corren en Python sin depender de ninguna API de pago cada vez que se ejecutan. La única pieza que sí usa un LLM es la de **investigación de mercado** (sección 2.11), y su salida son datos (una lista rankeada), nunca una decisión de dinero.

El sistema puede correr **tantas veces al día como se quiera** (no hay un calendario tipo "cada 3 días" para todo el conjunto) — cada keyword/campaña tiene su propio reloj interno, explicado en la sección 2.1.

---

## 2. El motor de decisión

### 2.1 Cuándo se toca algo — "ronda de decisión" por elemento, no por calendario

Una keyword (o ASIN/categoría en una campaña de pruebas) entra en la ronda de decisión — es decir, se plantea si hay que subirle/bajarle la puja, pausarla, etc. — cuando se cumplen **las dos** condiciones:

1. Han pasado **≥3 días** desde el último cambio aplicado sobre ese elemento.
2. Tiene **≥10 clics nuevos** desde ese último cambio.

Si no se cumplen las dos, no se toca en esta ronda, aunque otras keywords sí se muevan.

**Regla de madurez (7 días), para no ser "tonta" con la atribución de Amazon:**
Amazon puede tardar hasta 7 días en atribuir una venta a un clic. Por eso, dentro de los clics "nuevos desde el último cambio":
- Solo los clics con **más de 7 días de antigüedad** cuentan como "maduros" — es decir, cuentan en contra si no han traído venta (para el stop-loss de 2.4).
- Los clics de los últimos 7 días se guardan aparte, como **pendientes de madurar** — nunca cuentan en contra todavía, aunque no hayan traído venta.
- `learner.py` (aprendizaje, sección 3) también espera a que un clic tenga 7 días antes de usarlo para calcular si una decisión "mejoró" o "empeoró" — aunque la propia decisión de tocar la puja se tome ya a los 3 días.

### 2.2 Cálculo de la puja — sin techo artificial, solo el suelo real de Amazon

Se quita cualquier tope tipo "±20%" o "±50%". La puja de cada keyword se recalcula así:

```
puja_máxima_rentable = P(compra | clic) × ticket_medio_del_producto × ACOS_objetivo (30-35%)
```

- `P(compra|clic)`: la predicción del modelo (`keyword_ml.py`, ya construido).
- Único límite duro: **el suelo real de Amazon, 0,02€** — nunca se puja por debajo.
- Segunda red de seguridad: la campaña siempre usa estrategia **"Pujas dinámicas: solo reducir"** — Amazon nunca cobra más de lo pujado.
- No hay techo por arriba: si el dato dice que 1,20€ es rentable, se puja 1,20€.

### 2.3 Añadir una keyword nueva a una campaña existente

- **Máximo 12 keywords por campaña/grupo de anuncios.** Este tope y el resto de reglas de esta sección se evalúan **de forma independiente por cada producto/campaña** — la pinza, la rejilla y el Pou no comparten cupo entre sí.
- Se añade una keyword nueva solo si su **ACOS predicho es ≤30%** (más exigente que el rango normal 30-35%, porque una keyword sin historial propio lleva más incertidumbre que una ya probada).
- **Cuando se pausa una keyword (sección 2.4), su hueco se rellena** con la siguiente mejor candidata que cumpla el ≤30% — así el número de keywords activas por campaña tiende a mantenerse en 12.

### 2.4 Cuándo pausar una keyword (stop-loss)

```
Se pausa cuando llega a 20 clics MADUROS (>7 días) O a 4€ gastados en clics maduros,
lo que ocurra antes, sin ninguna venta atribuida todavía.
```

- Una sola venta, aunque sea pequeña, libra a la keyword de esta regla — a partir de ahí se trata como una keyword normal (sección 2.2).
- Nunca se borra de verdad — siempre se **pausa** (reversible). Una keyword pausada 2 veces seguidas por lo mismo no se reactiva sola: se marca para que Juan la revise.

### 2.5 Presupuesto

- **Techo duro absoluto: 840€/mes**, vía la cartera de Amazon. Esto no se toca nunca, es la única regla de verdad no negociable de todo el sistema (junto con 2.9-bis, cuenta pausada).
- **20% del total (168€/mes), fijo y global** (no por producto), reservado a experimentación: keywords/ASIN/categorías/productos sin historial probado todavía.
- **80% restante (672€/mes)**, repartido entre lo que ya demuestra funcionar, según una puntuación por campaña (ver sección 3 — igual que `aggressiveness_multiplier` pero a nivel de campaña, no de keyword): más cerca del ACOS objetivo y con buena respuesta histórica a más presupuesto → más dinero.
- **Sin mínimo artificial que fuerce a pausar una campaña por falta de presupuesto** — de momento se es laxo con esto (no hay nada gastando todavía en la cuenta real). Esto se revisará más adelante cuando ya haya dinero circulando de verdad.
- Reasignación **libre, sin tope por movimiento** entre campañas — puede vaciar una a 0 y volcarlo a otra si los datos lo justifican con claridad.

### 2.6 Crear campaña nueva vs. añadir a una existente

- **Por defecto: añadir a la campaña existente del producto**, mientras tenga hueco (<12 keywords).
- Se abre una **campaña nueva** solo cuando:
  - El producto no tiene ninguna campaña todavía y hay hueco en el 20% de experimentación para financiarla de verdad, **o**
  - Todas las campañas existentes del producto están llenas (12/12) y hay una candidata con predicción claramente buena sin sitio donde meterla.
- ⚠️ **Regla importante que añadió Juan:** abrir una campaña **siempre cuesta un presupuesto diario real y significativo** (Amazon no permite campañas "simbólicas" — el mínimo técnico es 1€/día, pero eso no da señal útil). Por eso, antes de decidir "abro campaña nueva" vs. "reparto ese dinero en keywords sueltas dentro de lo que ya existe", el motor tiene que comparar el coste de oportunidad: abrir una campaña nueva consume de golpe un trozo grande del fondo de experimentación (168€/mes), así que solo se hace cuando los datos lo justifican con claridad, no como primera opción por defecto.
- **Expansión de catálogo confirmada como autónoma**: el sistema puede detectar productos del catálogo sin campaña y abrirles una si el fondo de experimentación lo permite, sin que Juan tenga que darlos de alta a mano primero.

### 2.7 Comprobación de elegibilidad antes de tocar nada

Antes de decidir nada sobre una keyword o ASIN, comprobar el **estado de elegibilidad del anuncio** (Amazon lo da directamente en los datos: Oferta Destacada, stock, calidad de la ficha). Si el anuncio no es elegible para mostrarse, no se toca su puja — eso no es un problema de la keyword, es un problema de la ficha/cuenta, y se avisa aparte (ver 2.9).

### 2.8 Verificación de cambios aplicados + independencia entre cambios

- **Nunca se da un cambio por hecho solo por haberlo pedido.** Tras pedir un cambio a la API, se vuelve a leer ese elemento y se comprueba que el valor real coincide con lo pedido. Solo entonces se marca como "confirmado" en el documento único. Si no coincide, se reintenta o se marca como fallido — nunca se asume éxito a ciegas.
- **Cada cambio es independiente.** Si al aplicar varios cambios uno falla a mitad, los demás no se ven afectados — un fallo puntual nunca deja la cuenta en un estado a medias ni bloquea el resto de la ronda.
- Esta comprobación y la independencia entre cambios son **las dos caras de la misma capa de seguridad** — van juntas, no una sin la otra.

### 2.9 Alertas

- **Cada ejecución que aplique al menos un cambio** envía **un correo a `yubunama62@gmail.com`** con la lista de qué cambió (keyword/campaña, antes → después, motivo). Un correo por ronda, no uno por cambio individual, para no saturar.
- **2.9-bis, regla que nunca se toca:** si todas las campañas aparecen en pausa sin que el propio sistema las haya pausado (problema de cuenta, saldo, Buy Box…), el sistema **para y avisa por correo, inmediato y aparte del resumen normal**. Nunca reactiva nada por su cuenta — eso es siempre decisión de Juan.

### 2.10 Lista de ASIN de competencia — manual, no autodescubierta cada vez

Los ASIN de la competencia cambian poco por producto, así que **no se re-buscan solos en cada ronda**. Viven en una pestaña del documento único ("Competencia"), que Juan edita/confirma a mano cuando hace falta. El motor solo los lee de ahí.

### 2.11 Investigación de mercado — aquí sí hay un LLM, con instrucciones muy concretas

Este es el único sitio del sistema donde interviene un LLM, y su trabajo es **buscar y rankear**, nunca decidir dinero:

- Para cada producto, busca y ordena **palabras clave candidatas** usando: búsqueda web + el conector de keywords que se conecte (Helium 10 o alternativa gratuita) + el propio histórico del producto.
- Devuelve una lista ordenada con su motivo (igual que ya hace `keyword_ml.py --candidatas`, pero con el LLM aportando lo que las reglas fijas no pueden: interpretar texto libre de la web).
- Esa lista entra al filtro determinista de la sección 2.3 (≤30% ACOS predicho) exactamente igual que cualquier otro candidato — **el LLM propone y rankea, las reglas fijas deciden si entra de verdad**.

---

## 3. Aprendizaje (`learner.py`) — dos niveles

**Nivel keyword (ya existe, se mantiene el concepto):**
1. Por cada keyword y producto, mira cuántas subidas de puja se hicieron y cuántas de esas mejoraron el ACOS después.
2. `success_rate = aciertos / subidas totales`.
3. `aggressiveness = 0.2 + 0.8 × success_rate` (sin historial → 0.5 neutro; 100% acierto → 1.0; 0% acierto → 0.2, nunca 0 del todo).
4. Este número decide qué tan cerca de la `puja_máxima_rentable` (2.2) se atreve a ir el sistema con esa keyword en concreto.

**Nivel campaña/producto (pieza nueva, para el presupuesto de 2.5):**
- Mismo cálculo, pero preguntando: de las veces que se le subió el presupuesto a esta campaña, ¿cuántas trajeron más ventas manteniendo el ACOS en objetivo?
- Da una "puntuación de confianza" por campaña que, combinada con su ACOS actual, decide qué porción del 80% (672€/mes) le toca. Una campaña que históricamente responde bien a más dinero se lleva más que otra con el mismo ACOS hoy pero que en el pasado no mejoró al recibir más presupuesto.

---

## 4. El documento único

**Un solo archivo persistente** (evoluciona `memoria.xlsx`, que ya existe) con, como mínimo:
- **Segmentación**: estado actual de cada keyword/ASIN/categoría por campaña (como los exports de Amazon).
- **Seguimiento**: una foto por ronda (fecha + clics/coste/compras/ventas acumulados) — así se calcula "clics nuevos desde el último cambio" por resta entre fotos (método confirmado, sin necesidad de informes diarios de la API por ahora).
- **Tickets**: un registro por cada cambio, con motivo, antes/después, y veredicto (mejora/empeora) una vez maduro.
- **Histórico**: lo importado de antes de que existiera el sistema.
- **Competencia**: la lista manual de ASIN de la sección 2.10.

⚠️ **Salvaguarda técnica a implementar:** un Excel no está pensado para que un programa lo reescriba muchas veces al día sin cuidado (riesgo de corrupción si se corta a medias). Escribir siempre a un archivo temporal y sustituir el documento real solo cuando la escritura termina entera y bien.

---

## 5. Fuera de alcance por ahora (no implementar todavía)

- **Negativas automáticas** entre campañas propias o de términos de búsqueda malos — aplazado explícitamente por Juan.
- Sponsored Brands / Sponsored Display — este proyecto es solo Sponsored Products.
- Ajustes finos por ubicación (top of search, etc.).
- Informes diarios de la API (Reporting API) — se sigue con "foto y resta" sobre el documento único.

---

## 6. Plan de implementación (orden sugerido para Opus)

1. **`ads_api.py` — Fase 1, empezar ya.** Conexión completa a la Amazon Ads API para **extraer todos los datos** (campañas, grupos, keywords, ASIN, elegibilidad). ⚠️ Necesita que Juan ya tenga las credenciales (Client ID, Client Secret, refresh token) para poder probarse de verdad — si no las tiene aún, se escribe el código y queda listo, pero no se puede validar contra la cuenta real todavía.
2. **Reescribir `analyzer.py` y `safety.py`** con las reglas 2.1-2.4 (madurez de 3+7 días, fórmula de puja sin techo artificial, tope de 12 keywords, stop-loss de 20 clics/4€).
3. **Módulo nuevo de presupuesto** (sección 2.5 + parte de aprendizaje de la sección 3).
4. **Módulo nuevo de creación/expansión de campañas** (sección 2.6).
5. **Comprobación de elegibilidad** (2.7) integrada en el flujo, antes de cualquier decisión.
6. **Escritura + verificación en `ads_api.py`** (2.8): aplicar cambios y releer para confirmar, con independencia entre ellos.
7. **Sistema de alertas por correo** (2.9).
8. **Documento único** (sección 4): evolucionar `memoria.xlsx` con la salvaguarda de escritura atómica.
9. **Módulo de investigación** (2.11): la llamada acotada al LLM para buscar/rankear keywords, con el prompt bien definido para que solo devuelva datos, nunca decisiones.
10. **Retirar del flujo activo** (documentar como legacy, no borrar): `browser_agent.py`, `capture_session.py`, `ai_marketing_agent.py`, `keyword_generator.py`.

---

## 7. Puntos abiertos / a confirmar con Juan antes de dar por cerrado

- ⚠️ **Estado de las credenciales de la Amazon Ads API** — imprescindible para probar la Fase 1 de verdad.
- ⚠️ La "puja máx. rentable" de las campañas de pruebas por ASIN de competencia usa hoy la conversión **media del producto entero**, no algo específico de cada ASIN competidor — se podrá refinar cuando haya datos reales de cada uno.
- ⚠️ Una palabra suelta de Juan sin aclarar del todo ("sbs", en el contexto de crear campañas nuevas desde el fondo de experimentación) — no bloquea nada, ya está cubierto por la sección 2.6, pero si tenía otro significado, revisar.

---

## 8. Estado de la implementación (27/09/2026)

### Dónde está cada cosa

| Sección | Archivo | Notas |
|---|---|---|
| 2.1 ronda + madurez 7 días | `analyzer.py`, `documento.py` (`Series.maduro`) | Con la API, "maduro" = clics de días con más de 7 días (hoja Diario). Con la hoja masiva, la foto de hace ≥ 7 días |
| 2.2 puja | `analyzer.py`, `prediccion.py` | `P × ticket × ACOS`; el ACOS va de 30 % (agresividad 0,2) a 35 % (agresividad 1). P = modelo mezclado con los clics maduros propios (20 clics propios pesan como el modelo) |
| 2.3 12 keywords + ≤ 30 % | `analyzer.py` (`_rellenar_huecos`), `prediccion.py` (`candidatas`) | Candidatas: histórico del producto, frases del modelo, hoja Investigación. Nunca palabras de otro producto ni Amplia genérica |
| 2.4 stop-loss | `analyzer.py` | Cuenta desde que el agente creó el elemento (o desde que hay datos). Pausada 2 veces → "Requiere revisión" |
| 2.5 presupuesto | `presupuesto.py`, `safety.py` | Tope del día = min(840 / días del mes, lo que queda / días que faltan) |
| 2.6 campañas nuevas | `campanas.py` | Máx. 1 por ronda |
| 2.7 elegibilidad | `analyzer.py` (`elegibilidad_grupo`) | Por `servingStatus` de los anuncios del grupo |
| 2.8 verificación | `ads_api.py` (`_actualizar`, `_crear`), `agente.py` | Relectura + 1 reintento; si falla la creación de campaña a medias, se pausa |
| 2.9 / 2.9-bis alertas | `alertas.py`, `safety.py` (`problema_de_cuenta`) | Un correo por ronda; aviso inmediato (máx. 1 al día) si la cuenta está parada |
| 2.10 competencia | hoja Competencia | Solo se usan los ASIN con "Sí" en "Confirmado por Juan" |
| 2.11 investigación | `investigacion.py` | Claude + búsqueda web, semanal, solo si hay `ANTHROPIC_API_KEY`. Devuelve datos a la hoja Investigación |
| 3 aprendizaje | `learner.py` | Veredicto con ≥ 10 clics maduros tras el cambio y antes del siguiente |
| 4 documento único | `documento.py` → `resultados/memoria_agente.xlsx` | Escritura atómica + copia `.bak` |
| 6.1 extracción API | `ads_api.py` | Sin credenciales todavía: probado solo con una API falsa (`tests/`) |
| 6.10 legacy | `legacy/` | Movido, no borrado |

### Decisiones de implementación que conviene que Juan conozca

1. **Informes diarios de la API (cambio respecto a §5).** Los listados de la Amazon Ads API (campañas, keywords…) **no traen clics, gasto ni ventas**: esas métricas solo salen de la Reporting API. El agente pide el informe diario `spTargeting` (cada fila lleva su fecha) y lo guarda en la hoja "Diario"; las fotos de "Seguimiento" se siguen guardando para leerlas a simple vista. Ventaja: la regla de los 7 días es exacta. La primera ejecución pide 60 días; después, los últimos 10 (las ventas llegan hasta 7 días tarde).
2. **Modo sin API.** Mientras no haya credenciales, el mismo motor funciona con la hoja masiva descargada (`fuente_bulk.py`): genera `bulk_cambios_<fecha>.xlsx` para subir a mano y confirma cada cambio al leer la descarga siguiente (a los 14 días sin reflejarse → fallido). ⚠️ El valor "Actualizar" de la columna Operación aún no está confirmado por un informe de Amazon.
3. **Documento aparte.** `resultados/memoria_agente.xlsx` es un archivo nuevo (se siembra con el histórico y la competencia). `memoria.xlsx` y `memoria_pou.xlsx` son de la etapa manual y tienen fórmulas y tickets de Juan: no se pisan.
4. **"ACOS predicho" de una candidata** = CPC para competir / (P(compra|clic) × ticket). CPC para competir = la puja recomendada baja de Amazon para esa frase; si es nueva, la mediana de las frases parecidas del producto (específicas y genéricas por separado, porque las genéricas cuestan 3-4 veces más).
5. **Qué es "probado" (80 %)**: producto con ≥ 10 compras en el histórico y campaña que no es de pruebas, o cualquier campaña que ya haya hecho ≥ 3 compras maduras con ACOS ≤ 35 % (se "gradúa"). Lo demás (pruebas, Pou, campañas abiertas por el agente) es experimentación, a partes iguales dentro del 20 %.
6. **Coste de oportunidad de abrir campaña (§2.6):** solo se abre si, repartiendo el 20 % entre una campaña experimental más, a cada una le siguen tocando ≥ 2,50 €/día. Con los presupuestos actuales (Pou y Pinza - Pruebas ya son experimentales), el agente **no abrirá campañas nuevas** hasta que alguna se gradúe o se pause.
7. **Primer efecto esperado en presupuestos**: hoy las 4 campañas están a 7 €/día. Con la regla 80/20, Pou - Principal V2 y Pinza - Pruebas (experimentales) bajarían a ≈2,80 €/día cada una y Pinza/Rejilla - Principal V2 se repartirían ≈22,40 €/día según su ACOS (la pinza se lleva más).
8. **El agente nunca pausa campañas** (mínimo 1 €/día), así que "todo en pausa" siempre es algo externo → aviso y parada. La única excepción es una campaña que él mismo crea y falla a medias: la pausa y la excluye de esa comprobación.

### Sigue abierto

- ⚠️ Credenciales de la Amazon Ads API (sin ellas `ads_api.py` solo está probado con una API falsa).
- ⚠️ Correo: falta configurar SMTP (sin él, los correos quedan en `resultados/correos_pendientes/`).
- ⚠️ ASIN de competencia: conversión media del producto (sin cambios).
- ⚠️ "sbs": sin aclarar; no bloquea.
