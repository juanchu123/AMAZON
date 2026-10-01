"""
audit.py
--------
Diagnóstico de un ASIN contra la "definición de hecho" del documento
(sección 8) y elección DETERMINISTA del siguiente campo a trabajar.

El orden de prioridad no lo decide la IA: primero lo que es un error (o lo
que Amazon puede reescribir solo, como un título de más de 75 caracteres sin
Brand Registry), luego lo que falta, y solo después lo que se puede mejorar.
La IA redacta, pero no elige qué tocar.
"""

from dataclasses import dataclass, field

from limits import Limits
from listing_state import ListingState
from textutil import tokens, utf8_len

OK, FALLO, DESCONOCIDO, NO_APLICA = "ok", "fallo", "desconocido", "no aplica"


@dataclass
class Check:
    nombre: str
    estado: str
    detalle: str = ""


@dataclass
class AuditResult:
    asin: str
    checks: list[Check] = field(default_factory=list)
    alertas: list[str] = field(default_factory=list)
    siguiente_campo: str | None = None
    es_correccion: bool = False
    motivo_siguiente: str = ""

    @property
    def puntuacion(self) -> float | None:
        evaluables = [c for c in self.checks if c.estado in (OK, FALLO)]
        if not evaluables:
            return None
        return round(100 * sum(c.estado == OK for c in evaluables) / len(evaluables))


def _main_keyword_early(titulo: str, kw: str | None) -> tuple[str, str]:
    if not kw:
        return DESCONOCIDO, "define keyword_principal en config.json"
    t_toks, k_toks = tokens(titulo), tokens(kw)
    window = set(t_toks[:7])  # "en las primeras palabras" (móvil)
    if k_toks and all(t in window for t in k_toks):
        return OK, f"'{kw}' en las primeras palabras"
    return FALLO, f"'{kw}' no está en las primeras palabras del título"


def run_audit(state: ListingState, limits: Limits, keyword_principal: str | None,
              research_rows: list[dict], indexation_rate: float | None,
              brand_registry: bool = False) -> AuditResult:
    r = AuditResult(asin=state.asin)
    add = lambda n, e, d="": r.checks.append(Check(n, e, d))

    # ---- salud del listing (si esto falla, no se propone contenido)
    if not state.es_comprable:
        r.alertas.append(
            f"El listing NO está en estado BUYABLE (estado: {state.estado or 'desconocido'}). "
            "Sin oferta comprable no hay ventas ni anuncios. No se proponen cambios de contenido hasta resolverlo."
        )
    for i in state.issues_graves:
        r.alertas.append(f"Amazon marca un ERROR en el listing: {i.get('message', '')[:200]}")
    add("Sin errores de listing en Amazon", OK if not state.issues_graves else FALLO,
        f"{len(state.issues_graves)} errores")

    # ---- título
    tl = limits.titulo
    over = tl.max_chars and len(state.titulo) > tl.max_chars
    add(f"Título ≤ {tl.max_chars} caracteres", FALLO if over else OK, f"{len(state.titulo)} caracteres")
    if over and not brand_registry:
        r.alertas.append(
            f"El título tiene {len(state.titulo)} caracteres (> {tl.max_chars}). Sin Brand Registry, Amazon "
            "puede reescribirlo con IA sin aviso. Prioridad máxima."
        )
    add("Keyword principal al inicio del título", *_main_keyword_early(state.titulo, keyword_principal))

    # ---- item highlights
    if state.item_highlights is None:
        add("Item Highlights relleno", DESCONOCIDO, "el esquema SP-API no expone el campo; mirar en el editor")
    else:
        hl = limits.item_highlights
        if not state.item_highlights.strip():
            add("Item Highlights relleno", FALLO, "vacío")
        elif hl.max_chars and len(state.item_highlights) > hl.max_chars:
            add("Item Highlights relleno", FALLO, f"{len(state.item_highlights)} caracteres > {hl.max_chars}")
        else:
            add("Item Highlights relleno", OK, f"{len(state.item_highlights)} caracteres")

    # ---- bullets
    n_b = len([b for b in state.bullets if b.strip()])
    add(f"{limits.bullets_num} bullets", OK if n_b >= limits.bullets_num else FALLO, f"{n_b} bullets")

    # ---- backend
    bb = utf8_len(state.backend)
    if not state.backend.strip():
        add("Backend relleno y ≤ límite", FALLO, "vacío")
    elif limits.backend.max_bytes and bb > limits.backend.max_bytes:
        add("Backend relleno y ≤ límite", FALLO, f"{bb} bytes > {limits.backend.max_bytes}: Amazon puede ignorarlo entero")
    else:
        rep = set(tokens(state.backend)) & set(tokens(state.visible_text()))
        add("Backend relleno y ≤ límite", OK, f"{bb} bytes")
        add("Backend sin repetir texto visible", FALLO if rep else OK,
            ("repite: " + " ".join(sorted(rep))) if rep else "")

    # ---- imágenes
    main = next((i for i in state.imagenes if i["variant"] == "MAIN"), None)
    if not state.imagenes:
        add("Imagen principal ≥ 1.000 px", DESCONOCIDO, "el catálogo no devolvió imágenes")
        add("Galería de 7–9 imágenes", DESCONOCIDO)
    else:
        lado = max(main.get("width") or 0, main.get("height") or 0) if main else 0
        add("Imagen principal ≥ 1.000 px", OK if lado >= 1000 else FALLO, f"{lado} px")
        add("Galería de 7–9 imágenes", OK if len(state.imagenes) >= 7 else FALLO, f"{len(state.imagenes)} imágenes")
    add("Fondo blanco puro / sin texto en la principal", DESCONOCIDO, "revisión visual manual")
    add("Vídeo en el listing", DESCONOCIDO, "la SP-API no lo expone; comprobar a mano")
    add("A+ publicado", NO_APLICA if not brand_registry else DESCONOCIDO,
        "requiere Brand Registry" if not brand_registry else "")

    # ---- cumplimiento
    if limits.gpsr_attrs:
        faltan = [a for a in limits.gpsr_attrs if a not in state.atributos_presentes]
        add("Datos GPSR / seguridad cargados", FALLO if faltan else OK,
            ("faltan: " + ", ".join(faltan[:6])) if faltan else "")
    else:
        add("Datos GPSR / seguridad cargados", DESCONOCIDO, "confirmar en Seller Central y con legal")

    # ---- atributos
    if limits.schema_props:
        vacios = sorted(limits.schema_props - set(state.atributos_presentes))
        add("Atributos completos (incl. opcionales)", OK if not vacios else FALLO,
            f"{len(vacios)} atributos sin rellenar (p. ej. {', '.join(vacios[:5])})" if vacios else "")

    # ---- stock y reseñas
    if state.stock_disponible is None:
        add("Stock disponible", DESCONOCIDO)
    else:
        add("Stock disponible", OK if state.stock_disponible > 0 else FALLO, f"{state.stock_disponible} uds")
        if state.stock_disponible == 0:
            r.alertas.append("Sin stock FBA disponible: los anuncios se pausan y el ranking cae. Avisar a logística.")
    add("≥ 15 reseñas y ≥ 3,5★", DESCONOCIDO, "la SP-API no da reseñas; comprobar a mano")

    # ---- indexación
    if indexation_rate is None:
        add("Indexación ≥ 80 % (aprox.)", DESCONOCIDO)
    else:
        add("Indexación ≥ 80 % (aprox.)", OK if indexation_rate >= 0.8 else FALLO,
            f"{round(indexation_rate * 100)} % encontradas en catálogo")

    # ---- keywords que convierten y no están en el texto
    sin_cubrir = [k for k in research_rows if k["compras"] > 0 and not k["cubierta"]]
    add("Keywords que convierten cubiertas por el texto", FALLO if sin_cubrir else OK,
        ", ".join(k["keyword"] for k in sin_cubrir[:5]))

    _choose_next(r, state, limits, n_b, bb, sin_cubrir)
    return r


def _choose_next(r: AuditResult, state: ListingState, limits: Limits, n_bullets: int,
                 backend_bytes: int, sin_cubrir: list[dict]) -> None:
    if not state.es_comprable:
        return
    tl = limits.titulo
    if tl.max_chars and len(state.titulo) > tl.max_chars:
        r.siguiente_campo, r.es_correccion = "titulo", True
        r.motivo_siguiente = f"Título de {len(state.titulo)} caracteres; el límite es {tl.max_chars}."
    elif limits.backend.max_bytes and backend_bytes > limits.backend.max_bytes:
        r.siguiente_campo, r.es_correccion = "backend", True
        r.motivo_siguiente = f"Backend de {backend_bytes} bytes; Amazon puede ignorarlo entero."
    elif state.item_highlights is not None and not state.item_highlights.strip():
        r.siguiente_campo = "item_highlights"
        r.motivo_siguiente = "Item Highlights vacío: 125 caracteres indexables sin usar."
    elif n_bullets < limits.bullets_num:
        r.siguiente_campo = "bullets"
        r.motivo_siguiente = f"Solo hay {n_bullets} bullets de {limits.bullets_num}."
    elif not state.backend.strip():
        r.siguiente_campo = "backend"
        r.motivo_siguiente = "Backend vacío."
    elif sin_cubrir:
        r.siguiente_campo = "backend"
        r.motivo_siguiente = (
            "Keywords que ya convierten en Ads y no aparecen en el listing: "
            + ", ".join(k["keyword"] for k in sin_cubrir[:5])
        )
    elif any(c.nombre == "Keyword principal al inicio del título" and c.estado == FALLO for c in r.checks):
        r.siguiente_campo = "titulo"
        r.motivo_siguiente = "La keyword principal no está en las primeras palabras del título."
    elif any(c.nombre.startswith("Backend sin repetir") and c.estado == FALLO for c in r.checks):
        r.siguiente_campo = "backend"
        r.motivo_siguiente = "El backend repite palabras del texto visible (bytes desperdiciados)."
