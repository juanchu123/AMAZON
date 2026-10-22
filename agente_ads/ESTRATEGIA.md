# Estrategia acordada con Juan

Documento vivo: lo que Juan y el Agente ADS acuerdan por correo sobre hacia dónde van los anuncios. El agente
lo relee en cada ronda y lo respeta; cuando algo cambia, lo actualiza con la fecha y enlaza el hilo del correo.

## Objetivo
- ACOS objetivo 30-35 % (nunca por encima del de equilibrio de cada producto: hoja Economía).
- Tope 840 €/mes (directivas.json). Hoy se gasta mucho menos (~4-5 €/día): hay margen para crecer en cuanto
  algo demuestre que vende.

## Márgenes de Juan (correo del 09/10/2026, hilo [Agente ADS] "Hola Juan")
- Pinza: gana **3,67 €** por unidad antes de publicidad (ticket ~11,24 €) → **ACOS de equilibrio 32,7 %**.
- Rejilla: gana **3,03 €** (ticket ~14,27 €) → **ACOS de equilibrio 21,2 %**.
- Ninguna puja puede pasar de P(compra|clic) × ticket × equilibrio (el motor las baja sin esperar a la ronda).

## Prioridades (09/10/2026)
1. **Rejilla:** cortar el gasto en búsquedas ajenas de la automática y apostar por donde vende: páginas de
   producto de competidores (ASIN B0F3J3QHD7 en prueba) y términos que han vendido (cosecha a Exacta).
2. **Pinza (Juan, 09/10: "cuanto antes, pero sin gastar mucho"):** vuelve "Pinza - Principal V2" a 3 €/día
   con las pujas bajadas al equilibrio (0,35-0,42 €). **Límite de Juan: si la pinza gasta más de 5 € en
   conjunto desde el 09/10 sin ganar nada, el agente la reestructura como quiera** (directivas.json, "limites";
   el motor avisa con "LÍMITE DE JUAN SUPERADO"). Ganar = ventas × 3,67 € > gasto.
3. **Aprender rápido y barato:** negativas de vocabulario ajeno, pruebas con pérdida limitada, 14 días antes
   de juzgar pujas.
4. **Preparar Black Friday (27/11) y Navidad/Reyes** desde finales de octubre (CALENDARIO.md).

## Cupones (Juan, 09/10: "gestiona tú los cupones")
- El agente no tiene acceso a Seller Central: **propone** el cupón (producto, %, fechas, por qué) y Juan lo crea.
- Con estos márgenes un cupón sale caro: 10 % en la rejilla se come 1,43 € de 3,03 € (equilibrio al ~11 %);
  10 % en la pinza deja 2,55 € (equilibrio ~23 %), y Amazon cobra además una tarifa por canje.
- Criterio: sin cupón mientras los anuncios no sean rentables; probar uno pequeño (5 %) en la pinza solo si
  convierte y le falta empuje, y valorarlo para Black Friday / Navidad (propuesta a finales de octubre).

## Pendiente de hablar con Juan
- Rejilla: con su margen solo es rentable un clic de ~0,15-0,30 €. Si a esas pujas no hay tráfico, decidir
  con Juan: subir precio, bajar coste, o anunciarla solo donde vende (páginas de producto de la competencia).

## Semana del 12/10 (informe enviado a Juan)
- Desde las pujas al equilibrio (09-11/10): ACOS 26 %, CPC 0,29 € (antes 0,52 €). Vende desde fichas de competencia y Exactas cosechadas; no vende en genéricas en amplia.
- Plan propuesto (pendiente de Juan): pinza -> decisión el lunes 19/10 (si la V2 no vende, solo Exactas específicas ~0,30 € y el dinero a fichas de competencia); rejilla -> solo fichas de competencia + Exactas (+2-3 ASIN de competidores a ~0,25 €); Black Friday -> como mucho cupón 5 % en la pinza 20/11-2/12.

## Plan B: comprar visibilidad (Juan, 18/10/2026: "Hagamos el plan B")
- Por qué: con pujas al equilibrio la cuenta casi no gastaba (0-1 €/día del 13 al 17/10). Juan elige perder un poco
  a cambio de ventas y reseñas antes de Black Friday.
- Tope: **10 € de pérdida a la semana** (gasto − ventas × margen), la cifra del ejemplo del correo; Juan no dio otra.
- Pujas fijadas a 0,40 € en lo que ya ha vendido: automática "substitutes" (rejilla), exacta "soporte teléfono coche"
  (rejilla), ASIN B0F3J3QHD7 (rejilla), B08N4KR6PK y B09P3SZB6P (pinza). Del 18/10 al 02/12/2026.
- Lo aplica el motor (directivas.json → "visibilidad"): mientras la pérdida de la semana no llegue al tope, esas
  pujas se mantienen; si llega, el plan se para solo hasta el lunes y las pujas vuelven al equilibrio.
- Revisión cada lunes: si con 0,40 € siguen sin clics y sobra tope, subir a 0,45-0,50 €; si alguna pierde sin vender
  (stop-loss de siempre: 20 clics o 4 € sin venta), sale del plan.

## Cupón de Black Friday (Juan, 18/10/2026: "Haz el cupón")
- Propuesta enviada: pinza B0DCZS1NR6, 5 %, del 20/11 al 02/12/2026, un canje por cliente, presupuesto 20 €.
  Rejilla sin cupón (5 % se come 0,71 € de 3,03 €). Lo crea Juan en Seller Central antes del 30/10.

## Semana del 19/10 (informe enviado a Juan)
- 12-18/10: 5,93 € y 0 ventas por anuncios (semana anterior 23,11 € y 5 ventas): las pujas al equilibrio cortaron gasto y ventas.
- Propuesto: plan B en marcha (pendiente de que Juan suba el Excel); la automática a 0,40 € para descubrir fichas de
  competencia que vendan y pasarlas a segmentación por ASIN; 0,50 € en lo que venda la semana de Black Friday; preguntar
  a Juan por subir 1 € el precio de la rejilla (margen 3,03 € → ~4 €, clic rentable de ~0,26 € a ~0,35 €).
- 22/10: el Excel del plan B llegó dañado (base64 mal copiado) y Juan puso las 5 pujas a 0,40 € a mano (~19-20/10).
  Primera venta del plan: rejilla 10,74 € el 20/10 en la automática, desde la ficha B0C1NK79FK (candidata a ASIN
  propio si vuelve a vender). Pérdida de la semana: 0,79 € de 10 €.
