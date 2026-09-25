"""
import_historical_data.py
--------------------------
Importa un export real de Amazon Ads (el CSV que se descarga con el botón
"Exportar" de la tabla de Segmentación de un grupo de anuncios) como
CONTEXTO histórico — no como decisiones del sistema. Es rendimiento real
que Juan ya tenía antes de que este agente existiera, así que la IA debe
poder verlo desde el primer día, no solo lo que el propio sistema vaya
generando a partir de ahora.

Uso:
    python src/import_historical_data.py export.csv --producto B0DHYBY6MS --campana "Campaña - 27/6/2025 18:41:26.479"

Por qué necesita --producto explícito: el export de la tabla de
Segmentación (Palabra clave, Puja, Impresiones, Clics, Coste, Compras,
Ventas) NO incluye el SKU/ASIN del producto — eso vive en la pestaña
"Anuncios" del grupo, aparte. Como normalmente un grupo de anuncios
promociona un único producto, se pasa una vez por línea de comandos en
vez de tener que adivinarlo del CSV.

Guarda el resultado en logs/historical_keywords.json — SEPARADO de
logs/decisions.jsonl a propósito: decisions.jsonl son acciones que este
sistema ha tomado y evaluado; historical_keywords.json es contexto de
rendimiento que alguien más (Juan, o el propio Amazon) ya generó antes.
Nunca se mezclan como si fueran lo mismo.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

HISTORICAL_FILE = Path(__file__).resolve().parent.parent / "logs" / "historical_keywords.json"

# Nombres de columna tal como aparecen en el export real de Amazon Ads
# (visto en la cuenta de FreshFinder, sept. 2026). Si Amazon cambia el
# nombre de una columna, ajustar aquí — es el único sitio que lo sabe.
COLUMN_MAP = {
    "palabra clave": "keyword",
    "tipo de coincidencia": "match_type",
    "tipo de coincidencia objetivo": "match_type",
    "puja": "bid",
    "impresiones": "impressions",
    "clics": "clicks",
    "coste total": "cost",
    "compras": "orders",
    "ventas": "sales",
}


def _normalize_column_name(col: str) -> str:
    """Amazon a veces añade la unidad entre paréntesis al nombre de
    columna (p.ej. "Coste total (EUR)" en vez de "Coste total", visto en
    el export real de sept. 2026) — se quita antes de buscar en
    COLUMN_MAP para no depender de si Amazon la incluye o no.
    """
    return re.sub(r"\([^)]*\)", "", col).strip().lower()


def _parse_amount(value: str) -> float:
    """Amazon no exporta siempre el mismo formato de número decimal: se ha
    visto tanto "1.234,56 €" (punto de miles, coma decimal) como "17.4"
    sin símbolo de moneda ni separador de miles, con punto decimal normal
    (export real de sept. 2026). Tratar SIEMPRE el punto como separador
    de miles asumiendo el primer formato rompía el segundo en silencio —
    "17.4" se convertía en 174.0, un error de x10 que puede invertir una
    decisión de ACOS. Se detecta el formato por los separadores presentes
    en vez de asumir uno fijo.
    """
    value = value.replace("€", "").strip()
    if not value or value == "—":
        return 0.0
    if "," in value and "." in value:
        # "1.234,56" -> punto de miles, coma decimal
        value = value.replace(".", "").replace(",", ".")
    elif "," in value:
        # "1234,56" -> coma decimal, sin separador de miles
        value = value.replace(",", ".")
    # si solo hay puntos (o ninguno), ya está en formato de punto decimal
    return float(value)


def _normalize_row(raw_row: dict) -> dict:
    """Convierte una fila del CSV (con nombres de columna en español, tal
    como los exporta Amazon) a nuestro esquema interno normalizado.
    Columnas que no reconocemos se ignoran — mejor perder un dato extra
    que romper la importación por una columna nueva que Amazon añada.
    """
    out = {}
    for col, value in raw_row.items():
        key = COLUMN_MAP.get(_normalize_column_name(col))
        if key is None:
            continue
        if key in ("impressions", "clicks", "orders"):
            out[key] = int(value.replace(".", "").replace(",", "")) if value and value != "—" else 0
        elif key in ("bid", "cost", "sales"):
            out[key] = _parse_amount(value)
        else:
            out[key] = value.strip()
    return out


def import_csv(csv_path: str, producto: str, campana: str, ad_group: str = "") -> list[dict]:
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = [_normalize_row(row) for row in reader]

    for row in rows:
        row["producto"] = producto
        row["campana"] = campana
        row["ad_group"] = ad_group
        if row.get("sales", 0) > 0:
            row["acos"] = round(row.get("cost", 0.0) / row["sales"], 3)
        else:
            row["acos"] = None

    return rows


def load_historical_data() -> list[dict]:
    """Lo que usa ai_marketing_agent.py para incluir este contexto en el
    prompt. Si no se ha importado nada todavía, devuelve una lista vacía
    (no es un error — simplemente no hay histórico previo que aportar).
    """
    if not HISTORICAL_FILE.exists():
        return []
    with open(HISTORICAL_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_historical_data(rows: list[dict], merge: bool = True) -> None:
    """Guarda las filas importadas. merge=True (por defecto) añade a lo
    que ya hubiera importado antes, en vez de machacarlo — así se pueden
    ir sumando exports de distintos grupos de anuncios / productos con
    varias ejecuciones de este script.
    """
    HISTORICAL_FILE.parent.mkdir(exist_ok=True)
    existing = load_historical_data() if merge else []
    all_rows = existing + rows
    with open(HISTORICAL_FILE, "w", encoding="utf-8") as f:
        json.dump(all_rows, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", help="Ruta al CSV exportado desde Amazon Ads")
    parser.add_argument("--producto", required=True, help="SKU o ASIN del producto de este grupo de anuncios")
    parser.add_argument("--campana", required=True, help="Nombre de la campaña (trazabilidad)")
    parser.add_argument("--ad-group", default="", help="Nombre del grupo de anuncios (opcional)")
    parser.add_argument("--reemplazar", action="store_true", help="Reemplaza el histórico en vez de añadir a lo existente")
    args = parser.parse_args()

    rows = import_csv(args.csv_path, args.producto, args.campana, args.ad_group)
    con_actividad = [r for r in rows if r.get("clicks", 0) > 0]
    print(f"Importadas {len(rows)} filas ({len(con_actividad)} con clics reales) de {args.csv_path}")

    save_historical_data(rows, merge=not args.reemplazar)
    print(f"Guardado en {HISTORICAL_FILE}")


if __name__ == "__main__":
    main()
