"""
listing_state.py
----------------
Convierte las respuestas crudas de la SP-API en una "foto" del listing con
los campos que importan (título, highlights, bullets, descripción, backend,
imágenes, estado, stock). Esa foto es lo que se guarda antes de cada cambio
(regla 6: registrar el estado anterior para poder revertir) y lo que se
compara semana a semana para detectar cambios que nadie ha registrado, por
ejemplo la reescritura del título por la IA de Amazon.
"""

from dataclasses import asdict, dataclass, field

from limits import ATTR

TEXT_FIELDS = ("titulo", "item_highlights", "bullets", "descripcion", "backend")


@dataclass
class ListingState:
    asin: str
    sku: str
    marketplace_id: str
    product_type: str | None
    titulo: str = ""
    item_highlights: str | None = None   # None = el esquema no tiene el campo / no se pudo leer
    bullets: list[str] = field(default_factory=list)
    descripcion: str = ""
    backend: str = ""
    marca: str = ""
    estado: list[str] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    imagenes: list[dict] = field(default_factory=list)  # [{variant, width, height}]
    stock_disponible: int | None = None
    atributos_presentes: list[str] = field(default_factory=list)
    metricas: dict | None = None

    def text_fields(self) -> dict:
        return {k: getattr(self, k) for k in TEXT_FIELDS}

    def visible_text(self) -> str:
        return " ".join([self.titulo, self.item_highlights or "", *self.bullets])

    def all_text(self) -> str:
        return " ".join([self.visible_text(), self.descripcion, self.backend])

    @property
    def es_comprable(self) -> bool:
        return "BUYABLE" in self.estado

    @property
    def issues_graves(self) -> list[dict]:
        return [i for i in self.issues if i.get("severity") == "ERROR"]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ListingState":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _values(attrs: dict, name: str, marketplace_id: str, idioma: str) -> list[str]:
    """Valores de un atributo para este marketplace, prefiriendo el idioma pedido."""
    entries = attrs.get(name) or []
    entries = [e for e in entries if e.get("marketplace_id") in (None, marketplace_id)]
    preferred = [e for e in entries if e.get("language_tag") in (None, idioma)]
    return [str(e.get("value", "")) for e in (preferred or entries) if e.get("value") is not None]


def build_state(asin: str, sku: str, marketplace_id: str, idioma: str,
                listing: dict, catalog: dict | None, inventory: dict | None,
                highlights_attr: str | None) -> ListingState:
    attrs = listing.get("attributes") or {}
    summaries = [s for s in listing.get("summaries") or [] if s.get("marketplaceId") == marketplace_id]
    summary = summaries[0] if summaries else {}

    def one(name: str) -> str:
        vals = _values(attrs, name, marketplace_id, idioma)
        return vals[0] if vals else ""

    imagenes = []
    for block in (catalog or {}).get("images") or []:
        if block.get("marketplaceId") not in (None, marketplace_id):
            continue
        # El catálogo devuelve varias resoluciones de cada imagen: nos quedamos con la mayor por variante.
        best: dict[str, dict] = {}
        for img in block.get("images") or []:
            v = img.get("variant", "")
            if v not in best or (img.get("width") or 0) > (best[v].get("width") or 0):
                best[v] = img
        imagenes = [{"variant": v, "width": i.get("width"), "height": i.get("height")} for v, i in best.items()]

    stock = None
    if inventory:
        stock = ((inventory.get("inventoryDetails") or {}).get("fulfillableQuantity"))
        if stock is None:
            stock = inventory.get("totalQuantity")

    return ListingState(
        asin=asin,
        sku=sku,
        marketplace_id=marketplace_id,
        product_type=summary.get("productType") or next(
            (p.get("productType") for p in (catalog or {}).get("productTypes") or []), None),
        titulo=one(ATTR["titulo"]) or summary.get("itemName", ""),
        item_highlights=(one(highlights_attr) if highlights_attr else None),
        bullets=_values(attrs, ATTR["bullets"], marketplace_id, idioma),
        descripcion=one(ATTR["descripcion"]),
        backend=" ".join(_values(attrs, ATTR["backend"], marketplace_id, idioma)).strip(),
        marca=one("brand"),
        estado=summary.get("status") or [],
        issues=listing.get("issues") or [],
        imagenes=imagenes,
        stock_disponible=stock,
        atributos_presentes=sorted(attrs),
    )


def diff_states(old: ListingState, new: ListingState) -> dict:
    """Campos de texto que han cambiado entre dos fotos: {campo: (antes, después)}."""
    out = {}
    for k in TEXT_FIELDS:
        a, b = getattr(old, k), getattr(new, k)
        if _canon(a) != _canon(b):
            out[k] = (a, b)
    return out


def _canon(v):
    if isinstance(v, list):
        return [" ".join(str(x).split()) for x in v]
    return " ".join(str(v).split()) if v is not None else None
