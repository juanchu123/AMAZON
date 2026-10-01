"""
keywords.py
-----------
Investigación de keywords con lo que tenemos SIN Brand Registry (no hay
Brand Analytics ni Search Query Performance):

  1. Exports de Amazon Ads (tabla de Segmentación o informe de términos de
     búsqueda): lo que de verdad teclean los clientes y si convierte.
  2. logs/historical_keywords.json del agente de Ads (solo clics/compras).
  3. Keywords semilla que Juan pone en config.json.

Con eso se calcula qué keywords convierten, cuáles ya están cubiertas por el
texto del listing y cuáles faltan, y se propone un backend candidato
determinista (sin IA) que el redactor puede usar de punto de partida.
"""

import csv
import glob
import json
from dataclasses import dataclass, field
from pathlib import Path

from listing_state import ListingState
from textutil import norm, strip_accents, tokens, utf8_len

KEYWORD_COLUMNS = (
    "palabra clave", "término de búsqueda de cliente", "termino de busqueda de cliente",
    "término de búsqueda", "customer search term", "keyword", "targeting",
)


def parse_number(raw: str) -> float:
    """Amazon exporta a veces con punto decimal ("1.47") y a veces con coma
    ("0,0227" o "1.234,56 €"). Se detecta cuál es el separador decimal."""
    s = (raw or "").replace("€", "").replace("%", "").replace(" ", "").strip()
    if not s or s in ("—", "-"):
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


@dataclass
class KeywordStat:
    keyword: str
    impresiones: float = 0
    clics: float = 0
    compras: float = 0
    fuentes: set = field(default_factory=set)
    semilla: bool = False

    @property
    def puntuacion(self) -> float:
        # Convertir pesa mucho más que tener tráfico (la guía: "la conversión manda").
        return self.compras * 20 + self.clics + self.impresiones / 200 + (5 if self.semilla else 0)


def _col(row: dict, names) -> str | None:
    for k in row:
        if k and k.strip().lower() in names:
            return row[k]
    return None


def load_ads_csvs(patterns: list[str]) -> list[dict]:
    rows = []
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            with open(path, encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    kw = _col(row, KEYWORD_COLUMNS)
                    if not kw or not kw.strip():
                        continue
                    rows.append({
                        "keyword": kw.strip(),
                        "impresiones": parse_number(_col(row, ("impresiones", "impressions")) or ""),
                        "clics": parse_number(_col(row, ("clics", "clicks")) or ""),
                        "compras": parse_number(_col(row, ("compras", "pedidos", "orders", "purchases")) or ""),
                        "fuente": Path(path).name,
                    })
    return rows


def load_historical(path: str | None, asin: str, sku: str | None) -> list[dict]:
    """historical_keywords.json del agente de Ads. Solo se leen clics y compras:
    son enteros y fiables; coste/ventas se ignoran por cómo se parsean allí."""
    if not path or not Path(path).exists():
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for r in data:
        if r.get("producto") not in (asin, sku):
            continue
        out.append({
            "keyword": r.get("keyword", ""),
            "impresiones": r.get("impressions", 0) or 0,
            "clics": r.get("clicks", 0) or 0,
            "compras": r.get("orders", 0) or 0,
            "fuente": "historical_keywords.json",
        })
    return out


def aggregate(rows: list[dict], seeds: list[str]) -> list[KeywordStat]:
    stats: dict[str, KeywordStat] = {}
    for r in rows:
        k = norm(r["keyword"])
        if not k or k.startswith(("asin=", "category=", "b0")):
            continue  # segmentaciones por producto/categoría, no son palabras
        s = stats.setdefault(k, KeywordStat(keyword=r["keyword"].strip().lower()))
        s.impresiones += r["impresiones"]
        s.clics += r["clics"]
        s.compras += r["compras"]
        s.fuentes.add(r["fuente"])
    for seed in seeds:
        k = norm(seed)
        s = stats.setdefault(k, KeywordStat(keyword=seed.strip().lower()))
        s.semilla = True
        s.fuentes.add("semilla")
    return sorted(stats.values(), key=lambda s: s.puntuacion, reverse=True)


def coverage(kw: str, state: ListingState) -> dict:
    """¿Dónde está cubierta la keyword? Un término basta una vez en cualquier campo
    indexado; aquí se mira palabra a palabra porque Amazon recombina campos."""
    campos = {
        "titulo": state.titulo,
        "item_highlights": state.item_highlights or "",
        "bullets": " ".join(state.bullets),
        "descripcion": state.descripcion,
        "backend": state.backend,
    }
    kw_toks = tokens(kw)
    por_campo = {c: set(tokens(t)) for c, t in campos.items()}
    todos = set().union(*por_campo.values())
    faltan = [t for t in kw_toks if t not in todos]
    return {
        "cubierta": not faltan and bool(kw_toks),
        "faltan": faltan,
        "en": [c for c, ts in por_campo.items() if kw_toks and all(t in ts for t in kw_toks)],
    }


def build_backend_candidate(research_rows: list[dict], state: ListingState, max_bytes: int,
                            extra_excluded: set[str] | None = None) -> str:
    """Backend determinista: palabras de las keywords que convierten y que NO
    están en el texto visible, sin repetir, hasta llenar max_bytes."""
    visibles = set(tokens(state.visible_text(), drop_stopwords=False))
    excluded = visibles | (extra_excluded or set())
    out, vistos = [], set()
    for row in research_rows:
        for w in tokens(row["keyword"]):
            k = strip_accents(w)
            if k in excluded or k in vistos:
                continue
            candidate = " ".join(out + [w])
            if utf8_len(candidate) > max_bytes:
                return " ".join(out)
            out.append(w)
            vistos.add(k)
    return " ".join(out)


def research(state: ListingState, csv_patterns: list[str], historico_json: str | None,
             seeds: list[str]) -> list[dict]:
    rows = load_ads_csvs(csv_patterns) + load_historical(historico_json, state.asin, state.sku)
    out = []
    for s in aggregate(rows, seeds):
        cov = coverage(s.keyword, state)
        out.append({
            "keyword": s.keyword,
            "impresiones": int(s.impresiones),
            "clics": int(s.clics),
            "compras": int(s.compras),
            "semilla": s.semilla,
            "fuentes": sorted(s.fuentes),
            "puntuacion": round(s.puntuacion, 1),
            **cov,
        })
    return out
