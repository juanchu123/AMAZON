"""Paso 2: rellena el Excel de contenido de cajas por grupo de embalaje ("Pack Group - N").

Amazon genera este archivo en Send to Amazon después de repartir el envío en grupos de
embalaje. Tiene las hojas protegidas y fórmulas propias, así que NO se reescribe con openpyxl:
se editan directamente las celdas de datos en el XML y se deja todo lo demás byte a byte.

Uso:
    python rellenar_contenido_cajas.py ARCHIVO.xlsx --leer
    python rellenar_contenido_cajas.py ARCHIVO.xlsx SPEC.json SALIDA.xlsx

--leer imprime, por grupo, los SKUs y las unidades que Amazon espera. Úsalo antes de
preguntar a Juan cómo va a meter las unidades en cajas.

SPEC.json (una entrada por grupo, clave = número de grupo):
{
  "grupos": {
    "1": {"cajas": [
      {"unidades": {"5E-I8NY-S191": 2, "O8-5W7J-DSK1": 2},
       "peso": 0.9, "ancho": 20, "largo": 30, "alto": 15}
    ]},
    "3": {"cajas": [
      {"unidades": {"5E-I8NY-S191": 16}, "peso": 2.8, "ancho": 30, "largo": 40, "alto": 20},
      {"unidades": {"O8-5W7J-DSK1": 17}, "peso": 2.9, "ancho": 30, "largo": 40, "alto": 20}
    ]}
  }
}
Todos los grupos del archivo tienen que venir en la spec.
"""

import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import Errores, cargar_spec, validar_caja, validar_sku  # noqa: E402

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"

PRIMERA_COL_CAJA = 13        # columna M = caja 1
MAX_CAJAS = 11               # la plantilla trae fórmulas y validaciones hasta la W
MAX_CAMBIO_CAJAS = 10        # Amazon permite variar el nº de cajas estimado hasta ±10
ESTILO_CAJA = "44"           # estilo de las columnas de cajas en la plantilla de Amazon
ETIQUETAS_MEDIDAS = {"box weight (kg):": "peso", "box width (cm):": "ancho",
                     "box length (cm):": "largo", "box height (cm):": "alto"}


def col_letra(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def col_num(letras):
    n = 0
    for ch in letras:
        n = n * 26 + ord(ch) - 64
    return n


def fmt(v):
    return str(int(v)) if float(v).is_integer() else repr(float(v))


# ---------- lectura ----------

def cadenas_compartidas(z):
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")) for si in root.findall("m:si", NS)]


def hojas(z):
    """Lista de (nombre, ruta_xml) en el orden del libro."""
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    destino = {r.get("Id"): r.get("Target") for r in rels.iter(f"{REL_NS}Relationship")}
    out = []
    for s in wb.find("m:sheets", NS):
        t = destino[s.get(f"{{{NS['r']}}}id")].lstrip("/")
        out.append((s.get("name"), t if t.startswith("xl/") else "xl/" + t))
    return out


def valores_hoja(xml, strings):
    """{(fila, col): valor} de las celdas con valor."""
    root = ET.fromstring(xml)
    vals = {}
    for c in root.iter(f"{{{NS['m']}}}c"):
        m = re.match(r"([A-Z]+)(\d+)", c.get("r"))
        v = c.find("m:v", NS)
        if v is None:
            is_ = c.find("m:is", NS)
            if is_ is None:
                continue
            val = "".join(t.text or "" for t in is_.iter(f"{{{NS['m']}}}t"))
        elif c.get("t") == "s":
            val = strings[int(v.text)]
        elif c.get("t") in ("str", "inlineStr"):
            val = v.text
        else:
            try:
                val = float(v.text)
            except (TypeError, ValueError):
                val = v.text
        vals[(int(m.group(2)), col_num(m.group(1)))] = val
    return vals


def estructura_grupo(vals):
    """Localiza filas de SKUs, fila de nº de cajas y filas de medidas sin fijar números de fila."""
    fila_sku_cab = fila_nombre_caja = None
    medidas = {}
    fila_total = None
    for (r, c), v in sorted(vals.items()):
        if c == 1 and isinstance(v, str):
            t = v.strip().lower()
            if t == "sku" and fila_sku_cab is None:
                fila_sku_cab = r
            elif t == "name of box":
                fila_nombre_caja = r
            elif t in ETIQUETAS_MEDIDAS:
                medidas[ETIQUETAS_MEDIDAS[t]] = r
        if isinstance(v, str) and v.strip().lower().startswith("total box count"):
            fila_total = r
    if None in (fila_sku_cab, fila_nombre_caja, fila_total) or len(medidas) != 4:
        raise ValueError("estructura de hoja no reconocida")
    cab = {str(v).strip().lower(): c for (r, c), v in vals.items() if r == fila_sku_cab}
    col_esperada = next(c for k, c in cab.items() if k.startswith("expected quantity"))
    col_asin = cab.get("asin")
    col_fnsku = cab.get("fnsku")
    skus = []
    for r in range(fila_sku_cab + 1, fila_nombre_caja):
        sku = vals.get((r, 1))
        if sku:
            skus.append({"fila": r, "sku": str(sku).strip(),
                         "asin": vals.get((r, col_asin)), "fnsku": vals.get((r, col_fnsku)),
                         "esperadas": int(vals.get((r, col_esperada)) or 0)})
    total = vals.get((fila_total, PRIMERA_COL_CAJA))
    col_boxed = next((c for k, c in cab.items() if k.startswith("boxed quantity")), None)
    return {"skus": skus, "fila_total": fila_total, "cajas_estimadas": int(total or 1),
            "medidas": medidas, "col_boxed": col_boxed}


def leer_archivo(ruta):
    z = zipfile.ZipFile(ruta)
    strings = cadenas_compartidas(z)
    grupos = {}
    for nombre, path in hojas(z):
        m = re.match(r"pack group\s*-\s*(\d+)", nombre.strip().lower())
        if m:
            vals = valores_hoja(z.read(path), strings)
            info = estructura_grupo(vals)
            info.update(hoja=nombre, path=path)
            grupos[m.group(1)] = info
    if not grupos:
        sys.exit("No hay pestañas 'Pack Group - N'. ¿Es el archivo de contenido de cajas?")
    return z, grupos


# ---------- escritura ----------

def poner_celda(xml, fila, col, valor):
    """Escribe un número en (fila, col) respetando el orden de celdas dentro de la fila."""
    ref = f"{col_letra(col)}{fila}"
    m_fila = re.search(rf'<row r="{fila}"[^>]*?(?:/>|>.*?</row>)', xml, re.S)
    if not m_fila:
        raise ValueError(f"no existe la fila {fila}")
    fila_xml = m_fila.group(0)
    if fila_xml.endswith("/>"):
        fila_xml = fila_xml[:-2] + "></row>"
    celdas = list(re.finditer(r'<c r="([A-Z]+)\d+"[^>]*?(?:/>|>.*?</c>)', fila_xml, re.S))
    existente = next((c for c in celdas if c.group(1) == col_letra(col)), None)
    if existente:
        estilo = re.search(r'\ss="(\d+)"', existente.group(0))
        s = estilo.group(1) if estilo else ESTILO_CAJA
        if "<f>" in existente.group(0):
            raise ValueError(f"{ref} tiene fórmula; no se sobrescribe")
        nueva = f'<c r="{ref}" t="n" s="{s}"><v>{fmt(valor)}</v></c>'
        fila_nueva = fila_xml[:existente.start()] + nueva + fila_xml[existente.end():]
    else:
        nueva = f'<c r="{ref}" t="n" s="{ESTILO_CAJA}"><v>{fmt(valor)}</v></c>'
        siguiente = next((c for c in celdas if col_num(c.group(1)) > col), None)
        pos = siguiente.start() if siguiente else fila_xml.rindex("</row>")
        fila_nueva = fila_xml[:pos] + nueva + fila_xml[pos:]
    return xml[:m_fila.start()] + fila_nueva + xml[m_fila.end():]


def poner_cache_formula(xml, fila, col, valor):
    """Actualiza el valor cacheado de una celda con fórmula (p. ej. 'Boxed quantity')."""
    ref = f"{col_letra(col)}{fila}"
    patron = rf'(<c r="{ref}"[^>]*>\s*<f>[^<]*</f>\s*<v>)[^<]*(</v>)'
    return re.sub(patron, lambda m: m.group(1) + fmt(valor) + m.group(2), xml, count=1)


def rellenar(ruta, spec, salida):
    z, grupos = leer_archivo(ruta)
    err = Errores()
    spec_grupos = {str(k): v for k, v in (spec.get("grupos") or {}).items()}

    for g in spec_grupos:
        if g not in grupos:
            err.error(f"La spec tiene el grupo {g}, pero el archivo solo tiene {', '.join(sorted(grupos))}.")
    for g, info in sorted(grupos.items()):
        cajas = (spec_grupos.get(g) or {}).get("cajas") or []
        if not cajas:
            err.error(f"Grupo {g}: faltan las cajas en la spec.")
            continue
        if len(cajas) > MAX_CAJAS:
            err.error(f"Grupo {g}: {len(cajas)} cajas; la plantilla admite como máximo {MAX_CAJAS} por grupo.")
        if abs(len(cajas) - info["cajas_estimadas"]) > MAX_CAMBIO_CAJAS:
            err.error(f"Grupo {g}: Amazon estimó {info['cajas_estimadas']} cajas y solo deja variar ±{MAX_CAMBIO_CAJAS}.")
        skus_grupo = {s["sku"]: s for s in info["skus"]}
        sumas = {s: 0 for s in skus_grupo}
        for i, caja in enumerate(cajas, start=1):
            nombre = f"Grupo {g} caja {i}"
            unidades = caja.get("unidades") or {}
            if not unidades or sum(unidades.values()) <= 0:
                err.error(f"{nombre}: no lleva unidades.")
            for sku, n in unidades.items():
                validar_sku(sku, err)
                if sku not in skus_grupo:
                    err.error(f"{nombre}: {sku} no pertenece a este grupo de embalaje.")
                elif not isinstance(n, int) or n < 0:
                    err.error(f"{nombre}: unidades de {sku} deben ser un entero >= 0 (es {n!r}).")
                else:
                    sumas[sku] += n
            validar_caja(nombre, caja.get("peso"), caja.get("largo"), caja.get("ancho"), caja.get("alto"), err)
        for sku, s in skus_grupo.items():
            if sumas[sku] != s["esperadas"]:
                err.error(f"Grupo {g}: {sku} suma {sumas[sku]} uds en cajas, Amazon espera {s['esperadas']}.")

    err.informar_y_salir_si_hay_errores()

    nuevos = {}
    for g, info in grupos.items():
        xml = z.read(info["path"]).decode("utf-8")
        cajas = spec_grupos[g]["cajas"]
        xml = poner_celda(xml, info["fila_total"], PRIMERA_COL_CAJA, len(cajas))
        for i, caja in enumerate(cajas):
            col = PRIMERA_COL_CAJA + i
            for s in info["skus"]:
                n = caja["unidades"].get(s["sku"], 0)
                if n:
                    xml = poner_celda(xml, s["fila"], col, n)
            for campo, fila in info["medidas"].items():
                xml = poner_celda(xml, fila, col, caja[campo])
        if info["col_boxed"]:
            for s in info["skus"]:
                xml = poner_cache_formula(xml, s["fila"], info["col_boxed"], s["esperadas"])
        nuevos[info["path"]] = xml.encode("utf-8")

    Path(salida).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(salida, "w") as out:
        for item in z.infolist():
            datos = nuevos.get(item.filename, z.read(item.filename))
            out.writestr(item, datos, compress_type=zipfile.ZIP_DEFLATED)

    # Resumen
    total_uds = total_cajas = 0
    peso_total = 0.0
    for g in sorted(grupos):
        for i, caja in enumerate(spec_grupos[g]["cajas"], start=1):
            uds = sum(caja["unidades"].values())
            total_uds += uds
            total_cajas += 1
            peso_total += caja["peso"]
            print(f"P{g} - B{i}: {uds} uds {caja['unidades']} | {caja['peso']} kg | "
                  f"{caja['ancho']}×{caja['largo']}×{caja['alto']} cm (ancho×largo×alto)")
    print(f"OK: {salida} — {len(grupos)} grupo(s), {total_cajas} caja(s), {total_uds} uds, {peso_total:g} kg en total.")


def imprimir_lectura(ruta):
    _, grupos = leer_archivo(ruta)
    resumen = {g: {"hoja": i["hoja"], "cajas_estimadas_por_amazon": i["cajas_estimadas"],
                   "skus": [{k: s[k] for k in ("sku", "asin", "fnsku", "esperadas")} for s in i["skus"]]}
               for g, i in sorted(grupos.items())}
    print(json.dumps(resumen, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[2] == "--leer":
        imprimir_lectura(sys.argv[1])
    elif len(sys.argv) == 4:
        rellenar(sys.argv[1], cargar_spec(sys.argv[2]), sys.argv[3])
    else:
        sys.exit(__doc__)
