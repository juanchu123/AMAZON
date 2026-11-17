# Lecciones — lo que ha funcionado y lo que no

El Agente ADS relee este archivo antes de decidir y lo amplía después de cada ronda en la que aprenda algo
(una línea por lección, con fecha y el dato que la apoya). Es la memoria "en palabras"; la memoria "en
números" es el aprendizaje de Python (hojas Tickets y Aprendizaje de la memoria).

## Del histórico (antes del agente, analizado el 30/09/2026)
- Las keywords **genéricas en concordancia amplia** se comieron el dinero: rejilla 918 € de 1.049 € (88 %),
  conversión 4,3 %, ACOS 154 %. "soporte para móvil coche" (amplia) gastó 523 € sola.
- Lo **específico** del producto convierte mucho mejor: grupo "Pinza" 11,1 % y ACOS 41 %; en la rejilla las
  específicas 7,0 % frente a 4,8 % y con CPC más barato.
- La **Exacta** convierte el doble que la amplia (rejilla 8,6 % frente a 4,3 %).
- Se pagaba **más de lo que se pujaba** (1,33-1,42 × la puja) con "al alza y a la baja": ahora "solo a la baja".
- La puja sugerida de Amazon se queda corta: se paga 2,35 × (rejilla) y 1,38 × (pinza) la "puja rec. baja".

## Octubre 2026
- 01-08/10: la automática de la rejilla se llevó el 77 % del gasto (27,83 € de 36,09 €) con muchos clics en
  búsquedas de cosas que no es (magnético, imán, camión, bandeja, bola RAM, ranura CD, otros idiomas).
  → 09/10: negativas de frase por vocabulario ajeno (hoja masiva del 09/10).
- 01-08/10: las 2 ventas de la rejilla vinieron de **páginas de producto** (substitutes): ASIN B0F3J3QHD7 y
  "gravity phone holder ne5241". Páginas de producto ACOS 22 %; resto de la búsqueda ACOS 165 %.
  → 09/10: prueba de segmentación por ASIN B0F3J3QHD7 a 0,30 € y fuera el +30 % del resto de la búsqueda.
- Pinza - Principal V2: 14 clics y 0 ventas antes de que Juan la pausara (a propósito).
- 09/10: con los márgenes de Juan (pinza 3,67 €, rejilla 3,03 €) la rejilla perdió dinero del 01 al 08/10:
  ~29 € de anuncios por 2 ventas (6,06 € de margen). La automática pagaba 0,40 € por clic en substitutes con
  una conversión del 6,5 % (31 clics, 2 ventas): el clic rentable era ~0,18 €. → Todas las pujas al equilibrio.
- 09/10: la regla "nunca pagar más del equilibrio" no puede esperar a la ronda (≥ 3 días y ≥ 10 clics): con
  poco tráfico una puja ruinosa duraría semanas. Ahora se aplica en cada ronda (solo baja, nunca sube) y
  cuenta las ventas ya vistas aunque los clics no hayan madurado (si no, ahogaría lo único que vende).
- 10/10: la cosecha calcula la conversión con el propio término y, con 1 clic y 1 venta, sale ~18 %: para una
  búsqueda genérica ("soporte teléfono coche") eso daba 0,55 € en Exacta. Corregido a mano a 0,26 € (conversión
  real de la rejilla en Exacta ~8,6 %). Pendiente: que el motor no fíe la conversión de la cosecha a 1-2 clics.
- 10/10: una negativa de frase en un grupo bloquea las keywords de ese grupo que la contienen ("holder" habría
  bloqueado "gravity phone holder ne5241"): revisar siempre negativas frente a keywords del mismo grupo.
- 10/10: SellerMate atribuye ventas con retraso (la del 08/10 apareció el 10/10): bajar siempre los 8 días.
- 11/10: Juan subió el Excel del 10/10 completo (comprobado en SellerMate). La negativa exacta de traslado solo
  vale si la Exacta recoge el término tal cual: "soporte teléfono móvil coche" no lo recoge "soporte teléfono
  coche" (vetado negarlo). Un ASIN recién creado no se juzga con la media del producto si su ficha ya vendió.
- 11/10: Juan cambió a mano las ASIN de Pinza - Pruebas a 0,40 €: antes de deshacer un cambio suyo, preguntar.
- 12/10: primera cosecha confirmada: "soporte teléfono coche" (Exacta 0,26 €) vendió al primer clic el 11/10 (ACOS 3 %).
- 12/10: tras pujas al equilibrio (09-11/10) ACOS 26 % frente a ~100 % del 01/10; el CPC bajó de 0,52 € a 0,29 €.
- 13/10: una campaña que aparece en pausa sin que la pausara el agente ni un Excel es decisión de Juan: va a
  `no_reactivar`, se quita de `reactivar` y se le pregunta; sus cambios pendientes salen del Excel. La pinza en
  búsquedas genéricas (Principal V2) gastó 3,47 € en 2 días, 12 clics, sin ventas; su única venta vino de una ficha
  de la competencia (B09P3SZB6P).
- 14/10: con todas las pujas al equilibrio (rejilla 21 %) la cuenta casi no sale: 0,21 € y 193 impresiones el 13/10.
  No pierde dinero, pero tampoco vende. Hay que buscar alcance donde la conversión es alta (fichas de la
  competencia que ya vendieron, exactas concretas) en vez de subir pujas genéricas.

## 18/10 — Los clics recientes sin venta no cuentan para el motor, pero sí para el dinero
B09P3SZB6P: el motor proponía subir de 0,40 a 0,43 € porque solo ve 2 clics maduros (más de 7 días) y 1 venta.
Pero los 9 clics de los últimos días (2,47 €) no han vendido, y la pinza ya pasó el límite de 5 € de Juan.
Hay que esperar a que maduren antes de subir: se veta la subida hasta el 25/10. Al revés, el 16/10 se vetó
bajarla con 1 venta en 5 clics; dos días después ya no se sostenía. Con tan pocos clics, los vetos deben ser cortos.

## 22/10 — Un Excel bien hecho puede llegar roto: comprobar lo que llega, no lo que se manda
El bulk del 19/10 estaba bien en disco, pero el adjunto copiado a mano en base64 llegó con bytes cambiados (desde el
3036) y Amazon lo rechazó entero («archivo no válido o dañado»). Juan acabó poniendo las pujas del plan B a mano. Desde
hoy el bulk lleva solo la hoja de Sponsored Products (la mitad de caracteres que copiar) y cada envío se verifica
releyendo el correo (RAW) con `agente_ads/comprobar_adjunto.py`. Si Juan dice «error» y adjunta un `report.xlsx`,
es el informe de errores de Amazon: leerlo antes de nada.
