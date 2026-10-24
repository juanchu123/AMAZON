# FreshFinder — Agente autónomo de Amazon Ads

## Qué es esto

Un agente que se conecta a la cuenta de Amazon Ads de **FreshFinder** (artículos de coche y juguetes en Amazon.es), lee el rendimiento real de campañas, keywords y ASIN, y **actúa por sí solo**: ajusta pujas, pausa lo que pierde dinero, añade keywords nuevas, reparte el presupuesto entre campañas y abre campañas nuevas cuando los datos lo justifican. Cada cambio se verifica releyendo Amazon, queda registrado en un documento único y se avisa a Juan por correo.

La especificación completa (decidida con Juan el 26-27/09/2026) está en **`AGENTE_AUTONOMO.md`**. Este archivo resume lo que cualquier sesión de Claude Code tiene que saber antes de tocar nada. **`CONOCIMIENTO_AMAZON_ADS.md`** recoge cómo funciona Amazon Ads (estrategias de puja, emplazamientos, presupuesto, atribución, negativas, hoja masiva, cómo evaluar cambios), con fuentes: léelo antes de cambiar cualquier regla.

## Objetivo de negocio

- **ACOS objetivo: 30-35 %** (gasto en ads / ventas atribuidas a ads). Keyword nueva: solo con ACOS predicho ≤ 30 %.
- **Tope duro: 840 €/mes** (cartera de Amazon; 100 € → 630 € → 840 €, cambiado por Juan el 26/09/2026). Solo Juan lo cambia (`config.TOPE_MENSUAL_EUR`, `crear_memoria.CARTERA_MENSUAL`, este archivo y `marketingV2.md`).
- **El presupuesto lo reparte el agente entero** (Juan, 30/09/2026): sin 80/20 ni fondo fijo de experimentación, por puntuación de campaña y dentro del tope.

## Antes de empezar: pregunta primero

Cualquier sesión que abra este proyecto pregunta a Juan lo que necesite **antes** de ejecutar nada contra la cuenta real:

- **Credenciales de la Amazon Ads API** (`AMAZON_ADS_CLIENT_ID`, `AMAZON_ADS_CLIENT_SECRET`, `AMAZON_ADS_REFRESH_TOKEN`, opcional `AMAZON_ADS_PROFILE_ID`). Van en variables de entorno de SU ordenador. **Nunca pedirle que las pegue en el chat ni subirlas a git.**
- **Estado real de la cuenta**: la última vez, todas las campañas estaban en pausa (saldo de Seller Central). Con todo en pausa el agente avisa y se para: es lo correcto.
- **Correo** (`SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`; con Gmail, contraseña de aplicación) y, si se quiere la investigación de mercado, `ANTHROPIC_API_KEY`.
- **La primera vez, `python agente.py --simular`**: decide y lo cuenta sin tocar Amazon ni crear tickets. Solo después, ejecuciones reales.
- Cualquier cosa ambigua o contradictoria: preguntar en un mensaje corto antes que adivinar.

## Decisiones de Juan del 30/09/2026 y del 01/10/2026 (implementadas)

Tras estudiar Amazon Ads Academy (Sponsored Products D1, resumen en `CONOCIMIENTO_AMAZON_ADS.md` §18):
1. **Una candidata rentable entra**, sin esperar a tener 3 (también para abrir campaña).
2. **El presupuesto lo gestiona el agente entero** (techo 840 €/mes).
3. **El agente puede cambiar lo que necesite** en Amazon: pujas, estrategia, **ajustes de emplazamiento**, **negativas**, reactivar.
4. **Puede reactivar** keywords y campañas en pausa si sus datos lo justifican (nunca lo pausado 2 veces por el agente: revisión de Juan; una campaña terminada por fecha no se reactiva: se copia lo bueno).
5. **Se mantiene** la parada con aviso si todo está en pausa o hay un problema de cuenta/pago.
6. **Pruebas autónomas** (`pruebas.py`) por potencial, con stop-loss, cupo según lo que queda del tope, sin pruebas en Black Friday ni Navidad, y aprendiendo qué tipo de frase vende.
7. Sin erratas como keywords. Sin comprobación de "listo para retail" (pinza y rejilla se anuncian igual). La ficha la decide Juan. **Sin Registro de Marca**: nada de A+, Brand Store ni Sponsored Brands.

## Agente ADS (desde el 09/10/2026): el gestor experto que habla con Juan por Gmail

Claude en la nube, con dos rutinas (ronda diaria y correo; `agente_ads/RUTINAS.md`). Lee la cuenta con el
conector **SellerMate (solo lectura)**, guarda los datos en `entradas/<día>/sellermate/` (`fuente_sellermate.py`),
pasa el motor (`python agente.py --fuente sellermate`), revisa lo que propone con criterio (vetos en
`agente_ads/directivas.json`) y manda a Juan el parte con dos Excel: `bulk_cambios` (lo pequeño) y `propuestas`
(subir presupuesto, crear o reactivar campañas). **Juan sube los Excel: nada se cambia en Amazon sin él.**
Su manual: `agente_ads/AGENTE_ADS.md`; su conocimiento: `PRODUCTOS.md`, `CALENDARIO.md`, `LECCIONES.md`,
`ESTRATEGIA.md`; lo que dice Juan: `directivas.json` (tope, modo crecer/normal/recortar, campañas terminadas,
no reactivar, vetos, palabras ajenas extra).

## Tres agentes, un solo comando (`python agente.py`)

- **Marketing** (`agente.py` y sus módulos): anuncios — pujas, presupuesto, keywords, campañas. Reglas fijas.
- **Finanzas** (`finanzas.py`): con los costes que Juan rellena en la hoja **Economía** calcula margen por unidad y **ACOS de equilibrio** por producto (el límite de las pujas de marketing; sin costes, 35 %) y la hoja **Finanzas** (beneficio después de publicidad por producto, mes en curso y 30 días; gasto del mes frente al tope). Corre antes que marketing. Suelto: `python finanzas.py`.
- **Página de producto** (`ficha.py`): prepara `salidas/<día>/ficha_datos_<día>.xlsx` (palabras que venden, frases que gastan sin vender, investigación que pasa el filtro, quejas de la competencia); Cowork lee la ficha en amazon.es y escribe la propuesta (lunes, `RUTINA_COWORK.md`). **La ficha nunca se cambia sola: decide Juan.** Suelto: `python ficha.py`.
- La parte que necesita un LLM (investigar, proponer la ficha, el informe) la hace **Cowork** con la suscripción de Juan, no la API.

## Arquitectura ("Camino A": reglas fijas, sin LLM decidiendo dinero)

```
agente.py  (orquestador: una ejecución = una ronda; se puede lanzar cuantas veces se quiera)
 ├─ fuente de datos (solo lee y ejecuta, no decide)
 │   ├─ ads_api.py     Amazon Ads API v3: listados + informe diario (Reporting API) + escritura con verificación
 │   └─ fuente_bulk.py sin API: lee la hoja masiva descargada y escribe bulk_cambios_<fecha>.xlsx para subir a mano
 ├─ carpetas.py       entradas/<día>/ (hoja masiva + investigación) y salidas/<día>/ (memoria + cambios)
 ├─ documento.py      documento único (salidas/<día>/memoria_agente.xlsx), escritura atómica
 ├─ learner.py        veredicto de cada cambio (con clics maduros) y agresividad / confianza aprendidas
 ├─ terminos.py       términos de búsqueda: cosecha (lo que vende pasa a Exacta) y negativas (gasto > CPA sin ventas)
 ├─ analyzer.py       por keyword/ASIN: elegibilidad, ronda, stop-loss, puja, reactivar, huecos hasta 12
 ├─ pruebas.py        pruebas autónomas: potencial, cupo según el tope, aprendizaje por tipo de frase
 ├─ pujas.py          sistema de pujas: puja objetivo, tope rentable, multiplicador de Amazon y estrategia de cada campaña
 ├─ emplazamientos.py ajustes de puja por emplazamiento según la conversión de cada uno
 ├─ prediccion.py     por producto: ticket, conversión escalonada por coincidencia, modelo, candidatas (ACOS predicho)
 ├─ presupuesto.py    reparto del tope del día entre todas las campañas (más a las limitadas que rinden)
 ├─ campanas.py       ¿abrir o reactivar campaña? (con una candidata rentable y ≥ 2,50 €/día para ella)
 ├─ validacion.py     lo que Amazon acepta (keywords ≤ 80 caracteres/10 palabras, coincidencias, estrategias)
 ├─ safety.py         última barrera: suelo de puja, tope mensual, cuenta parada, validación. Nunca se salta
 ├─ finanzas.py       agente de finanzas: hoja Economía (costes) -> margen y ACOS de equilibrio; hoja Finanzas
 ├─ ficha.py          agente de página de producto: datos para mejorar la ficha (la propuesta la escribe Cowork)
 ├─ alertas.py        un correo por ronda + avisos inmediatos (SMTP; si no hay, .eml pendiente)
 └─ investigacion.py  ÚNICO uso de un LLM: buscar y ordenar frases candidatas (solo datos)
config.py            todos los números
keyword_ml.py        modelo de machine learning de keywords (P(compra|clic)), perfiles de producto
crear_memoria.py     generador de campañas iniciales (memoria + bulk), usado por la skill crear-campana
legacy/              el sistema anterior (navegador + LLM decidiendo); ver legacy/README.md
```

Las reglas no saben de dónde vienen los datos: la API y la hoja masiva producen la misma estructura (`modelo.py`).

**Sobre las fechas:** los listados de la API no traen métricas. Las métricas salen del informe diario `spTargeting` (Reporting API v3), una fila por día y elemento, que se guarda en la hoja "Diario". Con ellas el agente sabe exactamente qué clics tienen más de 7 días. Con la hoja masiva (sin fechas por fila) se usan fotos diarias en "Seguimiento" y se resta entre fotos.

## Reglas de decisión (AGENTE_AUTONOMO.md §2, actualizadas el 30/09-01/10/2026)

1. **Elegibilidad (§2.7):** si el anuncio del grupo no se puede mostrar (sin Oferta Destacada, sin stock, ficha rechazada…) no se toca nada del grupo y se avisa.
2. **Ronda (§2.1):** un elemento solo se decide con **≥ 3 días** desde su último cambio **y ≥ 10 clics nuevos**. Clic **maduro** = más de 7 días (atribución de Amazon). Lo que el agente crea o reactiva no se juzga (puja) hasta los **14 días**; el stop-loss vigila desde el primer día.
3. **Stop-loss (§2.4):** **20 clics maduros o 4 € maduros sin ninguna venta → pausar** (nunca borrar), contados desde que el agente la creó o reactivó. Una venta lo libra. Pausada 2 veces → "Requiere revisión de Juan" y el agente ya no la reactiva.
4. **Puja (§2.2, `pujas.py`):** `P(compra|clic) × ticket medio × ACOS objetivo`, con el ACOS entre 30 % y 35 % según la agresividad aprendida. P(compra|clic) = modelo de `keyword_ml.py` **escalonado amplia ≤ frase ≤ exacta** (regresión isotónica), mezclado con los clics maduros propios. Se calcula para el emplazamiento que peor convierte. **Suelo 0,02 €, sin techo artificial**, pero lo que Amazon pueda cobrar por un clic (con la estrategia y el ajuste del emplazamiento) nunca pasa del equilibrio en ningún emplazamiento.
   **Estrategia (por campaña):** "al alza y a la baja" solo con ≥ 10 compras maduras en 30 días, ACOS ≤ equilibrio y margen para que Amazon suba la puja; si no, "solo a la baja".
   **Emplazamientos (`emplazamientos.py`):** con ≥ 5 compras y ≥ 100 clics en la campaña, ajuste = conversión del emplazamiento / la del peor − 1 (prudente, máx. +900 %, cambios ≥ 10 puntos).
5. **Términos de búsqueda (`terminos.py`):** CPA objetivo = ticket × ACOS objetivo. Con ventas y ACOS ≤ 35 % → keyword en **Exacta** (cosecha, antes que cualquier otra candidata). Sin ventas y gasto **maduro** ≥ CPA → **Exacta negativa** en el grupo que lo cazó. Si ya es Exacta en otro grupo → negativa en el de origen. Nunca negativa a la propia keyword ni a un ASIN.
6. **Huecos (§2.3):** máximo **12 keywords/ASIN activos por grupo**. Se rellenan con: cosecha; después, por ACOS predicho (≤ 30 %), keywords en pausa que sus datos justifican **reactivar**, lo bueno de campañas **terminadas** (se copia) y candidatas nuevas (histórico, modelo, investigación), corregidas por lo aprendido de cada tipo de frase; y, si queda hueco y cupo, **pruebas** (`pruebas.py`: frases que solo pasan con su potencial, percentil 80).
7. **Presupuesto (§2.5):** tope del día = lo que permite no pasar de 840 €/mes, repartido entre **todas** las campañas por puntuación (ACOS de 30 días × confianza). Las limitadas por presupuesto que rinden reciben más; a una que gasta poco, como mucho 1,5 × lo que gasta. Mínimo 1 €/día; nunca se pausa una campaña por presupuesto.
8. **Campañas (§2.6):** por defecto se añade a la existente. Si el producto no tiene campaña activa: se **reactiva** la que esté en pausa con keywords que compensan; si no, se abre una nueva. También si todas están 12/12 y sobra una candidata rentable. Basta **una** candidata, máx. 1 por ronda y solo si le tocarían ≥ 2,50 €/día.
9. **Validación (`validacion.py`):** nada sale con una keyword, coincidencia o estrategia que Amazon rechace (errores 1018, 1021 y 1025).
10. **Verificación (§2.8):** cada cambio se aplica, se relee en Amazon y solo entonces queda "confirmado"; si no coincide, un reintento y "fallido". Cada cambio es independiente.

## Reglas de seguridad (no negociables)

1. **Tope mensual 840 €.** Si el gasto proyectado del mes ya llega al tope: solo bajadas, pausas y negativas.
2. **Cuenta parada (§2.9-bis):** si todas las campañas están en pausa sin que las pausara el agente, o Amazon marca un problema de cuenta o de pago → correo inmediato y **parar sin tocar nada** (y sin reactivar nada).
3. Fuera de Sponsored Products (Sponsored Brands/Display, cambiar la cartera, la ficha) nada sin que Juan lo pida.
4. Cualquier cambio de estas reglas lo pide Juan explícitamente; no se relajan porque "los datos lo justifiquen".

## Aprendizaje (learner.py)

- Cada cambio guarda la "base" (acumulado en ese momento). Cuando hay ≥ 10 clics **maduros** después del cambio (y antes del siguiente), se escribe el veredicto "mejora"/"empeora" en el ticket. Sin evaluar = neutro.
- **Nivel keyword** (producto + keyword + coincidencia, nunca por campaña): `agresividad = 0,2 + 0,8 × tasa de acierto de las subidas` (0,5 sin historial).
- **Nivel campaña:** lo mismo con las subidas de presupuesto (¿más ventas al día con ACOS en objetivo?). Es la "confianza" que usa el reparto del presupuesto.
- **Tipo de frase** (`pruebas.Aprendizaje`, hoja "Aprendizaje"): por producto, específica/genérica × coincidencia, compras reales frente a las que esperaba el modelo; ese factor (0,25-2) corrige la conversión de las frases nuevas de ese tipo.
- Un LLM no aprende entre llamadas: la memoria es el documento único.

## Carpetas: `entradas/` y `salidas/`, una por día (`AAAA-MM-DD`)

- `entradas/<día>/`: la **hoja masiva** descargada de Amazon e `investigacion_<día>.csv` (Cowork; `ASIN;Palabra clave;Motivo;Fuente;Volumen;Puja sugerida (€)`). El agente usa la hoja masiva de la carpeta más reciente e importa la investigación de todas las carpetas hasta hoy.
- `salidas/<día>/`: `memoria_agente.xlsx` actualizada, `bulk_cambios_<fecha>.xlsx` para subir a Amazon, `Documento_investigacion_keywords.xlsx` y `correos_pendientes/`.
- **Investigación sin repetir:** la hoja "Investigación" es una bolsa de todas las frases de todos los días, una vez por producto (misma firma = sin acentos, mayúsculas, orden ni palabras vacías). `python investigacion.py --ya-vistas` escribe `salidas/<hoy>/frases_ya_vistas.csv` para que Cowork no busque otra vez lo ya visto. El Excel de investigación lo genera el agente con la misma función con la que decide (`prediccion.Catalogo.evaluar`).
- El código vive solo en este repo: Cowork lo ejecuta pero no lo modifica. Su rutina diaria está en `RUTINA_COWORK.md`.
- La memoria de cada día **parte de la del día anterior más reciente** (o de la del mismo día si se repite): nunca se empieza de cero.

## Documento único — `salidas/<día>/memoria_agente.xlsx`

Hojas: Leyenda, Resumen, Economía (**la rellena Juan**), Finanzas, Campañas, Segmentación, Seguimiento (fotos), Diario (API), Términos (fotos de términos de búsqueda), Tickets, Aprendizaje, Competencia (**la edita Juan**), Investigación, Alertas, Histórico. Las hojas que añadan Juan o Cowork (p. ej. "Productos") se conservan tal cual. Se escribe a un temporal y se sustituye al final (atómico), con copia `.bak`. Hay que commitearlo: es la memoria del agente. `resultados/memoria.xlsx` y `memoria_pou.xlsx` son la memoria de la etapa manual: no se pisan.

## Cómo se ejecuta

```bash
python agente.py --simular            # primera vez: no toca nada
python agente.py                      # API si hay credenciales; si no, la hoja masiva de la entrada más reciente
python -m pytest tests/ -q            # tests con una API falsa
```
Programado con cron / Programador de tareas (o Cowork) en el ordenador de Juan: el proceso corre, decide, ejecuta y termina.

## Skills y rutina

- `crear-campana`: campañas iniciales con memoria + bulk (manual, en pausa).
- `investigar-keywords`: puntuar frases de Helium 10 con el modelo (manual).
- `revision-semanal` (rutina de los lunes en la nube): corre el agente con la entrada más reciente de `entradas/` y deja el informe en `salidas/<día>/`.
- Rutina diaria de Cowork en el ordenador de Juan: `RUTINA_COWORK.md` (descarga, investigación nueva, agente, informe).

## Estado actual / pendiente

- [ ] Juan: credenciales de la Amazon Ads API → primera ejecución `--simular` con la API real.
- [x] Operación de la hoja masiva: Crear / Actualizar / Archivar (confirmado en Amazon Ads Academy). Estado y Producto se escriben copiando la descarga ("activada", "en pausa").
- [ ] Al descargar la hoja masiva, marcar el informe de términos de búsqueda (sin él no hay cosecha ni negativas).
- [ ] Negativas de ASIN (páginas de producto) en campañas automáticas: pendiente.
- [ ] Correo SMTP configurado (si no, los avisos quedan en `salidas/<día>/correos_pendientes/`).
- [ ] La conversión de los ASIN de competencia usa la media del producto (se refinará con datos reales de cada ASIN).
- [ ] Coste del producto y comisiones de Amazon para calcular el ACOS de equilibrio real.
- [x] Negativas automáticas por CPA (Juan, 01/10/2026).
- [ ] Juan: rellenar la hoja "Economía" (comisión de Amazon, tarifa FBA, coste de cada producto). Hasta entonces el ACOS de equilibrio es el 35 % (`config.ACOS_EQUILIBRIO_DEFECTO`).
- [ ] Resto de la especificación de mejoras (28/09/2026): P0-A completo, P0-B §1-3 y §5, P1, P2. Hecho: P0-B §4 (sistema de pujas), P1-B.2 (CPC calibrado con lo pagado de verdad: `Producto.factor_cpc`, nunca < 1) y P0-B §2 (hoja Economía y ACOS de equilibrio por producto; el ACOS objetivo sigue siendo 30-35 % hasta que Juan decida).

## Notas importantes

- Dinero real. FreshFinder tuvo una suspensión de Seller en septiembre de 2026 (DAC7/IVA) y **todas las campañas quedaron en pausa** porque Amazon no pudo cobrar los anuncios del saldo de vendedor (reserva en la entidad de Bélgica). El agente asume que puede repetirse: con todo en pausa, avisa y se para.
- Productos con histórico: pinza (B0DCZS1NR6, 37 compras), rejilla (B0DHYBY6MS, 53), Pou (B0CPHXXHRQ, 1 → modelo no fiable, se usa su conversión media), ventosa (B0DSV986XY) y 3-en-1 (B0F746MFPQ) sin datos suficientes.
- Commits en español, en la rama de trabajo; sin PR salvo que Juan lo pida.
