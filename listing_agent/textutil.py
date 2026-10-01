"""
textutil.py
-----------
Utilidades de texto compartidas: normalizar para comparar (minúsculas, sin
tildes), tokenizar, contar bytes como los cuenta Amazon (UTF-8).
"""

import re
import unicodedata

# Palabras vacías en español: no aportan indexación y gastan bytes en backend.
STOPWORDS_ES = {
    "a", "al", "con", "de", "del", "el", "en", "la", "las", "lo", "los", "o",
    "para", "por", "sin", "su", "sus", "un", "una", "unos", "unas", "y", "e",
    "u", "que", "se", "es", "muy", "mas", "the", "and", "for", "with", "of",
}


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def norm(text: str) -> str:
    """Forma canónica para COMPARAR (nunca para publicar)."""
    return re.sub(r"\s+", " ", strip_accents(text or "").lower()).strip()


def tokens(text: str, drop_stopwords: bool = True) -> list[str]:
    toks = re.findall(r"[a-z0-9ñ]+", norm(text))
    if drop_stopwords:
        toks = [t for t in toks if t not in STOPWORDS_ES]
    return toks


def utf8_len(text: str) -> int:
    return len((text or "").encode("utf-8"))


def contains_phrase(text: str, phrase: str) -> bool:
    """¿Aparece `phrase` como palabra(s) completa(s) en `text`? (sin tildes, sin mayúsculas)"""
    p = norm(phrase)
    if not p:
        return False
    return re.search(r"(?<![a-z0-9ñ])" + re.escape(p) + r"(?![a-z0-9ñ])", norm(text)) is not None
