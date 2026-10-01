"""
limits.py
---------
Límites de cada campo del listing.

Regla 8 del documento: "Datos dudosos se marcan como dudosos. Si el límite
no está confirmado en el editor real, se usa el valor más conservador y se
avisa". Por eso:
  - Hay valores por defecto (los de la guía, ya conservadores).
  - Si el esquema del tipo de producto de la SP-API trae un límite, se usa el
    MÁS BAJO de los dos (el esquema puede seguir diciendo 200 en el título
    aunque la norma nueva sea 75; el valor por defecto puede ser más
    permisivo que lo que Amazon realmente acepta).
  - Cada límite lleva su "fuente" para que el informe diga si está confirmado.
"""

from dataclasses import dataclass

# Atributos SP-API de cada campo del listing.
ATTR = {
    "titulo": "item_name",
    "bullets": "bullet_point",
    "descripcion": "product_description",
    "backend": "generic_keyword",
}

DEFAULTS = {
    "titulo": {"max_chars": 75},             # desde 27/07/2026 (antes 200)
    "item_highlights": {"max_chars": 125},
    "bullet": {"max_chars": 250},            # guía: ~200–255; se usa el lado conservador
    "bullets_num": 5,
    "descripcion": {"max_chars": 2000},
    "backend": {"max_bytes": 249},           # Europa; un blog dice 500 -> se ignora
}


@dataclass
class FieldLimit:
    max_chars: int | None = None
    max_bytes: int | None = None
    fuente: str = "valor por defecto de la guía (sin confirmar en Seller Central)"

    def describe(self) -> str:
        parts = []
        if self.max_chars:
            parts.append(f"{self.max_chars} caracteres")
        if self.max_bytes:
            parts.append(f"{self.max_bytes} bytes")
        return " / ".join(parts) + f" — {self.fuente}"


@dataclass
class Limits:
    titulo: FieldLimit
    item_highlights: FieldLimit
    bullet: FieldLimit
    bullets_num: int
    descripcion: FieldLimit
    backend: FieldLimit
    highlights_attr: str | None  # nombre real del atributo de Item Highlights, si el esquema lo tiene
    gpsr_attrs: list[str]        # atributos de seguridad/GPSR que el esquema define
    schema_props: set[str]

    def for_field(self, campo: str) -> FieldLimit:
        return {
            "titulo": self.titulo,
            "item_highlights": self.item_highlights,
            "descripcion": self.descripcion,
            "backend": self.backend,
            "bullets": self.bullet,
        }[campo]


def _value_constraints(prop: dict) -> tuple[int | None, int | None, int | None]:
    """Devuelve (maxLength, maxUtf8ByteLength, maxItems) de un atributo del esquema."""
    max_items = prop.get("maxItems")
    value = ((prop.get("items") or {}).get("properties") or {}).get("value") or {}
    return value.get("maxLength"), value.get("maxUtf8ByteLength"), max_items


def _merge(default: dict, schema_chars: int | None, schema_bytes: int | None) -> FieldLimit:
    d_chars, d_bytes = default.get("max_chars"), default.get("max_bytes")
    if schema_chars is None and schema_bytes is None:
        return FieldLimit(d_chars, d_bytes)
    chars = min(x for x in (d_chars, schema_chars) if x) if (d_chars or schema_chars) else None
    nbytes = min(x for x in (d_bytes, schema_bytes) if x) if (d_bytes or schema_bytes) else None
    fuente = (
        f"esquema SP-API (chars={schema_chars}, bytes={schema_bytes}) "
        f"cruzado con la guía; se usa el más bajo"
    )
    return FieldLimit(chars, nbytes, fuente)


def limits_from_schema(schema: dict | None) -> Limits:
    props = (schema or {}).get("properties") or {}

    def lim(key: str, attr: str | None) -> FieldLimit:
        if not attr or attr not in props:
            return FieldLimit(**DEFAULTS[key])
        c, b, _ = _value_constraints(props[attr])
        return _merge(DEFAULTS[key], c, b)

    highlights_attr = next((p for p in props if "highlight" in p.lower()), None)
    gpsr_attrs = sorted(
        p for p in props
        if any(s in p.lower() for s in ("gpsr", "safety", "responsible", "compliance", "warning"))
    )
    bullets_num = DEFAULTS["bullets_num"]
    if "bullet_point" in props:
        _, _, max_items = _value_constraints(props["bullet_point"])
        if max_items:
            bullets_num = min(bullets_num, max_items)

    return Limits(
        titulo=lim("titulo", "item_name"),
        item_highlights=lim("item_highlights", highlights_attr),
        bullet=lim("bullet", "bullet_point"),
        bullets_num=bullets_num,
        descripcion=lim("descripcion", "product_description"),
        backend=lim("backend", "generic_keyword"),
        highlights_attr=highlights_attr,
        gpsr_attrs=gpsr_attrs,
        schema_props=set(props),
    )
