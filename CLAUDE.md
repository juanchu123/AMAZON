# FreshFinder — Optimizador Autónomo de Amazon Ads

## Qué es esto

Un sistema que se conecta a la cuenta de Amazon Ads de **FreshFinder** (venta de juguetes y artículos de deporte), analiza el rendimiento real de las keywords/combinaciones de búsqueda de las campañas activas, y **aplica cambios de puja automáticamente** (sin aprobación manual) para mejorar el rendimiento publicitario con el tiempo.

No es un dashboard ni un generador de listas de keywords: es un sistema de decisión que actúa directamente sobre la cuenta, aprendiendo de sus propias decisiones pasadas.

## Objetivo de negocio

- **ACOS objetivo: 30-35%.** El ACOS (Advertising Cost of Sale) mide cuánto se gasta en publicidad por cada euro de venta que esa publicidad genera (gasto en ads / ventas atribuidas a ads). Por debajo del rango = rentable, subir puja. Por encima = no rentable, bajar o pausar.
- Escala actual: ~2 campañas activas.
- **Presupuesto máximo: 630€/mes** en total (3 campañas a 7€/día; subido desde 100€/mes por Juan el 26/09/2026). El sistema nunca debe empujar el gasto proyectado por encima de este límite (ver Reglas de seguridad).

## Antes de empezar: pregunta primero

**Cualquier sesión de Claude Code que abra este proyecto debe preguntarle a Juan todo lo que necesite saber ANTES de escribir o ejecutar nada** — no asumir, no rellenar huecos por iniciativa propia, y menos aún ejecutar cambios reales contra la cuenta de Amazon Ads sin haber confirmado antes lo siguiente:

- **Los números marcados como "asumido" o "ajustable" en este documento** (ACOS objetivo 30-35%, presupuesto mensual 630€, fondo de exploración 20€/mes, tope de 3 keywords nuevas/día, tope de 3 experimentos/día, puja inicial de experimento 0,30€, stop-loss al 50%) — estos salieron de conversaciones anteriores con Juan, pero conviene reconfirmarlos antes de que muevan dinero real, sobre todo si ha pasado tiempo desde que se escribieron.
- **Si `.auth/session.json` existe y está viva** — si no, hay que guiar a Juan por `capture_session.py` antes de intentar leer nada.
- **Si `ANTHROPIC_API_KEY` está configurada** — sin ella, `keyword_generator.py` (los experimentos) no funciona; preguntar si Juan la tiene lista o si prefiere dejar los experimentos desactivados de momento.
- **El estado real de la cuenta de Ads en ese momento** — la última vez que se miró, las campañas estaban pausadas por un problema de saldo en Seller Central (ver "Notas importantes"). Antes de activar nada, preguntar si eso ya se resolvió.
- **Cualquier selector de Playwright que siga con `NotImplementedError`** — no adivinarlos ni inventarlos: pedirle a Juan que abra el navegador (`headless=False`) contigo, o usar el navegador ya conectado si la sesión lo permite, e inspeccionar el HTML real antes de escribir el scraper de esa parte.
- **Cualquier cosa de este documento que resulte ambigua o contradictoria** al releerlo — mejor preguntar en un mensaje corto que adivinar y aplicar algo que luego haya que deshacer.

Una vez confirmado lo anterior, se puede proceder con el resto del documento.

## El agente de marketing "piensa" de verdad — no es un script de reglas fijas

**Importante: la decisión no la toma un `if/else` con umbrales fijos.** Cada día, `ai_marketing_agent.py` le pasa a Claude (vía API) todos los datos reales — keywords, ACOS, histórico de aciertos, presupuesto restante, cupos del día — y le pide que razone y proponga acciones con su propio criterio, como lo haría un gestor de PPC humano mirando la cuenta. `analyzer.py` sigue existiendo como referencia de las reglas de negocio (y se usa para el harvesting y el stop-loss, que sí son deterministas), pero ya no es lo único que decide sobre pujas y experimentos.

**Esto NUNCA significa que la IA pueda gastar lo que quiera.** Todo lo que la IA propone pasa por `sanitize_commands()` (en `ai_marketing_agent.py`) antes de ejecutarse — esta es una capa que **nunca se salta**:
- Una subida/bajada de puja se recorta siempre al ±20% real (`capped_new_bid`), nunca al valor que la IA pida.
- Una keyword nueva o un experimento respetan siempre el tope diario (`MAX_NEW_KEYWORDS_PER_DAY`, `MAX_NEW_EXPERIMENTS_PER_DAY`), aunque la IA proponga más.
- La puja inicial de un experimento es siempre `EXPERIMENT_STARTING_BID_EUR` fija, nunca lo que la IA sugiera.
- El reset de 24h y el presupuesto mensual se comprueban igual que siempre, sin excepción.
- Cualquier acción sobre una keyword que no existe, o cualquier `action` que no sea una de las reconocidas, se descarta directamente.

En resumen: **la IA decide el QUÉ y el POR QUÉ, `safety.py` decide los límites del CUÁNTO** — y esa segunda capa manda siempre, pase lo que pase en la primera.

El stop-loss de experimentos activos (`monitor_experiments`) sigue siendo una regla dura y determinista, no pasa por la IA — una vez algo demuestra que no funciona, se mata siempre igual, sin margen de interpretación.

## Dónde vive esto realmente (para que quede claro)

Nada de esto corre "dentro de Claude" de forma continua. El flujo real:
1. Este código se escribe una vez (con Claude Code, Cursor, o el editor que prefieras — da igual cuál).
2. `run_daily.py` es un script de Python normal, programado vía cron/Task Scheduler en tu ordenador o un servidor pequeño.
3. Cada día, el sistema operativo lo lanza, el proceso hace su trabajo (lee, decide, ejecuta) y **termina**. No queda nada corriendo de fondo.
4. La única llamada a Claude es una petición corta y aislada a la API cada vez que hace falta razonar (una vez al día por campaña, aproximadamente) — no una conversación larga que se degrada con el tiempo. Cada llamada empieza de cero.

**Un límite honesto que hay que tener claro:** las llamadas a la API de Claude no tienen memoria propia — el modelo no se reentrena ni "aprende" en el sentido literal entre ejecuciones. Lo que hace que el sistema se comporte como si aprendiera es que cada día le pasamos en el prompt un resumen de lo que ya sabemos (la tasa de acierto de `learner.py`, el histórico importado) — es memoria externa que nosotros mantenemos, no memoria interna del modelo. Si ese contexto dejara de pasarse, el comportamiento "aprendido" desaparecería de golpe.

También hay que controlar la aleatoriedad explícitamente: las llamadas usan `temperature` bajo (0,2) para las decisiones de pujas (consistencia, dinero real) y alto (0,9) para generar ideas de experimentos (ahí sí interesa variedad). Ojo: temperatura baja reduce mucho la variación entre llamadas, pero no es un determinismo perfecto garantizado al 100%.

## Arquitectura: los agentes y su frontera

- **`browser_agent.py`** (subagente): el único que toca Internet. Lee las tablas de Amazon Ads (scraping) y ejecuta cambios (pujas, keywords nuevas, pausar experimentos). No decide nada — solo hace lo que se le ordena, y solo confirma que una orden se aplicó de verdad releyendo la página tras ejecutarla.
- **`ai_marketing_agent.py`**: Claude razonando sobre los datos reales cada día, vía API — propone qué hacer. Nunca importa Playwright ni sabe que existe un navegador detrás.
- **`sanitize_commands()`** (dentro de `ai_marketing_agent.py`): la barrera de seguridad que nunca se salta — recorta o descarta lo que la IA proponga si se sale de los límites de `safety.py`.
- **`marketing_agent.py`**: la parte determinista que NO pasa por la IA — el harvesting de términos de búsqueda con datos reales y el stop-loss de experimentos activos. Sigue existiendo porque esas dos cosas son reglas de negocio fijas, no criterio a interpretar.
- **`commands.py`**: el contrato `Command` que usan ambos flujos (IA y determinista) para hablar con el subagente.
- **`commands.py`**: el contrato entre los dos — un `Command` lleva todo lo que el subagente necesita para ejecutar y registrar, sin tener que volver a preguntarle nada al agente de marketing a mitad de la ejecución.
- **`run_daily.py`**: el orquestador. Llama al subagente para leer, pasa esos datos al agente de marketing para decidir, y vuelve a llamar al subagente para ejecutar cada orden.

Esta separación significa que si el día de mañana se sustituye el subagente por uno que hable con la Amazon Ads API oficial en vez de hacer scraping, `marketing_agent.py` no cambia ni una línea — solo le siguen llegando las mismas listas de datos.

## Fuente de datos y acceso

Amazon Ads Console (`advertising.amazon.es`) — vista **Campañas** de FreshFinder (entidad `ENTITY255IACS8436WD`). Datos relevantes por ejecución:

- Tabla de campañas: coste, ventas, ROAS, compras, clics, CTR, CPC por campaña.
- Dentro de cada campaña → grupo de anuncios → **segmentación / keywords**: puja actual, clics, coste, ventas, ACOS por keyword.
- **Segmentación negativa** (para no repetir pujas ya descartadas).

**Acceso: automatización de navegador (Playwright), no la Amazon Ads API oficial.**

Juan no tiene registrada la app de la Amazon Ads API (eso exige alta como desarrollador, aprobación de Amazon y credenciales OAuth — fricción que no queremos ahora mismo). En su lugar, el sistema navega la Ads Console ya autenticada, igual que se hizo para validar este proyecto:

1. **Sesión guardada una vez, manualmente.** Juan inicia sesión en `advertising.amazon.es` en un navegador controlado por Playwright (`playwright codegen` o un script de login puntual), y el script guarda el `storage_state` (cookies + tokens de sesión) en un archivo **fuera del repo** (p. ej. `.auth/session.json`, en `.gitignore`).
2. **Cada ejecución diaria reutiliza esa sesión guardada** para abrir la Ads Console sin volver a hacer login.
3. El script **extrae los datos por scraping** de las tablas (Campañas → grupo de anuncios → keywords), no por API — es decir, lee el DOM de la página igual que lo haría una persona.
4. Para **aplicar un cambio de puja**, el script navega al campo de puja de la keyword, lo edita y guarda, tal como lo haría Juan a mano.

**Riesgos a tener en cuenta (y por qué la API sigue siendo la opción "correcta" a futuro):**
- La sesión guardada caduca (Amazon fuerza reautenticación periódicamente) → el script debe detectar un login fallido y avisar a Juan en vez de fallar en silencio.
- Amazon puede cambiar el HTML de la Ads Console en cualquier momento → romper el scraping sin previo aviso. El script debe fallar de forma visible (log + aviso), nunca asumir que un scrape vacío significa "sin actividad".
- El scraping automatizado de acciones que mueven dinero (cambiar pujas) es más frágil que una API oficial — cualquier fallo a mitad de una acción de escritura debe dejar el sistema en un estado seguro (no aplicar el cambio parcialmente).
- Si más adelante Juan registra la Amazon Ads API, migrar es sencillo: la lógica de negocio (`analyzer.py`, `learner.py`, `safety.py`) no cambia, solo se sustituye `browser_agent.py` por `ads_api.py`.

## Lógica de decisión (diaria)

Ejecución programada **una vez al día**. En cada ejecución:

1. **Leer el histórico** (`logs/decisions.jsonl`) antes de decidir nada — ver sección "Cómo aprende el sistema".
2. **Abrir la sesión guardada de Ads Console** (Playwright) y comprobar que sigue autenticada; si no, detener la ejecución y avisar a Juan (no reintentar login automáticamente).
3. **Extraer los datos por scraping**: tabla de campañas + tabla de keywords por grupo de anuncios (puja actual, clics, coste, ventas → ACOS calculado).
4. Para cada keyword/combinación activa, calcular su ACOS actual y compararlo con el objetivo (30-35%):
   - **ACOS bajo objetivo** (rentable) → candidata a subir puja.
   - **ACOS por encima del objetivo** → candidata a bajar puja o pausar (si lleva mal varias veces seguidas, ver aprendizaje).
   - **Sin datos suficientes** (pocos clics) → no tocar todavía, dejar madurar.
5. **Ajustar la agresividad del cambio según el histórico de esa keyword concreta** (no todas las keywords se tratan igual — ver siguiente sección).
6. **Aplicar los límites de seguridad** (tope de cambio, reset 24h, presupuesto mensual) antes de ejecutar nada.
7. **Ejecutar los cambios navegando y editando el campo de puja en la UI** (no vía API). Confirmar visualmente (screenshot o lectura del DOM tras guardar) que el cambio se aplicó antes de darlo por hecho.
8. Escribir cada cambio en el log.
9. Actualizar en el log los resultados de cambios de días anteriores (para que el próximo ciclo de aprendizaje los tenga en cuenta).

## Cómo aprende el sistema

El log no es solo un registro — es la memoria que el sistema consulta **antes** de cada decisión. Pero para que sirva de algo, alguien tiene que **volver a comprobar qué pasó** después de cada cambio — eso es lo que hace `learner.update_pending_results()`, y es el primer paso de cada ejecución diaria, antes de pedirle nada nuevo a la IA:

1. Cada vez que se sube o baja una puja, se guarda una "foto" del rendimiento de esa keyword EN ESE MOMENTO (`clics_base`, `coste_base`, `ventas_base`) junto con la decisión — sin esto no se podría aislar el efecto de ESE cambio concreto del resto del histórico.
2. Pasados al menos 3 días (`min_days`) y con al menos 10 clics nuevos desde entonces (`min_new_clicks` — mismo umbral que para decidir, para no evaluar con ruido), se calcula el rendimiento incremental: `coste_actual - coste_base`, `ventas_actual - ventas_base`, y el ACOS de esa diferencia.
3. Se escribe el veredicto (`"mejora"` o `"empeora"`) directamente en esa línea del log — a partir de ahí, esa decisión ya cuenta hacia la tasa de acierto de la keyword.
4. **Una decisión todavía sin evaluar no cuenta ni como acierto ni como fallo** — la agresividad se queda neutra (0,5) hasta que haya datos reales, nunca se penaliza por defecto.

**El aprendizaje se indexa por producto (SKU/ASIN) + keyword, nunca por campaña.** La misma palabra clave puede promocionar productos distintos en campañas distintas, y puede funcionar genial para uno y mal para otro — si el histórico se mezclara entre productos, el sistema aprendería una media borrosa que no sirve para ninguno. El SKU/ASIN se lee de la pestaña "Anuncios" de cada grupo de anuncios (normalmente un único producto por grupo). La campaña se guarda en el log solo para trazabilidad humana, nunca para agrupar el aprendizaje.

Ese histórico ya evaluado es lo que:

- Nº de subidas/bajadas/pausas aplicadas a esa keyword.
- Qué pasó después de cada una (¿el ACOS mejoró o empeoró tras el cambio?).
- Una "tasa de acierto" reciente: de las últimas N subidas de puja en esta keyword, cuántas resultaron en mejora de ACOS.

Esa tasa de acierto ajusta el comportamiento:

- Keyword con histórico de responder bien a subidas → el sistema puede acercarse más al tope máximo permitido de cambio.
- Keyword que ha empeorado tras subidas repetidas → el sistema se vuelve conservador con ella aunque las métricas del día actual parezcan buenas.
- Keyword con 2+ pausas seguidas por mal rendimiento → **no se reactiva automáticamente**; se marca en el log como `requiere_revision: true` para que Juan la vea.

Con solo 2 campañas el aprendizaje será lento al principio (hace falta historial mínimo), pero la lógica ya está lista para escalar cuando haya más volumen de campañas y datos.

## Reglas de seguridad (no negociables, van antes que cualquier "optimización")

1. **Tope de cambio por ejecución:** máximo ±20% sobre la puja actual de una keyword en una misma ejecución.
2. **Reset de 24h:** una vez aplicado un cambio a una keyword/combinación, no se le vuelve a tocar hasta que hayan pasado 24h completas desde el último cambio.
3. **Presupuesto mensual duro: 630€** (cartera de Amazon con ese tope; antes 100€, cambiado por Juan el 26/09/2026). Antes de aplicar cualquier subida de puja, calcular el gasto proyectado del mes con los reportes de Campaign Report. Si el proyectado ya roza el límite, no se suben más pujas ese mes aunque el rendimiento lo justifique — solo se permiten bajadas/pausas.
4. Ninguna acción que no esté explícitamente cubierta por estas reglas (crear campañas nuevas, cambiar targeting, cambiar presupuestos diarios, etc.) se ejecuta sin que Juan lo pida explícitamente en el momento.

## Formato del log — `logs/decisions.jsonl`

Un archivo JSON Lines (una línea = un JSON válido = un evento). Se elige por ser ligero, versionable en git, legible por humano y máquina, sin dependencias de base de datos — apropiado para la escala actual (2 campañas). Si el proyecto escala a muchas más campañas, migrar a SQLite sin cambiar la lógica de negocio.

`producto` (SKU o ASIN) es el campo que usa el aprendizaje para agrupar — `campana` se guarda solo para que un humano pueda rastrear de dónde vino el cambio.

Ejemplo de línea (cambio aplicado):
```json
{"fecha": "2026-09-24", "producto": "B0DHYBY6MS", "campana": "Campaña - 27/6/2025 18:41:26.479", "keyword": "soporte movil coche", "tipo_cambio": "subida_puja", "valor_antes": 0.51, "valor_despues": 0.61, "motivo": "ACOS 22% (bajo objetivo 30-35%), 8 clics, 2 ventas", "resultado_siguiente": null}
```

Ejemplo de línea (resultado actualizado un día después):
```json
{"fecha": "2026-09-24", "producto": "B0DHYBY6MS", "campana": "Campaña - 27/6/2025 18:41:26.479", "keyword": "soporte movil coche", "tipo_cambio": "subida_puja", "valor_antes": 0.51, "valor_despues": 0.61, "motivo": "ACOS 22% (bajo objetivo 30-35%), 8 clics, 2 ventas", "resultado_siguiente": {"clics": 11, "ventas": 3, "acos_real": 19.5, "evaluacion": "mejora"}}
```

## Estructura del proyecto

```
/
├── CLAUDE.md                  # este archivo
├── .auth/
│   └── session.json           # storage_state de Playwright (cookies de sesión) — NUNCA en git
├── logs/
│   └── decisions.jsonl        # histórico de decisiones y resultados
├── src/
│   ├── browser_agent.py       # SUBAGENTE: Playwright — lee y ejecuta, nunca decide
│   ├── ai_marketing_agent.py  # Claude razona y propone + sanitize_commands (barrera dura)
│   ├── marketing_agent.py     # solo stop-loss (determinista) + modo alternativo sin IA
│   ├── keyword_generator.py   # generador de ideas standalone (usado por el modo sin IA)
│   ├── commands.py            # contrato Command entre agente(s) y subagente
│   ├── analyzer.py            # reglas de ACOS, harvesting y stop-loss (referencia + modo sin IA)
│   ├── learner.py             # histórico por producto+keyword, experimentos activos
│   ├── safety.py              # límites: puja, presupuesto, keywords/día, stop-loss
│   ├── capture_session.py     # login manual único, genera .auth/session.json
│   └── run_daily.py           # orquestador: subagente lee -> marketing decide -> subagente ejecuta
├── .gitignore                  # debe incluir .auth/ y logs/ si se quiere mantener privado
└── README.md
```

## Descubrimiento de nuevas keywords: dos mecanismos distintos

**1. Harvesting (keywords cosechadas de datos reales)** — ver más abajo, `AÑADIR_KEYWORD`. Promueve términos de búsqueda que YA tienen clics y ventas reales en la campaña automática. No es una apuesta: la puja se basa en datos que ya existen.

**2. Experimentos (keywords 100% inventadas, sin datos previos)** — `GENERAR_EXPERIMENTO` / `MATAR_EXPERIMENTO`. Esto SÍ es una apuesta deliberada: Juan quiere que el sistema se atreva a probar frases que nadie ha buscado todavía en sus anuncios, para aprender qué funciona más allá de lo obvio. Como es dinero gastado sin ninguna garantía, tiene su propio circuito de seguridad, separado del resto:

- **Generación**: `keyword_generator.py` llama a la API de Claude (requiere `ANTHROPIC_API_KEY` propia, ver README) con el título y categoría del producto, y el listado de todo lo ya probado (para no repetir), y devuelve frases nuevas en español, coincidencia **Frase**.
- **Tope diario**: máximo **3 experimentos nuevos por ejecución**, contado de forma **global** (no por campaña) — `MAX_NEW_EXPERIMENTS_PER_DAY`.
- **Fondo de exploración**: **20€/mes** (`EXPLORATION_FUND_MONTHLY_EUR`, asumido de esta conversación — ajustable), repartido entre los experimentos del día → cada uno tiene un presupuesto asignado de `20€ / 3 ≈ 6,67€`.
- **Stop-loss**: si un experimento acumula gasto por encima del **50% de su presupuesto asignado (≈3,33€) sin ninguna venta**, se pausa inmediatamente — no espera al día siguiente ni a que acabe el mes. Basta con que tenga aunque sea 1 venta para librarse de esta regla; a partir de ahí pasa a tratarse como cualquier keyword normal (vía `decide_base_action`).
- **Puja inicial**: conservadora y fija, `EXPERIMENT_STARTING_BID_EUR = 0,30€` — no hay ningún dato previo del que partir, así que no se calcula, se asume un valor bajo por defecto.
- Cada ejecución diaria, ANTES de generar experimentos nuevos, se revisan los que ya están activos (`learner.get_active_experiments()`) y se les aplica el stop-loss — así una mala idea no sobrevive ni un día de más de lo permitido.

## Harvesting (keyword cosechada de un término de búsqueda real)

Además de ajustar pujas de keywords ya existentes, el sistema **se atreve a crear keywords nuevas** a partir de términos de búsqueda reales de clientes (pestaña "Términos de búsqueda" de cada campaña — no confundir con la lista de keywords ya configuradas).

**Reglas, más exigentes que las de ajustar una keyword existente** (crear algo nuevo pesa más que tocar algo que ya existe):
- Nunca duplica: si el término ya existe como keyword en cualquier tipo de coincidencia, se ignora.
- Mínimo 5 clics para tener señal (`MIN_CLICKS_FOR_NEW_KEYWORD`).
- Mínimo 1 compra real — tráfico sin ninguna venta nunca se promueve, por muchos clics que tenga (eso es candidato a negativizar, no a promover; la negativización automática no está implementada todavía, es una mejora futura).
- El ACOS del propio término debe estar dentro o por debajo del objetivo (30-35%) — un término que convierte pero ya gasta de más no es buen candidato a que le des puja propia.
- Se añade siempre en coincidencia **Exacta** (la más predecible, evita "difuminar" el término).
- Puja inicial = el CPC medio que ya pagaba ese término como parte de la campaña automática (`new_keyword_bid()`), no un valor arbitrario.

**Límite de seguridad propio:** máximo **3 keywords nuevas por ejecución** (`MAX_NEW_KEYWORDS_PER_DAY`) — evita que el sistema se dispare creando decenas de keywords de golpe si un día hay muchos candidatos. El resto se reevalúan al día siguiente.

Cada keyword nueva se registra en el mismo log (`decisions.jsonl`, `tipo_cambio: "añadir_keyword"`), indexada por producto igual que el resto — así, si esa keyword nueva no rinde bien después, el aprendizaje ya tiene su historial desde el primer día.

## Importar histórico real (rendimiento de antes de este sistema)

Juan puede tener rendimiento real de keywords de antes de que este agente existiera — no tiene sentido que la IA empiece a ciegas si esos datos ya están ahí. `import_historical_data.py` los incorpora como contexto:

```bash
python src/import_historical_data.py export.csv --producto B0DHYBY6MS --campana "Campaña - 27/6/2025 18:41:26.479" --ad-group Auto
```

- El CSV es el export real de la tabla de Segmentación de Amazon Ads (botón "Exportar" que vimos en la cuenta) — columnas en español: Palabra clave, Tipo de coincidencia, Puja, Impresiones, Clics, Coste total, Compras, Ventas.
- `--producto` es obligatorio y hay que pasarlo a mano: el export de esa tabla no incluye el SKU/ASIN (eso está en la pestaña "Anuncios" aparte) — como un grupo de anuncios normalmente promociona un único producto, se indica una vez por import.
- Se guarda en `logs/historical_keywords.json`, **separado de `decisions.jsonl` a propósito**: uno es rendimiento real que ya existía, el otro son decisiones que ha tomado este sistema y evaluado — nunca se tratan como lo mismo.
- Por defecto se va **añadiendo** a lo ya importado (útil para ir sumando exports de varios grupos de anuncios/productos); `--reemplazar` lo sustituye entero si hace falta.
- `ai_marketing_agent.py` lo incluye automáticamente en el contexto que ve la IA cada día, filtrado a los productos que se están evaluando en ese momento — instruido explícitamente para tratarlo como una señal fuerte, no como ruido de fondo.

## Estado actual / pendiente

- [ ] Juan genera la sesión inicial de Playwright (login manual una vez, guardar `storage_state` en `.auth/session.json`).
- [ ] Confirmar rango de ACOS objetivo (30-35% propuesto, ajustable).
- [ ] Primera ejecución en modo lectura únicamente (sin aplicar cambios) para validar que el scraping lee correctamente las tablas de campañas, keywords y términos de búsqueda.
- [ ] Activar aplicación de cambios reales (pujas y keywords nuevas) tras validar.
- [ ] (Opcional, futuro) Si Juan registra la Amazon Ads API más adelante, migrar `browser_agent.py` → `ads_api.py` sin tocar `analyzer.py` / `learner.py` / `safety.py`.
- [ ] (Opcional, futuro) Integrar Helium 10 como fuente de datos adicional (investigación de keywords de mercado, no solo el propio rendimiento de FreshFinder) — existe un conector MCP de Helium 10 usable en chat, pero para `run_daily.py` (script standalone por cron) hace falta integrar su API REST directamente, un módulo nuevo tipo `helium10_source.py` que aporte contexto extra a `ai_marketing_agent.py`, igual que hace `import_historical_data.py`.

## Notas importantes

- Este sistema opera con dinero real sobre la cuenta de Amazon Ads de FreshFinder. Cualquier cambio en las reglas de seguridad (tope de cambio, presupuesto, frecuencia) debe pedirlo Juan explícitamente — no se relajan por iniciativa propia aunque el rendimiento parezca justificarlo.
- FreshFinder tuvo una suspensión de cuenta de Amazon Seller en septiembre 2026 por temas de DAC7/VAT. Además, a fecha de creación de este documento, **todas las campañas de Ads están en pausa porque Amazon no pudo cargar los anuncios contra el saldo de la cuenta de vendedor** (reserva de saldo en la entidad de Bélgica). El sistema debe operar asumiendo que esto puede repetirse: si detecta que todas las campañas aparecen en pausa sin que el propio sistema las haya pausado, debe registrarlo y avisar en vez de intentar "reactivar" nada por su cuenta — eso es una decisión de negocio de Juan, no del optimizador.
- Cualquier cambio de account status (suspensión, "en riesgo", pago rechazado) debe hacer que el sistema se detenga y avise en vez de seguir operando a ciegas.
