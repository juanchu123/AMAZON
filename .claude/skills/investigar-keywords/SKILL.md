---
name: investigar-keywords
description: Investigar las mejores frases (keywords) para un ASIN de FreshFinder uniendo datos de mercado (Helium 10 Cerebro/Magnet u otra lista con volumen de búsqueda) con el histórico propio (conversión que predice keyword_ml.py). Úsala cuando Juan pida "investiga keywords para mi ASIN", "mira Helium 10", "qué frases busca la gente" o suba un export de Helium 10.
---

# Investigar keywords para un ASIN

Objetivo: una lista de frases ordenada por **si se pueden ganar sin perder dinero** y **cuántas compras traerían**, no solo por volumen. El volumen dice cuánta gente busca; el histórico dice si esa gente compra TU producto.

## 1. Conseguir las frases de mercado

Por orden de preferencia:

1. **Conector de Helium 10** (si está en la sesión: herramientas `mcp__*helium*`, p. ej. `analyze_keywords`). Si no aparece, díselo a Juan: se conecta en https://claude.ai/customize/connectors y hay que abrir una sesión nueva (los conectores se leen al empezar). Con él:
   - **Cerebro (ASIN inverso)** del ASIN de Juan y de 3–5 competidores directos (los de la campaña de pruebas, `crear_memoria.py` → `asins`): qué frases les traen tráfico.
   - **Magnet** con 2–3 semillas del producto ("peluche pou", "soporte movil coche pinza").
   - Marketplace **Amazon.es**. Guarda el resultado como CSV en `datos/helium10_<producto>_<fecha>.csv` con columnas `Keyword Phrase, Search Volume, Competing Products, Suggested PPC Bid`.
2. **Export manual de Helium 10** (Cerebro/Magnet → Export CSV) que Juan sube a `datos/`. Mismas columnas.
3. Sin Helium 10: lista propia (columna "palabra clave", opcional "volumen"). Sin volumen, el orden será solo por conversión.

amazon.es y su autocompletado están bloqueados desde el contenedor: no intentes scrapearlos.

## 2. Puntuar con el modelo

```bash
python keyword_ml.py --producto <perfil> --candidatas datos/helium10_<producto>_<fecha>.csv --top 25
```

Genera `resultados/investigacion_<perfil>.csv` con, por frase: volumen, competidores, puja sugerida de Helium 10, compra/clic predicha (Frase y Exacta), **puja máx. rentable** (ACOS objetivo), **compite** (Sí / Justo / No), **compras/mes estimadas** (= volumen × CTR medio del producto × compra/clic; orientativo), si ya se probó, si es específica del producto y la coincidencia recomendada.

Si el producto no tiene perfil, créalo antes (skill `crear-campana`, Paso 2).

## 3. Interpretar (cuéntaselo a Juan así)

- **Compite = Sí** y específica → candidata fuerte (Frase; las mejores, también Exacta).
- **Compite = Justo** → probar con puja = puja máx. rentable; puede salir poco.
- **Compite = No** → la puja que hace falta para salir supera lo que es rentable: no pujar (aunque tenga mucho volumen). Las genéricas grandes ("soporte movil coche") suelen caer aquí.
- **Palabras sin datos** → la conversión es una suposición; si el producto tiene < 10 compras en el histórico, todo es suposición (pujas ≤ 0,30 €).
- Frases con volumen alto y palabras que NO están en la ficha (p. ej. "alien pou") → recomendar añadirlas al título/bullets si describen el producto: mejora anuncios y orgánico.
- Nunca proponer palabras de características que el producto no tiene.

## 4. Llevarlo a una campaña

Las elegidas pasan a `crear_memoria.py` → `CAMPANAS[...]["especiales"]` (lista `(frase, motivo)`, con el volumen en el motivo) y se sigue la skill `crear-campana` (Paso 4 en adelante), o se añaden como keywords nuevas en la revisión semanal. Commit y push de `datos/` y `resultados/investigacion_*.csv`.
