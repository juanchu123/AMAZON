"""
safety.py
---------
La barrera que NUNCA se salta (equivalente a sanitize_commands() del agente
de Ads): todo lo que proponga el redactor (Cowork, Claude vía API o una
persona) pasa por validate_proposal() antes de convertirse en un paquete
listo para publicar.

La IA decide el QUÉ y el POR QUÉ; este archivo decide si se puede publicar.
Si algo no cumple, la propuesta se rechaza con el motivo; nunca se "arregla"
en silencio algo que cambie el sentido del texto. Lo único que se normaliza
automáticamente es el backend (minúsculas, quitar palabras vacías,
repeticiones y palabras que ya están en el texto visible), y se avisa de
cada cosa quitada.
"""

import re
from dataclasses import dataclass, field

from limits import Limits
from listing_state import ListingState
from textutil import STOPWORDS_ES, contains_phrase, norm, strip_accents, tokens, utf8_len

CAMPOS = ("titulo", "item_highlights", "bullets", "descripcion", "backend")

# Lenguaje promocional (regla 7). Error = no se publica; aviso = revisar.
PROMO_ERROR = [
    "oferta", "descuento", "rebaja", "rebajas", "gratis", "envio gratis", "barato", "precio",
    "no 1", "nº1", "nº 1", "numero 1", "top ventas", "superventas", "mas vendido",
    "best seller", "bestseller", "promocion", "liquidacion", "black friday", "garantizado",
    "100% garantizado", "chollo", "outlet", "ganga",
]
PROMO_WARN = ["mejor", "el mejor", "increible", "perfecto", "premium", "calidad superior"]

# Afirmaciones médicas / de seguridad / conformidad: solo con confirmación de legal (regla 7).
CLAIMS = [
    "certificado", "certificada", "homologado", "homologada", "seguro para ninos",
    "100% seguro", "no toxico", "sin bpa", "antibacteriano", "hipoalergenico", "cura",
    "terapeutico", "medico", "aprobado por", "ce certificado", "a prueba de golpes",
    "irrompible", "ignifugo",
]

TITLE_FORBIDDEN_CHARS = set("!$?_{}^¬¦~*#<>★☆✓✔✅®©™€£¡¿")
ASIN_RE = re.compile(r"\bB0[A-Z0-9]{8}\b", re.IGNORECASE)
URL_RE = re.compile(r"(https?://|www\.|\b[a-z0-9-]+\.(com|es|net|org|eu)\b)", re.IGNORECASE)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RE = re.compile(r"(\+\d{2}\s?)?\b\d{3}[\s.-]?\d{3}[\s.-]?\d{3}\b")
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


@dataclass
class ValidationResult:
    ok: bool
    campo: str
    valor_final: object
    errores: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    recuento: dict = field(default_factory=dict)


@dataclass
class ContentPolicy:
    marca_propia: str
    marcas_competidoras: list[str]
    marcas_de_dispositivos: list[str]
    claims_confirmados: list[str]
    margen_bytes_backend: int


def _common_checks(text: str, policy: ContentPolicy, where: str, errores: list, avisos: list,
                   allow_device_brands: bool = True) -> None:
    if ASIN_RE.search(text):
        errores.append(f"{where}: contiene un ASIN.")
    if URL_RE.search(text) or EMAIL_RE.search(text):
        errores.append(f"{where}: contiene una URL o un email.")
    if PHONE_RE.search(text):
        errores.append(f"{where}: parece contener un teléfono.")
    for b in policy.marcas_competidoras:
        if contains_phrase(text, b):
            errores.append(f"{where}: menciona la marca ajena '{b}'.")
    if not allow_device_brands:
        for b in policy.marcas_de_dispositivos:
            if contains_phrase(text, b):
                errores.append(f"{where}: menciona la marca '{b}' (no permitido en backend).")
    for w in PROMO_ERROR:
        if contains_phrase(text, w):
            errores.append(f"{where}: lenguaje promocional '{w}'.")
    for w in PROMO_WARN:
        if contains_phrase(text, w):
            avisos.append(f"{where}: '{w}' puede leerse como promocional; revísalo.")
    confirmed = [norm(c) for c in policy.claims_confirmados]
    for c in CLAIMS:
        if contains_phrase(text, c) and not any(c in cc or cc in c for cc in confirmed):
            errores.append(
                f"{where}: afirmación '{c}' sin confirmación de legal "
                "(añádela a claims_confirmados_por_legal solo si legal la respalda)."
            )
    if EMOJI_RE.search(text):
        errores.append(f"{where}: contiene emojis o símbolos decorativos.")


def _check_title(t: str, limits: Limits, policy: ContentPolicy, errores, avisos, recuento):
    lim = limits.titulo
    recuento["caracteres"] = len(t)
    if not t.strip():
        errores.append("Título vacío.")
        return
    if lim.max_chars and len(t) > lim.max_chars:
        errores.append(f"Título de {len(t)} caracteres; máximo {lim.max_chars}.")
    bad = sorted({c for c in t if c in TITLE_FORBIDDEN_CHARS})
    if bad:
        errores.append(f"Título con caracteres no permitidos: {' '.join(bad)}")
    counts: dict[str, int] = {}
    for w in tokens(t):
        counts[w] = counts.get(w, 0) + 1
    repetidas = [w for w, n in counts.items() if n > 2]
    if repetidas:
        errores.append(f"Título repite más de dos veces: {', '.join(repetidas)}")
    shouting = [w for w in re.findall(r"\b[A-ZÁÉÍÓÚÑ]{5,}\b", t)]
    if shouting:
        avisos.append(f"Título con palabras en mayúsculas completas: {', '.join(shouting)}")
    if policy.marca_propia:
        n_marca = len(re.findall(re.escape(norm(policy.marca_propia)), norm(t)))
        if n_marca == 0:
            avisos.append("El título no incluye la marca (fórmula: Marca + producto + atributo).")
        elif n_marca > 1:
            errores.append("El título repite la marca.")
        elif not norm(t).startswith(norm(policy.marca_propia)):
            avisos.append("La marca no está al principio del título (orden recomendado por Amazon).")
    _common_checks(t, policy, "Título", errores, avisos)


def _check_highlights(h: str, titulo: str, limits: Limits, policy, errores, avisos, recuento):
    recuento["caracteres"] = len(h)
    if limits.highlights_attr is None:
        avisos.append(
            "El esquema SP-API de este tipo de producto no expone Item Highlights; "
            "comprueba en el editor de Seller Central que el campo existe antes de pegarlo."
        )
    if not h.strip():
        errores.append("Item Highlights vacío.")
        return
    lim = limits.item_highlights
    if lim.max_chars and len(h) > lim.max_chars:
        errores.append(f"Item Highlights de {len(h)} caracteres; máximo {lim.max_chars}.")
    ht, tt = set(tokens(h)), set(tokens(titulo))
    if ht and len(ht & tt) / len(ht) > 0.5:
        avisos.append("Item Highlights repite más de la mitad de las palabras del título.")
    _common_checks(h, policy, "Item Highlights", errores, avisos)


def _check_bullets(bullets, limits: Limits, policy, errores, avisos, recuento):
    if not isinstance(bullets, list) or not all(isinstance(b, str) for b in bullets):
        errores.append("bullets debe ser una lista de textos.")
        return
    recuento["num_bullets"] = len(bullets)
    recuento["caracteres_por_bullet"] = [len(b) for b in bullets]
    recuento["bytes_totales"] = sum(utf8_len(b) for b in bullets)
    if len(bullets) != limits.bullets_num:
        errores.append(f"Hay {len(bullets)} bullets; deben ser {limits.bullets_num}.")
    lim = limits.bullet
    for i, b in enumerate(bullets, 1):
        if not b.strip():
            errores.append(f"Bullet {i} vacío.")
        if lim.max_chars and len(b) > lim.max_chars:
            errores.append(f"Bullet {i} de {len(b)} caracteres; máximo {lim.max_chars}.")
        _common_checks(b, policy, f"Bullet {i}", errores, avisos)
    if recuento["bytes_totales"] > 1000:
        avisos.append(
            f"Los bullets suman {recuento['bytes_totales']} bytes; según una fuente solo se "
            "indexan los primeros 1.000. Pon lo importante al principio."
        )
    if policy.marca_propia and bullets and all(norm(b).startswith(norm(policy.marca_propia)) for b in bullets):
        avisos.append("Todos los bullets empiezan con la marca; evítalo.")


def _check_description(d: str, limits: Limits, policy, errores, avisos, recuento):
    recuento["caracteres"] = len(d)
    lim = limits.descripcion
    if lim.max_chars and len(d) > lim.max_chars:
        errores.append(f"Descripción de {len(d)} caracteres; máximo {lim.max_chars}.")
    if re.search(r"<[a-zA-Z/][^>]*>", d):
        errores.append("La descripción debe ser texto plano (sin HTML).")
    _common_checks(d, policy, "Descripción", errores, avisos)


def normalize_backend(raw: str, visible_text: str, policy: ContentPolicy) -> tuple[str, list[str]]:
    """Limpia el backend sin cambiar su intención. Devuelve (texto, avisos)."""
    avisos = []
    text = raw.lower()
    if re.search(r"[^\w\s]", text, re.UNICODE):
        avisos.append("Se han quitado comas/puntuación del backend (solo se separa con espacios).")
        text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    visibles = set(tokens(visible_text, drop_stopwords=False))
    marca = set(tokens(policy.marca_propia, drop_stopwords=False))
    out, vistos = [], set()
    quitadas = {"vacias": [], "repetidas": [], "visibles": [], "marca": []}
    for w in text.split():
        k = strip_accents(w)
        if k in STOPWORDS_ES:
            quitadas["vacias"].append(w)
        elif k in vistos:
            quitadas["repetidas"].append(w)
        elif k in marca:
            quitadas["marca"].append(w)
        elif k in visibles:
            quitadas["visibles"].append(w)
        else:
            vistos.add(k)
            out.append(w)
    etiquetas = {
        "vacias": "palabras vacías",
        "repetidas": "repetidas",
        "visibles": "ya están en título/highlights/bullets",
        "marca": "tu propia marca (ya se indexa sola)",
    }
    for k, ws in quitadas.items():
        if ws:
            avisos.append(f"Backend: quitadas por {etiquetas[k]}: {' '.join(ws)}")
    return " ".join(out), avisos


def _check_backend(b: str, visible_text: str, limits: Limits, policy, errores, avisos, recuento):
    clean, notes = normalize_backend(b, visible_text, policy)
    avisos.extend(notes)
    n = utf8_len(clean)
    lim = limits.backend
    tope = (lim.max_bytes or 249) - policy.margen_bytes_backend
    recuento.update({"bytes": n, "tope_bytes_con_margen": tope, "limite_bytes": lim.max_bytes})
    if not clean:
        errores.append("El backend queda vacío tras limpiarlo.")
    if n > tope:
        errores.append(
            f"Backend de {n} bytes; máximo {tope} (límite {lim.max_bytes} menos "
            f"{policy.margen_bytes_backend} de margen). Pasarse puede invalidar TODO el campo."
        )
    _common_checks(clean, policy, "Backend", errores, avisos, allow_device_brands=False)
    return clean


def correction_justified(campo: str, state: ListingState, limits: Limits) -> str | None:
    """¿Hay un error real en ese campo que justifique saltarse la cadencia ("salvo error")?"""
    if campo == "titulo" and limits.titulo.max_chars and len(state.titulo) > limits.titulo.max_chars:
        return f"el título actual tiene {len(state.titulo)} caracteres (máximo {limits.titulo.max_chars})"
    if campo == "backend" and limits.backend.max_bytes and utf8_len(state.backend) > limits.backend.max_bytes:
        return f"el backend actual tiene {utf8_len(state.backend)} bytes (máximo {limits.backend.max_bytes})"
    attr_names = {"titulo": "item_name", "bullets": "bullet_point", "descripcion": "product_description",
                  "backend": "generic_keyword", "item_highlights": limits.highlights_attr or "-"}
    for issue in state.issues_graves:
        if attr_names[campo] in (issue.get("attributeNames") or []):
            return f"Amazon marca un error en este campo: {issue.get('message', '')[:120]}"
    return None


def validate_proposal(proposal: dict, state: ListingState, limits: Limits,
                      policy: ContentPolicy) -> ValidationResult:
    campo = proposal.get("campo")
    errores: list[str] = []
    avisos: list[str] = []
    recuento: dict = {}

    if campo not in CAMPOS:
        return ValidationResult(False, str(campo), None, [f"Campo '{campo}' no reconocido; usa uno de {CAMPOS}."])
    if proposal.get("asin") != state.asin:
        errores.append(f"La propuesta es para {proposal.get('asin')} pero el listing leído es {state.asin}.")
    for k in ("motivo", "riesgo", "metrica_a_vigilar"):
        if not str(proposal.get(k, "")).strip():
            errores.append(f"Falta '{k}' en la propuesta (antes/después, motivo, riesgo, métrica).")

    valor = proposal.get("valor_nuevo")
    if campo == "bullets":
        if isinstance(valor, list):
            valor = [" ".join(str(b).split()) for b in valor]
    elif not isinstance(valor, str):
        return ValidationResult(False, campo, None, errores + ["valor_nuevo debe ser un texto."])
    else:
        valor = " ".join(valor.split())

    if campo == "titulo":
        _check_title(valor, limits, policy, errores, avisos, recuento)
    elif campo == "item_highlights":
        _check_highlights(valor, state.titulo, limits, policy, errores, avisos, recuento)
    elif campo == "bullets":
        _check_bullets(valor, limits, policy, errores, avisos, recuento)
    elif campo == "descripcion":
        _check_description(valor, limits, policy, errores, avisos, recuento)
    elif campo == "backend":
        visible = " ".join([state.titulo, state.item_highlights or "", *state.bullets])
        valor = _check_backend(valor, visible, limits, policy, errores, avisos, recuento)

    actual = getattr(state, campo)
    if valor == actual:
        errores.append("La propuesta es idéntica a lo que ya está publicado.")

    if proposal.get("es_correccion"):
        motivo = correction_justified(campo, state, limits)
        if motivo is None and not proposal.get("revierte_a"):
            errores.append(
                "La propuesta dice ser una corrección de error, pero no hay ningún error "
                "detectable en ese campo; no puede saltarse la cadencia de cambios."
            )
        elif motivo:
            avisos.append(f"Corrección justificada: {motivo}.")

    return ValidationResult(not errores, campo, valor, errores, avisos, recuento)
