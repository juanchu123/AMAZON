"""
indexation.py
-------------
Comprobación de indexación vía SP-API.

Límite honesto: la SP-API NO tiene un "¿está mi ASIN indexado para esta
keyword?". Lo más parecido es buscar la keyword en el catálogo
(searchCatalogItems) y ver si el ASIN sale en las primeras páginas. Eso es
una APROXIMACIÓN, no la búsqueda real de un cliente:
  - "encontrado"  -> buena señal de que Amazon asocia el ASIN con el término.
  - "no_encontrado" -> NO prueba que no esté indexado (puede estar en la
    página 10). Para confirmar, el informe incluye el enlace
    "keyword + ASIN" de Amazon.es para comprobarlo a mano en incógnito.
"""

from datetime import date
from urllib.parse import quote_plus

from sp_api import SPAPIError


def manual_check_url(keyword: str, asin: str) -> str:
    return f"https://www.amazon.es/s?k={quote_plus(keyword + ' ' + asin)}"


def check_keywords(client, asin: str, keywords: list[str], pages: int = 2,
                   hoy: date | None = None) -> list[dict]:
    hoy = hoy or date.today()
    out = []
    for kw in keywords:
        estado, detalle = "no_encontrado", f"no aparece en las primeras {pages} páginas del catálogo"
        token = None
        try:
            for page in range(1, pages + 1):
                data = client.search_catalog(kw, page_token=token)
                asins = [i.get("asin") for i in data.get("items") or []]
                if asin in asins:
                    estado, detalle = "encontrado", f"página {page} del catálogo"
                    break
                token = (data.get("pagination") or {}).get("nextToken")
                if not token:
                    break
        except SPAPIError as e:
            estado, detalle = "error", str(e)[:200]
        out.append({
            "fecha": hoy.isoformat(),
            "asin": asin,
            "keyword": kw,
            "estado": estado,
            "detalle": detalle,
            "metodo": "sp-api searchCatalogItems (aproximación)",
            "comprobar_a_mano": manual_check_url(kw, asin),
        })
    return out


def indexation_rate(rows: list[dict]) -> float | None:
    valid = [r for r in rows if r["estado"] in ("encontrado", "no_encontrado")]
    if not valid:
        return None
    return sum(r["estado"] == "encontrado" for r in valid) / len(valid)
