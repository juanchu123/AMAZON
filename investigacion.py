"""
investigacion.py — investigación de mercado con un LLM (AGENTE_AUTONOMO.md §2.11).

Es el ÚNICO sitio del sistema donde interviene un LLM, y su trabajo es BUSCAR Y ORDENAR
frases candidatas, nunca decidir dinero. Su salida va a la hoja "Investigación" del documento
único y de ahí al filtro determinista de analyzer.py / prediccion.py (ACOS predicho ≤ 30 %):
el LLM propone, las reglas fijas deciden si entra de verdad.

Fuentes que recibe para cada producto:
  - el título del producto y sus palabras específicas (perfil de keyword_ml.py),
  - su histórico (las keywords que ya vendieron y las que gastaron sin vender),
  - las keywords que ya tiene (para no repetirlas),
  - el export de Helium 10 u otra lista de keywords si Juan lo ha dejado en entradas/,
  - búsqueda web (herramienta web_search del servidor de Anthropic).

Requiere ANTHROPIC_API_KEY (variable de entorno). Modelo: AGENTE_MODELO_LLM (por defecto
claude-opus-5). Se ejecuta como mucho una vez por semana y producto (DIAS_ENTRE_INVESTIGACIONES).
Coste orientativo: unos céntimos por producto y semana.
"""

import json
import os
import re
from datetime import timedelta

import config
import keyword_ml as kml

INSTRUCCIONES = """Eres un investigador de palabras clave para anuncios Sponsored Products de Amazon.es.
Tu único trabajo es encontrar y ordenar frases de búsqueda que compradores reales de España escribirían
en Amazon para encontrar ESTE producto. No decides pujas, presupuestos ni si una frase se usa: eso lo
deciden reglas fijas después, con los datos de ventas reales.

Reglas:
- Solo frases en español, tal como las teclea un comprador en el buscador de Amazon.es (minúsculas).
- Solo frases que describen este producto. Nunca características que el producto no tiene
  (si el título no dice "magnético", no propongas "soporte magnético").
- Nada de marcas de otros fabricantes.
- No repitas las frases que ya tiene ni variaciones triviales de ellas (orden de palabras, plurales).
- Prioriza frases específicas del producto (llevan sus palabras distintivas) frente a genéricas.
- Usa la búsqueda web para ver cómo se describe y se busca este tipo de producto en España
  (fichas de la competencia, foros, comparativas) y aprovecha el histórico: las palabras de las
  frases que ya vendieron son la mejor pista.
"""

ESQUEMA = {
    "type": "object",
    "properties": {
        "candidatas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "palabra_clave": {"type": "string"},
                    "motivo": {"type": "string"},
                    "volumen_estimado": {"type": "string", "enum": ["alto", "medio", "bajo", "desconocido"]},
                },
                "required": ["palabra_clave", "motivo", "volumen_estimado"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["candidatas"],
    "additionalProperties": False,
}


def toca_investigar(doc, asin, hoy):
    ult, _ = doc.investigacion(asin)
    return ult is None or (hoy - ult) >= timedelta(days=config.DIAS_ENTRE_INVESTIGACIONES)


def disponible():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _contexto(prod, existentes, lista_externa):
    lineas = [f"Producto (ASIN {prod.asin}): {prod.nombre}"]
    if prod.perfil:
        lineas.append("Palabras que lo distinguen: " + ", ".join(sorted(kml.PERFILES[prod.perfil]["especificas"])))
    vendieron = sorted((f for f in prod.filas if f["compras"] > 0), key=lambda f: -f["compras"])[:25]
    sin_venta = sorted((f for f in prod.filas if f["compras"] == 0 and f["clics"] >= 10), key=lambda f: -f["clics"])[:15]
    if vendieron:
        lineas.append("\nFrases que YA VENDIERON (clics / compras):")
        lineas += [f"- {f['keyword']} ({f['coincidencia']}): {f['clics']:.0f} / {f['compras']:.0f}" for f in vendieron]
    if sin_venta:
        lineas.append("\nFrases con muchos clics y NINGUNA venta (evita parecidas):")
        lineas += [f"- {f['keyword']}: {f['clics']:.0f} clics" for f in sin_venta]
    if existentes:
        lineas.append("\nFrases que ya tiene en sus campañas (no repetir):")
        lineas += [f"- {t}" for t in sorted(existentes)[:60]]
    if lista_externa:
        lineas.append("\nLista de keywords de mercado (Helium 10 u otra fuente; frase / volumen):")
        lineas += [f"- {c['frase']} / {c['volumen'] if c['volumen'] is not None else '?'}" for c in lista_externa[:80]]
    return "\n".join(lineas)


def _lista_externa(prod):
    """Busca en entradas/ un export de keywords del producto (p. ej. helium10_pinza_2026-10-01.csv)."""
    claves = {prod.asin.lower()} | ({prod.perfil} if prod.perfil else set())
    archivos = sorted((p for p in config.ENTRADAS.rglob("*") if p.suffix.lower() in (".csv", ".xlsx")
                       and any(k in p.name.lower() for k in claves)), key=lambda p: p.stat().st_mtime)
    if not archivos:
        return [], None
    try:
        return kml.leer_candidatas(str(archivos[-1])), archivos[-1].name
    except SystemExit:
        return [], None


def investigar(prod, existentes, cliente=None):
    """Devuelve [{palabra_clave, motivo, volumen}] ordenadas (la primera, la más prometedora)."""
    import anthropic
    cliente = cliente or anthropic.Anthropic()
    externa, archivo = _lista_externa(prod)
    contexto = _contexto(prod, existentes, externa)

    # 1) investigación libre con búsqueda web
    mensajes = [{"role": "user", "content": contexto + "\n\nInvestiga y escribe una lista razonada de hasta "
                 f"{config.MAX_CANDIDATAS_INVESTIGACION} frases candidatas nuevas, de la más prometedora a la menos, "
                 "con el motivo de cada una y una estimación de volumen de búsqueda (alto/medio/bajo/desconocido)."}]
    notas = ""
    for _ in range(5):   # la búsqueda web puede pausar el turno (pause_turn): se reanuda
        r = cliente.messages.create(model=config.MODELO_INVESTIGACION, max_tokens=16000, system=INSTRUCCIONES,
                                    thinking={"type": "adaptive"}, messages=mensajes,
                                    tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}])
        notas += "".join(b.text for b in r.content if b.type == "text")
        if r.stop_reason != "pause_turn":
            break
        mensajes = mensajes[:1] + [{"role": "assistant", "content": r.content}]

    # 2) convertir las notas en datos estructurados (sin herramientas: JSON garantizado)
    r = cliente.messages.create(
        model=config.MODELO_INVESTIGACION, max_tokens=8000, system=INSTRUCCIONES,
        messages=[{"role": "user", "content": contexto + "\n\nNotas de la investigación:\n" + notas
                   + "\n\nDevuelve la lista final ordenada (la primera, la más prometedora), sin frases repetidas "
                     "ni frases que ya tiene."}],
        output_config={"format": {"type": "json_schema", "schema": ESQUEMA}})
    if r.stop_reason == "refusal":
        return [], archivo
    texto = next((b.text for b in r.content if b.type == "text"), "{}")
    datos = json.loads(texto).get("candidatas", [])
    ya = {kml.firma(t) for t in existentes}
    out, vistas = [], set()
    for c in datos:
        frase = " ".join(str(c.get("palabra_clave", "")).lower().split())
        fi = kml.firma(frase)
        if not fi or fi in ya or fi in vistas:
            continue
        vistas.add(fi)
        out.append({"palabra_clave": frase, "motivo": str(c.get("motivo", ""))[:300],
                    "volumen": c.get("volumen_estimado")})
    return out[:config.MAX_CANDIDATAS_INVESTIGACION], archivo


def importar_documento(doc, ruta, dia):
    """Carga Documento_investigacion_keywords.xlsx (lo genera Cowork cada día) en la hoja Investigación.

    Cada hoja de producto ("Pinza (B0DCZS1NR6)"…) trae todas las frases investigadas, ordenadas de
    mejor a peor. Se guardan con la fecha de la carpeta de entrada como la investigación vigente del
    producto (si ya se importó ese día, se sustituye; lo que llegó de otras fuentes se queda). Solo son datos: el filtro de ACOS predicho del
    agente decide si alguna entra. Las frases que solo propone el modelo ("Recomendada ML") no se
    importan: el agente ya genera las suyas. Devuelve {asin: nº de frases}."""
    from openpyxl import load_workbook
    wb = load_workbook(ruta, read_only=True, data_only=True)
    importadas = {}
    for ws in wb.worksheets:
        m = re.search(r"\((B0[A-Z0-9]{8})\)", ws.title)
        if not m:
            continue
        asin, filas = m[1], list(ws.iter_rows(values_only=True))
        cab = next((i for i, r in enumerate(filas) if r and r[0] == "Frase"), None)
        if cab is None:
            continue
        cols = [str(c or "") for c in filas[cab]]
        nuevas = []
        for r in filas[cab + 1:]:
            d = dict(zip(cols, r))
            frase, fuentes = str(d.get("Frase") or "").strip().lower(), str(d.get("Fuentes") or "").strip()
            if not frase or fuentes == "Recomendada ML":
                continue
            motivo = f"{fuentes}. {d.get('Motivo') or ''}".strip(" .")
            nuevas.append({"Fecha": dia.isoformat(), "Producto (ASIN)": asin, "Rank": len(nuevas) + 1,
                           "Palabra clave": frase, "Motivo": motivo[:300], "Fuente": f"Documento de investigación ({ruta.name})",
                           "Volumen": d.get("Señal de volumen"), "Puja sugerida (€)": d.get("Puja sugerida Amazon (€)")})
        doc.hojas["Investigación"] = [f for f in doc.hojas["Investigación"]
                                      if not (str(f["Producto (ASIN)"]) == asin and str(f["Fecha"])[:10] == dia.isoformat()
                                              and str(f.get("Fuente") or "").startswith("Documento de investigación"))]
        doc.hojas["Investigación"] += nuevas
        importadas[asin] = len(nuevas)
    return importadas


def guardar(doc, asin, hoy, candidatas, archivo):
    fuente = "LLM + búsqueda web" + (f" + {archivo}" if archivo else "")
    for i, c in enumerate(candidatas, 1):
        doc.hojas["Investigación"].append({"Fecha": hoy.isoformat(), "Producto (ASIN)": asin, "Rank": i,
                                           "Palabra clave": c["palabra_clave"], "Motivo": c["motivo"],
                                           "Fuente": fuente, "Volumen": c["volumen"]})
