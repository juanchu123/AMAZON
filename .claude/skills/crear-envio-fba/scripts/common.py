"""Utilidades compartidas por los scripts de creación de envíos FBA."""

import json
import sys
from pathlib import Path

# Catálogo de FreshFinder (fuente: guía del agente de logística).
CATALOGO = {
    "5E-I8NY-S191": {"asin": "B0DHYBY6MS", "producto": "Soporte móvil coche rejilla 360° con clip"},
    "O8-5W7J-DSK1": {"asin": "B0DCZS1NR6", "producto": "Soporte móvil coche con pinza"},
    "O4-JMKY-X1L2": {"asin": "B0DSV986XY", "producto": "Soporte móvil coche con ventosa 360°"},
    "9E-ZZM5-X8ZE": {"asin": "B0F746MFPQ", "producto": "Soporte móvil coche 3 en 1"},
    "NN-8FIP-9ZZT": {"asin": "B0CPHXXHRQ", "producto": "Peluche Pou (Meokro)"},
}

# Límites de caja para envíos de paquetes pequeños (SPD) en Amazon EU.
# Revisar la guía vigente de Seller Central si Amazon los cambia.
PESO_MAX_KG = 23.0          # por encima, Amazon no acepta la caja
PESO_HEAVY_KG = 15.0        # por encima, la caja necesita etiqueta "Heavy package"
LADO_MAX_CM = 63.5          # ningún lado de la caja puede superar esto

OWNERS = {"amazon": "Amazon", "seller": "Seller"}


class Errores:
    """Acumula errores y avisos para mostrarlos todos de una vez."""

    def __init__(self):
        self.errores = []
        self.avisos = []

    def error(self, msg):
        self.errores.append(msg)

    def aviso(self, msg):
        self.avisos.append(msg)

    def informar_y_salir_si_hay_errores(self):
        for a in self.avisos:
            print(f"AVISO: {a}")
        for e in self.errores:
            print(f"ERROR: {e}", file=sys.stderr)
        if self.errores:
            print(f"\n{len(self.errores)} error(es): no se ha generado el archivo.", file=sys.stderr)
            sys.exit(1)


def cargar_spec(ruta):
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def validar_sku(sku, err):
    if sku not in CATALOGO:
        err.error(f"SKU desconocido '{sku}': no está en el catálogo. Revisa que esté bien escrito.")


def validar_caja(nombre, peso, largo, ancho, alto, err):
    """Valida peso y medidas de una caja. Todos obligatorios y > 0."""
    campos = {"peso (kg)": peso, "largo (cm)": largo, "ancho (cm)": ancho, "alto (cm)": alto}
    for campo, valor in campos.items():
        if valor is None:
            err.error(f"{nombre}: falta {campo}.")
        elif not isinstance(valor, (int, float)) or valor <= 0:
            err.error(f"{nombre}: {campo} debe ser un número positivo (es {valor!r}).")
    if isinstance(peso, (int, float)):
        if peso > PESO_MAX_KG:
            err.error(f"{nombre}: pesa {peso} kg, más del máximo de {PESO_MAX_KG} kg. Reparte en más cajas.")
        elif peso > PESO_HEAVY_KG:
            err.aviso(f"{nombre}: pesa {peso} kg (> {PESO_HEAVY_KG} kg). Necesita etiqueta 'Heavy package'.")
    for campo, valor in (("largo", largo), ("ancho", ancho), ("alto", alto)):
        if isinstance(valor, (int, float)) and valor > LADO_MAX_CM:
            err.error(f"{nombre}: {campo} de {valor} cm supera el máximo de {LADO_MAX_CM} cm.")


def normalizar_owner(valor, campo, err):
    if valor is None:
        return None
    v = OWNERS.get(str(valor).strip().lower())
    if v is None:
        err.error(f"{campo} debe ser 'Amazon' o 'Seller' (es {valor!r}).")
    return v
