# FreshFinder — Agente autónomo de Amazon Ads

## Qué es esto

Un agente que se conecta a la cuenta de Amazon Ads de **FreshFinder** (artículos de coche y juguetes en Amazon.es), lee el rendimiento real de campañas, keywords y ASIN, y **actúa por sí solo**: ajusta pujas, pausa lo que pierde dinero, añade keywords nuevas, reparte el presupuesto entre campañas y abre campañas nuevas cuando los datos lo justifican. Cada cambio se verifica releyendo Amazon, queda registrado en un documento único y se avisa a Juan por correo.

La especificación completa (decidida con Juan el 26-27/09/2026) está en **`AGENTE_AUTONOMO.md`**. Este archivo resume lo que cualquier sesión de Claude Code tiene que saber antes de tocar nada.

## Objetivo de negocio

- **ACOS objetivo: 30-35 %** (gasto en ads / ventas atribuidas a ads). Keyword nueva: solo con ACOS predicho ≤ 30 %.
- **Tope duro: 840 €/mes** (cartera de Amazon; 100 € → 630 € → 840 €, cambiado por Juan el 26/09/2026). Solo Juan lo cambia (`config.TOPE_MENSUAL_EUR`, `crear_memoria.CARTERA_MENSUAL`, este archivo y `marketingV2.md`).
- **20 % del tope (168 €/mes) para experimentación**, global; **80 %** para lo que ya funciona, según puntuación por campaña.

## Antes de empezar: pregunta primero

Cualquier sesión que abra este proyecto pregunta a Juan lo que necesite **antes** de ejecutar nada contra la cuenta real:

- **Credenciales de la Amazon Ads API** (`AMAZON_ADS_CLIENT_ID`, `AMAZON_ADS_CLIENT_SECRET`, `AMAZON_ADS_REFRESH_TOKEN`, opcional `AMAZON_ADS_PROFILE_ID`). Van en variables de entorno de SU ordenador. **Nunca pedirle que las pegue en el chat ni subirlas a git.**
- **Estado real de la cuenta**: la última vez, todas las campañas estaban en pausa (saldo de Seller Central). Con todo en pausa el agente avisa y se para: es lo correcto.
- **Correo** (`SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`; con Gmail, contraseña de aplicación) y, si se quiere la investigación de mercado, `ANTHROPIC_API_KEY`.
- **La primera vez, `python agente.py --simular`**: decide y lo cuenta sin tocar Amazon ni crear tickets. Solo después, ejecuciones reales.
- Cualquier cosa ambigua o contradictoria: preguntar en un mensaje corto antes que adivinar.

## Arquitectura ("Camino A": reglas fijas, sin LLM decidiendo dinero)

```
agente.py  (orquestador: una ejecución = una ronda; se puede lanzar cuantas veces se quiera)
 ├─ fuente de datos (solo lee y ejecuta, no decide)
 │   ├─ ads_api.py     Amazon Ads API v3: listados + informe diario (Reporting API) + escritura con verificación
 │   └─ fuente_bulk.py sin API: lee la hoja masiva descargada y escribe bulk_cambios_<fecha>.xlsx para subir a mano
 ├─ documento.py      documento único (resultados/memoria_agente.xlsx), escritura atómica
 ├─ learner.py        veredicto de cada cambio (con clics maduros) y agresividad / confianza aprendidas
 ├─ analyzer.py       por keyword/ASIN: elegibilidad, ronda, stop-loss, puja, huecos hasta 12
 ├─ prediccion.py     por producto: ticket, conversión, modelo de keyword_ml.py, candidatas (ACOS predicho)
 ├─ presupuesto.py    reparto 80/20 del tope del día entre campañas
 ├─ campanas.py       ¿abrir campaña nueva? (solo si el 20 % da para pagarla de verdad)
 ├─ safety.py         última barrera: suelo de puja, tope mensual, cuenta parada. Nunca se salta
 ├─ alertas.py        un correo por ronda + avisos inmediatos (SMTP; si no hay, .eml pendiente)
 └─ investigacion.py  ÚNICO uso de un LLM: buscar y ordenar frases candidatas (solo datos)
config.py            todos los números
keyword_ml.py        modelo de machine learning de keywords (P(compra|clic)), perfiles de producto
crear_memoria.py     generador de campañas iniciales (memoria + bulk), usado por la skill crear-campana
legacy/              el sistema anterior (navegador + LLM decidiendo); ver legacy/README.md
```

Las reglas no saben de dónde vienen los datos: la API y la hoja masiva producen la misma estructura (`modelo.py`).

**Sobre las fechas:** los listados de la API no traen métricas. Las métricas salen del informe diario `spTargeting` (Reporting API v3), una fila por día y elemento, que se guarda en la hoja "Diario". Con ellas el agente sabe exactamente qué clics tienen más de 7 días. Con la hoja masiva (sin fechas por fila) se usan fotos diarias en "Seguimiento" y se resta entre fotos.

## Reglas de decisión (AGENTE_AUTONOMO.md §2)

1. **Elegibilidad (§2.7):** si el anuncio del grupo no se puede mostrar (sin Oferta Destacada, sin stock, ficha rechazada…) no se toca nada del grupo y se avisa.
2. **Ronda (§2.1):** un elemento solo se decide con **≥ 3 días** desde su último cambio **y ≥ 10 clics nuevos**. Clic **maduro** = más de 7 días (atribución de Amazon).
3. **Stop-loss (§2.4):** **20 clics maduros o 4 € maduros sin ninguna venta → pausar** (nunca borrar). Una venta lo libra. Pausada 2 veces → "Requiere revisión de Juan"; el agente **nunca reactiva nada**.
4. **Puja (§2.2):** `P(compra|clic) × ticket medio × ACOS objetivo`, con el ACOS entre 30 % y 35 % según la agresividad aprendida. P(compra|clic) = modelo de `keyword_ml.py` mezclado con los clics maduros propios. **Suelo 0,02 €, sin techo artificial**, estrategia "solo reducir".
5. **Huecos (§2.3):** máximo **12 keywords/ASIN activos por grupo**, cada producto por su cuenta; los huecos se rellenan con candidatas (histórico, modelo, investigación) con **ACOS predicho ≤ 30 %**. ASIN de competencia: solo los de la hoja "Competencia" con "Sí" de Juan.
6. **Presupuesto (§2.5):** tope del día = lo que permite no pasar de 840 €/mes; 20 % a experimentación a partes iguales, 80 % a campañas probadas por puntuación (ACOS de 30 días × confianza aprendida). Mínimo 1 €/día por campaña; nunca se pausa una campaña por presupuesto.
7. **Campañas nuevas (§2.6):** por defecto se añade a la campaña existente. Se abre una nueva (máx. 1 por ronda) solo si el producto no tiene ninguna, o todas están 12/12 y hay una candidata claramente buena (≤ 25 %), y además a cada campaña experimental le seguirían tocando ≥ 2,50 €/día.
8. **Verificación (§2.8):** cada cambio se aplica, se relee en Amazon y solo entonces queda "confirmado"; si no coincide, un reintento y "fallido". Cada cambio es independiente.

## Reglas de seguridad (no negociables)

1. **Tope mensual 840 €.** Si el gasto proyectado del mes ya llega al tope: solo bajadas y pausas.
2. **Cuenta parada (§2.9-bis):** si todas las campañas están en pausa sin que las pausara el agente, o Amazon marca un problema de cuenta o de pago → correo inmediato y **parar sin tocar nada**. Nunca se reactiva nada por iniciativa propia.
3. Nada fuera de estas reglas (negativas automáticas, Sponsored Brands/Display, ubicaciones, cambiar la cartera…) sin que Juan lo pida.
4. Cualquier cambio de estas reglas lo pide Juan explícitamente; no se relajan porque "los datos lo justifiquen".

## Aprendizaje (learner.py)

- Cada cambio guarda la "base" (acumulado en ese momento). Cuando hay ≥ 10 clics **maduros** después del cambio (y antes del siguiente), se escribe el veredicto "mejora"/"empeora" en el ticket. Sin evaluar = neutro.
- **Nivel keyword** (producto + keyword + coincidencia, nunca por campaña): `agresividad = 0,2 + 0,8 × tasa de acierto de las subidas` (0,5 sin historial).
- **Nivel campaña:** lo mismo con las subidas de presupuesto (¿más ventas al día con ACOS en objetivo?). Es la "confianza" que usa el reparto del 80 %.
- Un LLM no aprende entre llamadas: la memoria es el documento único.

## Documento único — `resultados/memoria_agente.xlsx`

Hojas: Leyenda, Resumen, Campañas, Segmentación, Seguimiento (fotos), Diario (API), Tickets, Competencia (**la edita Juan**), Investigación, Alertas, Histórico. Se escribe a un temporal y se sustituye al final (atómico), con copia `.bak`. Hay que commitearlo: es la memoria del agente. `resultados/memoria.xlsx` y `memoria_pou.xlsx` son la memoria de la etapa manual: no se pisan.

## Cómo se ejecuta

```bash
python agente.py --simular            # primera vez: no toca nada
python agente.py                      # API si hay credenciales; si no, la hoja masiva más reciente de datos/
python -m pytest tests/ -q            # tests con una API falsa
```
Programado con cron / Programador de tareas (o Cowork) en el ordenador de Juan: el proceso corre, decide, ejecuta y termina.

## Skills y rutina

- `crear-campana`: campañas iniciales con memoria + bulk (manual, en pausa).
- `investigar-keywords`: puntuar frases de Helium 10 con el modelo (manual).
- `revision-semanal` (rutina de los lunes en la nube): corre el agente con la hoja masiva de `datos/` y deja el informe.

## Estado actual / pendiente

- [ ] Juan: credenciales de la Amazon Ads API → primera ejecución `--simular` con la API real.
- [ ] Confirmar con un informe de Amazon el valor "Actualizar" de la columna Operación de la hoja masiva (modo sin API).
- [ ] Correo SMTP configurado (si no, los avisos quedan en `resultados/correos_pendientes/`).
- [ ] La conversión de los ASIN de competencia usa la media del producto (se refinará con datos reales de cada ASIN).
- [ ] Coste del producto y comisiones de Amazon para calcular el ACOS de equilibrio real.
- [ ] (Futuro) Negativas automáticas — aplazado por Juan.

## Notas importantes

- Dinero real. FreshFinder tuvo una suspensión de Seller en septiembre de 2026 (DAC7/IVA) y **todas las campañas quedaron en pausa** porque Amazon no pudo cobrar los anuncios del saldo de vendedor (reserva en la entidad de Bélgica). El agente asume que puede repetirse: con todo en pausa, avisa y se para.
- Productos con histórico: pinza (B0DCZS1NR6, 37 compras), rejilla (B0DHYBY6MS, 53), Pou (B0CPHXXHRQ, 1 → modelo no fiable, se usa su conversión media), ventosa (B0DSV986XY) y 3-en-1 (B0F746MFPQ) sin datos suficientes.
- Commits en español, en la rama de trabajo; sin PR salvo que Juan lo pida.
