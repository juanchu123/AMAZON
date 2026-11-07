"""
validacion.py — lo que Amazon acepta en una hoja masiva o en la API, comprobado ANTES de escribir.

Una fila mal escrita hace que Amazon rechace la subida (Amazon Ads Academy, errores frecuentes de
las hojas masivas):
  1021  palabra clave no válida: más de 80 caracteres, o con / % \\ ^ , o dos puntos seguidos.
  1018  tipo de coincidencia mal escrito (valen Amplia, Frase, Exacta, Frase negativa, Exacta negativa;
        sin la palabra "coincidencia").
  1025  estrategia de pujas no válida (solo las tres de modelo.py, tal como vienen en la descarga).
Además, Amazon no deja más de 10 palabras en una palabra clave.

Juan (30/09/2026): sin erratas a propósito como keywords; la investigación no las propone.
"""

import re

from modelo import ALZA_BAJA, PUJA_FIJA, SOLO_BAJA

MAX_CARACTERES = 80
MAX_PALABRAS = 10
PROHIBIDOS = set("/%\\^,")
COINCIDENCIAS = ("Amplia", "Frase", "Exacta")
COINCIDENCIAS_NEGATIVAS = ("Frase negativa", "Exacta negativa")
ESTRATEGIAS = (SOLO_BAJA, ALZA_BAJA, PUJA_FIJA)


def keyword(texto):
    """(válida, motivo). motivo vacío si es válida."""
    t = str(texto or "").strip()
    if not t:
        return False, "palabra clave vacía"
    if len(t) > MAX_CARACTERES:
        return False, f"más de {MAX_CARACTERES} caracteres ({len(t)})"
    malos = sorted(PROHIBIDOS & set(t))
    if malos:
        return False, "lleva caracteres que Amazon no acepta: " + " ".join(malos)
    if ".." in t or ":" in t:
        return False, "lleva dos puntos seguidos o ':'"
    if len(t.split()) > MAX_PALABRAS:
        return False, f"más de {MAX_PALABRAS} palabras"
    return True, ""


def coincidencia(valor, negativa=False):
    return valor in (COINCIDENCIAS_NEGATIVAS if negativa else COINCIDENCIAS)


def estrategia(valor):
    return valor in ESTRATEGIAS


def asin(valor):
    return bool(re.fullmatch(r"B0[A-Z0-9]{8}", str(valor or "").strip().upper()))
