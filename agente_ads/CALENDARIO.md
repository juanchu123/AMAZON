# Calendario comercial — España (Amazon.es)

El Agente ADS lo mira en cada ronda: qué viene en las próximas 4 semanas y en qué fase está cada evento.
Los soportes de móvil para coche son **compra útil y regalo barato**: suben con los **viajes en coche**
(verano, puentes, Semana Santa) y con los **regalos** (Navidad, Reyes, Día del Padre). En eventos de ofertas
(Black Friday, Prime) el CPC sube porque pujan todos.

Fechas marcadas con (?) hay que confirmarlas cuando Amazon las anuncie (el agente lo actualiza).

| Fecha | Evento | Por qué importa |
|---|---|---|
| 12/10/2026 (lunes) | Puente del Pilar | Viajes en coche |
| Octubre 2026 (?) | Prime Big Deal Days | CPC más alto; tráfico con ofertas |
| 1/11/2026 (domingo) | Todos los Santos | Viajes cortos |
| 20/11 – 2/12/2026 | **Black Friday (27/11) y Cyber Monday (30/11)** | El evento más caro del año |
| 6 – 8/12/2026 | Puente de la Constitución/Inmaculada | Viajes + primeras compras de Navidad |
| 1 – 22/12/2026 | **Navidad** (regalos; último envío ~20/12) | Regalo barato |
| 26/12/2026 – 5/1/2027 | **Reyes** (6/1) | Regalo; fuerte en España |
| 7/1/2027 | Rebajas de invierno | Búsqueda de precio |
| 14/2/2027 | San Valentín | Poco relevante |
| 19/3/2027 | Día del Padre | Regalo para conductores |
| 25 – 28/3/2027 | Semana Santa | Viajes en coche |
| 2/5/2027 | Día de la Madre | Regalo |
| Julio 2027 (?) | Prime Day | CPC más alto |
| Julio – agosto 2027 | **Verano / operación salida** | Temporada alta de viajes en coche |
| Septiembre 2027 | Vuelta al cole / a la rutina | Vuelta a trayectos diarios |

## Cómo se prepara un evento grande (Black Friday, Navidad/Reyes, Prime, verano)

1. **3-4 semanas antes:** no se abren pruebas nuevas (también lo bloquea `config.PERIODOS_SIN_PRUEBAS`); se
   consolida lo que ya vende (cosecha a Exacta, negativas). Se le propone a Juan el plan del evento:
   presupuesto, ofertas o cupones (la oferta la decide él) y si conviene modo "crecer".
2. **Semana del evento:** subir puja solo en lo que tiene ventas probadas (Exacta, ASIN que venden); tolerar
   algo más de ACOS mientras siga por debajo del equilibrio; vigilar que las buenas no se queden sin
   presupuesto a mitad del día (proponer subida a Juan con tiempo).
3. **Después:** volver a las pujas normales en 2-3 días; no sacar conclusiones de los datos del evento para el
   resto del año (conversión y CPC no son normales); apuntar lo aprendido en LECCIONES.md.

## Días de la semana
Con datos suficientes (≥ 4 semanas), mirar si algún día vende claramente mejor o peor (SellerMate: group_by
dayOfWeek). Hasta entonces, no se tocan pujas por día.
