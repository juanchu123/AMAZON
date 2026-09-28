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

import argparse
import csv
import json
import os
import re
from datetime import timedelta
from pathlib import Path

import config
import keyword_ml as kml
from documento import num

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


COLUMNAS_CSV = ("ASIN", "Palabra clave", "Motivo", "Fuente", "Volumen", "Puja sugerida (€)")


def _euros(v):
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace("€", "").replace(",", ".").strip())
    except ValueError:
        return None


def añadir(doc, asin, dia, filas):
    """Añade a la hoja Investigación las frases que el producto aún no tiene. Misma firma = misma
    frase (sin acentos, mayúsculas, orden de palabras ni palabras vacías): nunca se repite.
    filas: [{"Palabra clave", "Motivo", "Fuente", "Volumen", "Puja sugerida (€)"}]. Devuelve cuántas son nuevas."""
    hoja = doc.hojas["Investigación"]
    vistas = {kml.firma(str(f.get("Palabra clave") or "")) for f in hoja if str(f["Producto (ASIN)"]) == asin}
    rank = max((int(num(f["Rank"])) for f in hoja
                if str(f["Producto (ASIN)"]) == asin and str(f["Fecha"])[:10] == dia.isoformat()), default=0)
    nuevas = 0
    for f in filas:
        frase = str(f.get("Palabra clave") or "").strip().lower()
        fi = kml.firma(frase)
        if not fi or fi in vistas:
            continue
        vistas.add(fi)
        rank, nuevas = rank + 1, nuevas + 1
        hoja.append({"Fecha": dia.isoformat(), "Producto (ASIN)": asin, "Rank": rank, **f, "Palabra clave": frase})
    return nuevas


def importar_csv(doc, ruta, dia):
    """investigacion_<día>.csv de Cowork (separador ';', UTF-8), cabecera exacta
    ASIN;Palabra clave;Motivo;Fuente;Volumen;Puja sugerida (€). Devuelve {asin: frases nuevas}."""
    with open(ruta, encoding="utf-8-sig", newline="") as fh:
        lector = csv.DictReader(fh, delimiter=";")
        faltan = [c for c in COLUMNAS_CSV if c not in (lector.fieldnames or [])]
        if faltan:
            raise SystemExit(f"{ruta.name}: faltan las columnas {faltan} (cabecera: {lector.fieldnames})")
        por_asin = {}
        for r in lector:
            asin = str(r.get("ASIN") or "").strip().upper()
            if asin.startswith("B0"):
                por_asin.setdefault(asin, []).append({
                    "Palabra clave": r["Palabra clave"], "Motivo": str(r.get("Motivo") or "")[:300],
                    "Fuente": f"{r.get('Fuente') or ''} ({ruta.name})".strip(), "Volumen": r.get("Volumen") or None,
                    "Puja sugerida (€)": _euros(r.get("Puja sugerida (€)"))})
    return {asin: añadir(doc, asin, dia, filas) for asin, filas in por_asin.items()}


def importar_documento(doc, ruta, dia):
    """Documento_investigacion_keywords.xlsx: una hoja por producto ("Pinza (B0DCZS1NR6)"…) con las
    frases investigadas. Se añaden las que el producto aún no tiene; las que solo propone el modelo
    ("Recomendada ML") no, porque el agente ya genera las suyas. Devuelve {asin: frases nuevas}."""
    from openpyxl import load_workbook
    wb = load_workbook(ruta, read_only=True, data_only=True)
    importadas = {}
    for ws in wb.worksheets:
        m = re.search(r"\((B0[A-Z0-9]{8})\)", ws.title)
        if not m:
            continue
        filas = list(ws.iter_rows(values_only=True))
        cab = next((i for i, r in enumerate(filas) if r and r[0] == "Frase"), None)
        if cab is None:
            continue
        cols = [str(c or "") for c in filas[cab]]
        nuevas = []
        for r in filas[cab + 1:]:
            d = dict(zip(cols, r))
            fuentes = str(d.get("Fuentes") or d.get("Fuente") or "").strip()
            if not d.get("Frase") or fuentes == "Recomendada ML":
                continue
            nuevas.append({"Palabra clave": str(d["Frase"]), "Motivo": f"{fuentes}. {d.get('Motivo') or ''}".strip(" .")[:300],
                           "Fuente": f"{fuentes} ({ruta.name})", "Volumen": d.get("Señal de volumen") or d.get("Volumen"),
                           "Puja sugerida (€)": _euros(d.get("Puja sugerida Amazon (€)") or d.get("Puja sugerida (€)"))})
        importadas[m[1]] = añadir(doc, m[1], dia, nuevas)
    return importadas


def importar_entrada(doc, carpeta, dia):
    """Todo lo de investigación que haya en una carpeta de entrada. Devuelve [(archivo, asin, nuevas)]."""
    out = []
    for ruta in sorted(Path(carpeta).glob("investigacion*.csv")):
        out += [(ruta.name, a, n) for a, n in importar_csv(doc, ruta, dia).items()]
    for ruta in sorted(Path(carpeta).glob("*.xlsx")):
        if ruta.name.lower().startswith(config.PREFIJO_INVESTIGACION):
            out += [(ruta.name, a, n) for a, n in importar_documento(doc, ruta, dia).items()]
    return out


# ---------------------------------------------------------------- para Cowork: qué no volver a buscar
def ya_vistas(doc):
    """Frases que ya no hace falta investigar, por producto: las investigadas (todos los días), las
    que el producto tiene en campañas y las del histórico. [(asin, frase, firma, origen)]."""
    out, vistas = [], set()

    def poner(asin, frase, origen):
        fi = kml.firma(str(frase or ""))
        if asin and fi and (asin, fi) not in vistas:
            vistas.add((asin, fi))
            out.append((asin, str(frase).strip().lower(), " ".join(sorted(fi)), origen))

    for f in doc.hojas["Investigación"]:
        poner(str(f["Producto (ASIN)"]), f.get("Palabra clave"), f"investigada el {str(f['Fecha'])[:10]}")
    for f in doc.hojas["Segmentación"]:
        if f.get("Tipo") == "keyword":
            poner(str(f.get("Producto (ASIN)") or ""), f.get("Palabra clave / segmentación"), "en campañas")
    for f in doc.hojas["Histórico"]:
        poner(str(f.get("Producto (ASIN)") or ""), f.get("Keyword / segmento"), "histórico")
    return out


def escribir_ya_vistas(doc, ruta):
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    filas = ya_vistas(doc)
    with open(ruta, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["ASIN", "Palabra clave", "Firma", "Origen"])
        w.writerows(filas)
    return len(filas)


# ---------------------------------------------------------------- Excel de investigación (para Juan)
def escribir_excel(doc, catalogo, cuenta, ruta, hoy):
    """Documento_investigacion_keywords.xlsx: todas las frases investigadas de cada producto,
    puntuadas con la MISMA función con la que decide el agente (prediccion.Catalogo.evaluar)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    asins = sorted({str(f["Producto (ASIN)"]) for f in doc.hojas["Investigación"] if f.get("Producto (ASIN)")})
    if not asins:
        return None
    en_campanas = {}
    for e in cuenta.elementos.values():
        en_campanas.setdefault(cuenta.producto_de_grupo(e.id_grupo), set()).add(kml.firma(e.texto))
    wb = Workbook()
    res = wb.active
    res.title = "Resumen"
    res.append([f"Investigación de keywords — FreshFinder ({hoy:%d/%m/%Y})"])
    res.append(["Todas las frases investigadas (todos los días), una vez por producto, puntuadas con el filtro "
                f"del agente: entra en campaña si el ACOS predicho es ≤ {config.ACOS_MAX_KEYWORD_NUEVA:.0%} y hay hueco."])
    res.append([])
    res.append(["Producto", "Hoja", "Frases", f"Pasan filtro (≤ {config.ACOS_MAX_KEYWORD_NUEVA:.0%})",
                f"Cerca ({config.ACOS_MAX_KEYWORD_NUEVA:.0%}–{config.ACOS_OBJETIVO_MAX:.0%})", "Ya en campañas", "Nuevas hoy"])
    cab = ["Frase", "Primera vez", "Fuente", "Volumen", "Puja sugerida (€)", "En campañas", "P(compra|clic)",
           "CPC estimado (€)", "ACOS predicho", "¿Pasa filtro?", "Puja propuesta (€)", "Decisión del filtro",
           "Motivo de la investigación"]
    negrita, azul = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="305496")
    for asin in asins:
        filas = []
        for f in doc.investigacion(asin)[1]:
            frase = str(f["Palabra clave"])
            ev = catalogo.evaluar(asin, frase, rec=_euros(f.get("Puja sugerida (€)")))
            ya = kml.firma(frase) in en_campanas.get(asin, set())
            filas.append([frase, str(f["Fecha"])[:10], f.get("Fuente"), f.get("Volumen"), _euros(f.get("Puja sugerida (€)")),
                          "Sí" if ya else "No", round(ev["p"], 4) if ev["p"] else None,
                          round(ev["cpc"], 2) if ev["cpc"] else None,
                          round(ev["acos_pred"], 3) if ev["acos_pred"] is not None else None,
                          "Sí" if ev["pasa"] and not ya else "No", ev["puja"],
                          "ya está en campañas" if ya else ev["motivo"], f.get("Motivo")])
        filas.sort(key=lambda r: (r[9] != "Sí", r[8] if r[8] is not None else 99))
        titulo = f"{catalogo.producto(asin).corto} ({asin})"[:31]
        ws = wb.create_sheet(titulo)
        ws.append(cab)
        for c in ws[1]:
            c.font, c.fill = negrita, azul
        for r in filas:
            ws.append(r)
        ws.freeze_panes = "A2"
        ws.column_dimensions["A"].width = 48
        cerca = sum(1 for r in filas if r[8] is not None and config.ACOS_MAX_KEYWORD_NUEVA < r[8] <= config.ACOS_OBJETIVO_MAX)
        res.append([catalogo.producto(asin).corto, titulo, len(filas), sum(r[9] == "Sí" for r in filas), cerca,
                    sum(r[5] == "Sí" for r in filas), sum(r[1] == hoy.isoformat() for r in filas)])
    res["A1"].font = Font(bold=True, size=13)
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    wb.save(ruta)
    return ruta


def guardar(doc, asin, hoy, candidatas, archivo):
    fuente = "LLM + búsqueda web" + (f" + {archivo}" if archivo else "")
    return añadir(doc, asin, hoy, [{"Palabra clave": c["palabra_clave"], "Motivo": c["motivo"], "Fuente": fuente,
                                    "Volumen": c["volumen"]} for c in candidatas])


def main(argv=None):
    """python investigacion.py --ya-vistas  ->  salidas/<hoy>/frases_ya_vistas.csv (para Cowork)."""
    from datetime import date
    import carpetas
    from documento import Documento
    ap = argparse.ArgumentParser(description="Investigación de keywords: utilidades para Cowork")
    ap.add_argument("--ya-vistas", action="store_true", help="escribe las frases que ya no hace falta investigar")
    ap.add_argument("--hoy", help="AAAA-MM-DD (por defecto, hoy)")
    args = ap.parse_args(argv)
    if not args.ya_vistas:
        ap.print_help()
        return
    hoy = date.fromisoformat(args.hoy) if args.hoy else date.today()
    memoria = carpetas.memoria_anterior(hoy)
    if not memoria:
        raise SystemExit(f"No hay ninguna memoria en {config.SALIDAS}/: ejecuta antes el agente.")
    ruta = carpetas.salida(hoy) / "frases_ya_vistas.csv"
    n = escribir_ya_vistas(Documento(memoria), ruta)
    print(f"{n} frases ya vistas (de {memoria}) -> {ruta}")


if __name__ == "__main__":
    main()
