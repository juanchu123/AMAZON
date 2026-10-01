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

## 8. Economía de un producto en Amazon.es (para la hoja Economía)

- **Comisión por venta (referral):** porcentaje del precio total con IVA. Según la categoría en la que esté el producto en Seller Central: *Accesorios de electrónica* 15 % (hasta 100 €) y 8 % por encima; *Automoción y deportes de motor* 12 %; *Juguetes y juegos* 15 %. Mínimo por artículo de unos 0,30. Amazon mantuvo los porcentajes en 2024-2026. **Cuál aplica a cada ASIN lo dice Seller Central** (Inventario → la categoría del producto, o la calculadora de ingresos).
- **Tarifa FBA (logística):** para un paquete pequeño estándar (hasta unos 450 g), en la UE está en torno a **2,95 € para precios < 10 € y 3,96 € para 10-50 €** fuera de temporada alta. Desde el 1/2/2026 las **tarifas FBA reducidas de bajo precio** cubren productos de **≤ 20 €** en casi todas las categorías (unos 0,45 €/ud menos de media): **todos los productos de FreshFinder entran**. Hay recargo de temporada alta (octubre-diciembre).
- La cifra exacta por ASIN: **calculadora de ingresos FBA de Seller Central**. Es la que hay que poner en la hoja Economía; las tablas publicadas se quedan viejas en meses.
- Fuentes: Repricer (guía de tarifas 2026), About Amazon EU ("Update to European referral and FBA fees for 2026"), Beancount y Flexfulfillment (cambios FBA 2026), 30/09/2026.
- Orden de magnitud para la pinza (11,24 €): 11,24/1,21 − 15 % × 11,24 − ~2,5-3 € FBA − 0,80 € coste ≈ 3,8-4,3 € de margen → **ACOS de equilibrio ≈ 34-38 %**. Con el objetivo 30-35 % se juega casi a beneficio cero en anuncios: el dinero lo tienen que dar las ventas orgánicas que arrastran (ver §11).

## 9. Reglas de la ficha (para el agente de página de producto)

- **Título:** máximo **200 caracteres** con espacios (desde el 21/01/2025). Ninguna palabra más de **2 veces** (singular y plural cuentan igual; preposiciones y artículos no cuentan). Prohibidos `! $ ? _ { } ^ ¬ ¦` salvo en la marca. En móvil se cortan a partir de ~80 caracteres: **lo importante, en los primeros 80**. Si no se cumple, Amazon reescribe el título solo.
- **Bullets:** 5. Recomendado **≤ 200 caracteres cada uno** (en móvil se cortan); el límite duro depende de la categoría (lo marca Seller Central al editar).
- **Términos de búsqueda ocultos (backend):** **< 250 bytes** (ojo: una letra con tilde ocupa 2 bytes). Sin repetir palabras del título, sin marcas propias ni ajenas, sin ASIN.
- Fuentes: Search Engine Land ("Amazon's 2025 title policy update"), foros de Seller Central Europa (nuevos requisitos de título del 21/01/2025), guías de bullets de SellerSprite y Amalytix, 30/09/2026.

## 10. Campañas automáticas y cosecha de términos

- Una campaña automática tiene 4 grupos de segmentación, cada uno con su propia puja: **coincidencia cercana** (búsquedas muy parecidas al producto), **coincidencia amplia** (relacionadas de lejos), **sustitutos** (fichas de productos parecidos) y **complementos** (fichas de productos que se usan con el tuyo).
- Uso recomendado por Amazon: la automática sirve para **descubrir**; el **informe de términos de búsqueda** dice qué escribieron los que compraron, y esos términos se pasan a campañas manuales (exacta o frase) con su propia puja. Amazon tiene una función, "Target Promotion", que lo hace. Los términos que gastan sin vender se niegan en la automática.
- Fuente: guía "A guide to targeting with Sponsored Products" y "Harvest high performing targets with Target Promotion" (advertising.amazon.com), 30/09/2026.
- En el agente: la hoja masiva lee los grupos automáticos (`close-match`, `loose-match`, `substitutes`, `complements`) como elementos con puja. La cosecha automática está especificada en P1-D (pendiente).

## 11. ACOS no es todo: TACOS y ventas orgánicas

- **TACOS** = gasto en anuncios / **ventas totales** (anuncios + orgánicas). Un ACOS estable con un TACOS que baja significa que los anuncios empujan ventas orgánicas (mejor posición, más reseñas).
- Referencias habituales del sector: TACOS 5-15 % en productos maduros, 20-30 % en lanzamiento. **Son cifras de agencias, no de Amazon, y no demuestran causalidad**: el estudio de eBay (Blake, Nosko y Tadelis, *Econometrica* 2015) mostró que parte de lo que se atribuye a los anuncios habría ocurrido igual. La única forma seria de saberlo es comparar con un grupo de control (§7.4).
- En el agente: calcular el TACOS necesita las ventas totales, que no vienen en la hoja masiva. Saldrán del informe de transacciones de Seller Central (pendiente) en el agente de finanzas.

## 12. Eventos y estacionalidad (Prime Day, Black Friday, Navidad)

- En los grandes eventos **sube el CPC** (Amazon: +11 % en Prime Day en Sponsored Products) y también la conversión; los presupuestos diarios **se agotan a mitad del día**. Amazon recomienda subir presupuestos (3-5 veces) y pujas en esos días, o usar reglas de puja por calendario.
- Amazon dice que los productos con oferta o cupón que además se anuncian venden de media 12 veces más. Es una cifra de marketing de Amazon, sin grupo de control: no demuestra que la venta la cause el anuncio (§11).
- En el agente: el tope reparte los 840 €/mes a partes iguales por día. **Adelantar gasto a los días de evento (y ahorrar otros días) es una decisión de Juan**, que no está implementada; el tope rentable por clic sí protege en esos días aunque el CPC suba.
- Fuente: guías de Amazon Ads "Black Friday and Cyber Monday advertising tips", "Prime Day 2026: Advanced advertising strategies" y "Holiday advertising myths", 30/09/2026.

## 13. Puja sugerida de Amazon

- La puja sugerida y su rango salen de las **pujas ganadoras de anuncios parecidos recientes** en la categoría, y cambian cada día. No es lo que se paga por clic: el CPC real sale de la subasta.
- En esta cuenta, la "puja recomendada baja" de la rejilla era 0,32 € y el CPC pagado de verdad 0,95 € (mediana 0,76 €). Por eso el ACOS predicho con la puja sugerida sale optimista (especificación P1-B: calibrar el CPC).
- Fuente: ayuda de Amazon Ads "Understand bidding" y "Bidding strategies for Sponsored Products", 30/09/2026.

## 14. Segmentación por ASIN de la competencia

- Amazon la presenta como segmentación de fondo de embudo (compradores que ya comparan). Las pujas valen para todos los productos del grupo: en un grupo, productos muy parecidos. Existe la **segmentación negativa por ASIN**, para no salir junto a productos que no encajan.
- Fuente: guías "A guide to targeting with Sponsored Products" y "Sponsored Products best practices", 30/09/2026.

## 15. Diagnóstico de la cuenta con sus propios números (histórico)

ACOS = CPC / (conversión × ticket). Con el histórico de la cuenta:

| Producto | Clics | Compras | Conversión | Ticket | CPC pagado | ACOS | Para ACOS 35 %: conversión necesaria con ese CPC | … o CPC necesario con esa conversión |
|---|---|---|---|---|---|---|---|---|
| Rejilla | 1.119 | 53 | 4,7 % | 14,27 € | 0,95 € | 141 % | 19,1 % | 0,24 € |
| Pinza | 467 | 37 | 7,9 % | 11,24 € | 0,61 € | 69 % | 15,6 % | 0,31 € |

- **El problema principal no son las pujas: es la conversión.** Las referencias del sector (agencias, EE. UU.) hablan de una conversión media en Amazon de alrededor del 10 %; la rejilla está a la mitad. Con esa conversión, pujar lo que haría rentable la rejilla (≈ 0,24 €) apenas da impresiones. El agente de marketing no puede arreglar esto solo: lo que mueve la conversión es la **ficha** (título, fotos, bullets), el **precio**, las **reseñas** (cantidad y nota) y el **cupón u oferta**.
- Consecuencia práctica: prioridad al agente de página de producto y a revisar precio y reseñas, sobre todo en la rejilla. Y usar el informe de negocio (sesiones y porcentaje de sesiones con pedido) para medir si los cambios de ficha suben la conversión.
- Reseñas: el programa **Amazon Vine** (unidades gratis a revisores de Amazon a cambio de reseñas) se usa para lanzar productos con pocas reseñas; su coste e importe en Europa cambian, hay que mirarlo en Seller Central. Las cifras de mejora de conversión que circulan son de blogs, no de Amazon.
- Fuentes de las referencias: AdBadger y Karooya (benchmarks 2025-2026), blogs sobre Vine (EcomCircles, SellerSonar); datos propios de `FreshFinder_Amazon_Ads_historico.xlsx`. 30/09/2026.

## 16. Lo que enseña el histórico propio (FreshFinder_Amazon_Ads_historico.xlsx, analizado el 30/09/2026)

1. **Las keywords genéricas en amplia se comieron el dinero.** Rejilla: la amplia gastó 918 € de 1.049 € (88 %), con conversión 4,3 % y ACOS 154 %. Solo "soporte para móvil coche" (amplia) gastó 523 €, con conversión 4,0 % y CPC 1,05 €. Pinza: las genéricas convirtieron un 1,5 % (ACOS 453 %).
2. **Lo específico del producto convierte mucho mejor.** El grupo "Pinza" de la campaña "Soporte móvil pinza" trajo 34 de las 37 compras de la pinza: conversión 11,1 %, ACOS 41 %. En la rejilla, las específicas convirtieron un 7,0 % frente a 4,8 % de las genéricas, y con un CPC más barato (0,71 € frente a 0,98 €).
3. **La exacta convierte el doble que la amplia** (rejilla: 8,6 % frente a 4,3 %, CPC 0,74 € frente a 1,02 €). La campaña automática de la rejilla convirtió un 7,6 % (ACOS 84 %), mejor que su amplia manual.
4. **Se pagó más de lo que se pujaba:** mediana del CPC pagado / puja escrita = 1,42 en la rejilla y 1,33 en la pinza. Casi todas las campañas antiguas tenían "al alza y a la baja". Confirma con datos reales el multiplicador de `pujas.py`.
5. **La puja sugerida de Amazon se queda corta:** mediana del CPC pagado / "puja rec. baja" = 2,35 en la rejilla (19 keywords con ≥ 5 clics) y 1,38 en la pinza (11). Implementado como `Producto.factor_cpc` (mejoras P1-B.2): el ACOS predicho de una frase nueva usa el CPC sugerido × ese factor, que nunca baja de 1.

**Consecuencia:** con el CPC calibrado, en el histórico solo queda **una frase nueva por producto** con ACOS predicho ≤ 30 % (rejilla: "soporte coche para teléfono móvil"; pinza: "soporte móvil para coche de pinza para salpicadero"). Es lo que dicen los datos: con la conversión actual, casi ninguna frase nueva es rentable al CPC real. Juan decidió (30/09/2026) que una candidata rentable basta y que el agente pruebe por su cuenta con pérdida limitada (§18, `pruebas.py`).

## 17. Lo que falta por comprobar en la documentación oficial

La red de esta sesión no deja abrir advertising.amazon.com (solo el buscador). Pendiente:
- La puja mínima de Sponsored Products en Amazon.es (el agente usa 0,02 €).
- Si la atribución de 7 días se mantiene igual para la cuenta de FreshFinder.
- La categoría (y por tanto la comisión) de cada ASIN y su tarifa FBA exacta: calculadora de ingresos de Seller Central.
- El límite duro de caracteres de los bullets en la categoría de los soportes.

Para comprobarlo: permitir `advertising.amazon.com` en la configuración de red del entorno, o que Juan pegue el texto de la página.

## 18. Amazon Ads Academy — Sponsored Products D1 (estudiado el 30/09/2026) y lo que se hizo con ello

Fuente: `sponsored_products_D1_1.pdf` (resumen de ~21 cursos de Amazon Ads Academy que pasó Juan). Lo que el agente ya usa:

- **Estrategias y emplazamientos:** "al alza y a la baja" sube hasta +100 % arriba de la búsqueda y +50 % en el resto; el ajuste por emplazamiento va de 0 a +900 % y se suma a la estrategia (1 $ con +300 % arriba = 4 $, y hasta 8 $ con al alza y a la baja). El curso dice que el "resto de la búsqueda" no se ajusta, pero la hoja masiva de Amazon.es ya trae la fila "Emplazamiento del resto de la búsqueda": el curso está desactualizado. → `pujas.py`, `emplazamientos.py`.
- **Informe de emplazamiento:** comparar ACOS y conversión de cada emplazamiento y subir la puja donde convierte mejor. → `emplazamientos.py`.
- **Términos de búsqueda:** conversiones por encima del ROAS objetivo → keyword en manual; sin conversión y gasto > CPA objetivo → negativa; sin conversión y gasto < CPA → vigilar. Pauta automática → cosecha → manual exacta, con negativa en la automática. → `terminos.py`.
- **Coincidencias:** la exacta admite plurales, paráfrasis y otro orden, y se ignoran palabras vacías; las faltas de ortografía NO se contemplan (Juan decidió no usar erratas). Escalonar la puja amplia < frase < exacta. → `prediccion.p_modelo` (isotónica).
- **Presupuesto:** SP solo tiene presupuesto diario medio (un día puede gastar hasta el doble; el mes no pasa de la media × días). Las campañas buenas que agotan el presupuesto reciben más, sacándolo de las flojas, nunca al revés; si una gasta menos de lo que tiene, no sirve darle más. → `presupuesto.py`.
- **Cadencia:** dejar ~14 días antes de evaluar algo nuevo; después revisar cada 48 h y esperar unos días tras cada cambio. → `config.DIAS_PRIMERA_EVALUACION`, ronda de 3 días.
- **Campañas caducadas:** una campaña con la fecha de fin pasada no se reactiva; se copia. → `analyzer.terminadas`, `campanas.py`.
- **Hoja masiva:** Operación Crear / Actualizar / Archivar (vacía = se ignora). Errores frecuentes: 1025 (estrategia mal escrita), 1018 (coincidencia mal escrita), 1021 (keyword > 80 caracteres o con / % \ ^ , o dos puntos). Solo trae campañas con impresiones en los últimos 60 días. → `validacion.py`, `fuente_bulk.py`.
- **Pruebas:** A/B en periodos estables (no en eventos de temporada), 2-14 días, mirar CTR y luego ACOS. → `pruebas.py` (sin pruebas en Black Friday ni Navidad).
- **Ficha:** bullets de 10 a 255 caracteres, sin exclamaciones ni "el mejor"; ofertas flash (4-12 h) y de 7 días; el descuento porcentual o el cupón no afectan a la Oferta Destacada, el precio rebajado sí. Sin Registro de Marca no hay A+, Brand Store ni Sponsored Brands. → `ficha.py`, `RUTINA_COWORK.md`.
- **Listo para retail** (≥ 15 reseñas, ≥ 3,5 estrellas, ≥ 4 imágenes, stock, Oferta Destacada): Juan decidió que pinza y rejilla se anuncian igual; el agente solo para un grupo si Amazon marca el anuncio como no elegible.

Lo que el curso no cubre y falta: negativas de ASIN en campañas automáticas, datos de emplazamiento reales de la cuenta (todo estaba en pausa) y los cursos avanzados de SP.
