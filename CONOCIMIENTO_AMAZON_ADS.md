# Conocimiento de Amazon Ads que usa el agente

Hechos comprobados (fecha y fuente en cada uno) y cómo los aplica el código. Cualquier sesión (o Cowork) que vaya a cambiar reglas de pujas, presupuesto o evaluación lo lee antes. Si Amazon cambia algo, se actualiza aquí y en el código a la vez.

## 1. Estrategias de puja (Sponsored Products)

| Estrategia | Qué hace Amazon con la puja escrita | En el agente |
|---|---|---|
| Pujas dinámicas: solo a la baja | La baja en tiempo real si la conversión parece menos probable; nunca la sube | Multiplicador 1 |
| Pujas dinámicas: al alza y a la baja | La sube **hasta +100 % en la parte superior de la primera página** y **hasta +50 % en el resto de emplazamientos**; la baja cuando la conversión parece menos probable | Multiplicador 2 arriba, 1,5 en el resto (`config.SUBIDA_DINAMICA_*`) |
| Puja fija | Usa la puja tal cual | Multiplicador 1 |

- Ejemplo oficial: puja de 1 € con "al alza y a la baja" → hasta 2 € arriba de la búsqueda, 1,50 € en el resto.
- Fuente: guía oficial "Dynamic bidding - up and down" (advertising.amazon.com/library/guides/dynamic-bidding-sponsored-products), comprobado el 30/09/2026.
- En el código: `pujas.multiplicador()`; la puja escrita es `min(objetivo, tope rentable / multiplicador)`, así el clic más caro posible no pasa del equilibrio.

## 2. Ajustes de puja por emplazamiento

- Tres emplazamientos ajustables: parte superior de la búsqueda (primera página), resto de la búsqueda y páginas de producto (en la hoja masiva aparece también "Amazon Business"). Ajuste de **0 % a 900 %**, que se suma encima de la estrategia (se multiplican).
- Fuente: anuncio de Amazon recogido por Search Engine Land y Martech, y ayuda de Amazon Ads "Adjust Sponsored Products bids" (30/09/2026).
- En el agente: se leen y cuentan en el multiplicador, pero no se tocan (regla de seguridad 3). Si alguno pasa de 0 %, el agente avisa.

## 3. Presupuesto diario

- El presupuesto diario **es una media del mes**: un día concreto Amazon puede gastar más (hasta un 25 %, o hasta un 100 % con la política nueva), pero **al final del mes nunca cobra más que presupuesto diario × días del mes**; si se pasa, ajusta la factura.
- Fuente: guía "Sponsored Products budget basics and best practices" y "New sponsored ads daily budgeting policy" (advertising.amazon.com, 30/09/2026).
- En el agente: por eso el tope de 840 €/mes se controla con la **suma de presupuestos diarios** (`safety.presupuesto_diario_total`) y no con el gasto de un solo día. Que un día se gaste más que el presupuesto no es un error ni motivo para cortar.
- Mínimo por campaña: 1 €/día (`config.PRESUPUESTO_MINIMO_AMAZON`).

## 4. Atribución

- Sponsored Products para **vendedores (Seller Central, como FreshFinder): 7 días**, solo por clic. Una compra del producto (o de otro producto del vendedor) hasta 7 días después del clic se atribuye a ese clic, **en la fecha del clic**. Vendedores con cuenta de proveedor (Vendor): 14 días.
- Fuente: documentación de herramientas de terceros (bidx, Karooya, Openbridge); la página oficial no estuvo accesible (30/09/2026). Coincide con la columna "Ventas de 7 días" de los informes de Seller Central.
- En el agente: un clic es **maduro** a los 7 días (`config.DIAS_MADUREZ`). Stop-loss y veredictos solo usan clics maduros: antes, las ventas de ese clic pueden no haber llegado.

## 5. Keywords negativas

- Tipos: **negativa exacta** (no sale en esa búsqueda exacta o variaciones cercanas) y **negativa de frase** (no sale en búsquedas que contienen la frase). Se ponen a nivel de campaña o de grupo de anuncios. Sirven en campañas manuales y automáticas.
- Fuente: ayuda "Add negative keywords or negative products" y guía "Targeting with Sponsored Products" (advertising.amazon.com, 30/09/2026).
- En el agente: aún no se crean solas (aplazado por Juan). Especificación en P1-E.

## 6. Hoja masiva (Operaciones en bloque)

- Columna **Operación**: Create / Update / Archive (en español: Crear / Actualizar / Archivar). **Si está vacía, Amazon ignora la fila.**
- Entidades de Sponsored Products: Campaña, Grupo de anuncios, Anuncio de producto, Palabra clave, Palabra clave negativa, Ajuste de puja, Palabra clave negativa de campaña, Segmentación por productos, Segmentación negativa por productos.
- Fuente: guías de terceros sobre bulksheets (Adbrew, eCommerce Fastlane) y el índice de la documentación oficial de bulksheets (30/09/2026).
- **Sin confirmar:** el valor exacto en español de "Update". "Crear" ya se aceptó en una subida real; "Actualizar" (`fuente_bulk.OP_ACTUALIZAR`) se confirma con el informe de la primera subida que lo use.

## 7. Cómo saber si un cambio funcionó (experimentos)

Principios de la experimentación online (Kohavi, Tang y Xu, *Trustworthy Online Controlled Experiments*, 2020) aplicados a esta cuenta:

1. **Una métrica que manda:** el beneficio después de publicidad (hoja Finanzas), no el ACOS ni las ventas solas. Un ACOS más bajo con menos beneficio es peor.
2. **Tamaño de muestra antes de juzgar:** con conversiones del 5-8 %, 10 clics suelen dar 0 o 1 venta; eso es ruido. Por eso el agente espera clics maduros y (pendiente, P1-A) usará intervalos en vez de "¿mejoró el ACOS?".
3. **Regresión a la media:** una keyword pausada tras una racha mala, o subida tras una racha buena, tiende a volver a su media sin que el cambio haya hecho nada. No atribuir al cambio lo que es azar.
4. **Estacionalidad y cambios de la cuenta:** Navidad, rebajas, precio, reseñas o stock mueven la conversión de todo a la vez. Comparar antes/después no basta; hace falta un grupo de control (P2: campaña "congelada" frente a la gestionada).
5. **Ley de Twyman:** un resultado que parece demasiado bueno probablemente es un error de datos (como el ACOS 0 % que salía cuando no se leía la columna "Inversión"). Primero se revisan los datos.
6. **No mirar a cada rato y decidir:** mirar los datos a diario y cortar en cuanto "parece" que algo va bien o mal infla los falsos positivos. Las reglas fijan de antemano cuándo se decide (ronda: ≥ 3 días y ≥ 10 clics; veredicto: ≥ 10 clics maduros).

## 8. Lo que falta por comprobar en la documentación oficial

La red de esta sesión no deja abrir advertising.amazon.com (solo el buscador). Pendiente:
- El valor en español de "Update" en la hoja masiva.
- La puja mínima de Sponsored Products en Amazon.es (el agente usa 0,02 €).
- Si la atribución de 7 días se mantiene igual para la cuenta de FreshFinder.

Para comprobarlo: permitir `advertising.amazon.com` en la configuración de red del entorno, o que Juan pegue el texto de la página.
