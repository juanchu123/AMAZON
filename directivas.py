"""
directivas.py — lo que Juan le ha dicho al Agente ADS (agente_ads/directivas.json), aplicado a las reglas.

  tope_mensual_eur     techo del mes (840 € salvo que Juan diga otra cosa por correo y lo confirme)
  modo                 "normal" | "crecer" (gasta sin miedo: el doble de pruebas por ronda) |
                       "recortar" (ninguna prueba nueva; el tope ya lo baja tope_mensual_eur)
  campanas_terminadas  ids de campañas que siguen "activadas" pero ya no sirven (fecha de fin pasada):
                       SellerMate no da la fecha de fin, así que se apuntan aquí
  no_reactivar         ids de campañas que Juan ha pausado a propósito
  palabras_ajenas_extra  {asin: [palabras]}: más vocabulario de cosas que el producto no es
  vetos                [{"tipo", "texto" o "clave", "hasta" (AAAA-MM-DD), "motivo"}]: cambios que el Agente
                       ADS (o Juan) no quiere aunque las reglas los propongan; "tipo" "*" vale para todos
El agente edita este archivo cuando Juan le escribe (y lo apunta en "notas"); Python solo lo lee.
"""

import json
from pathlib import Path

import config

RUTA = config.RAIZ / "agente_ads" / "directivas.json"
MODOS = ("normal", "crecer", "recortar")


def cargar(ruta=None):
    ruta = Path(ruta or RUTA)
    if not ruta.exists():
        return {}
    return json.loads(ruta.read_text(encoding="utf-8"))


def aplicar(d):
    """Pone en config lo que dicen las directivas. Devuelve un texto para el Resumen."""
    if not d:
        return "sin directivas (agente_ads/directivas.json)"
    tope = float(d.get("tope_mensual_eur") or config.TOPE_MENSUAL_EUR)
    if tope <= 0:
        raise SystemExit("directivas.json: tope_mensual_eur tiene que ser > 0")
    config.TOPE_MENSUAL_EUR = tope
    modo = d.get("modo") or "normal"
    if modo not in MODOS:
        raise SystemExit(f"directivas.json: modo '{modo}' no válido ({', '.join(MODOS)})")
    if modo == "crecer":
        config.MAX_PRUEBAS_NUEVAS_POR_RONDA *= 2
    elif modo == "recortar":
        config.MAX_PRUEBAS_NUEVAS_POR_RONDA = 0
    config.NO_REACTIVAR = {str(x) for x in d.get("no_reactivar") or []}
    import keyword_ml as kml
    for asin, palabras in (d.get("palabras_ajenas_extra") or {}).items():
        config.PALABRAS_AJENAS[asin] = set(config.PALABRAS_AJENAS.get(asin, set())) | {kml.normalizar(w) for w in palabras}
    config.VETOS = list(d.get("vetos") or [])
    return f"tope {tope:.0f} €/mes, modo {modo}, {len(config.NO_REACTIVAR)} campañas que no se reactivan"


def vetado(cambio, hoy):
    """Motivo si un veto vigente cubre este cambio, o None."""
    import keyword_ml as kml
    for v in config.VETOS:
        if v.get("hasta") and str(v["hasta"]) < hoy.isoformat():
            continue
        if v.get("tipo") not in (None, "*", cambio.tipo):
            continue
        if v.get("clave") and str(v["clave"]) != str(cambio.clave):
            continue
        if v.get("texto") and kml.normalizar(str(v["texto"])) != kml.normalizar(str(cambio.texto)):
            continue
        if v.get("campana") and str(v["campana"]).lower() not in str(cambio.campana).lower():
            continue
        return f"vetado: {v.get('motivo') or 'sin motivo'}"
    return None
