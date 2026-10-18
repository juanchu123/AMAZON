"""
directivas.py — lo que Juan le ha dicho al Agente ADS (agente_ads/directivas.json), aplicado a las reglas.

  tope_mensual_eur     techo del mes (840 € salvo que Juan diga otra cosa por correo y lo confirme)
  modo                 "normal" | "crecer" (gasta sin miedo: el doble de pruebas por ronda) |
                       "recortar" (ninguna prueba nueva; el tope ya lo baja tope_mensual_eur)
  campanas_terminadas  ids de campañas que siguen "activadas" pero ya no sirven (fecha de fin pasada):
                       SellerMate no da la fecha de fin, así que se apuntan aquí
  no_reactivar         ids de campañas que Juan ha pausado a propósito
  palabras_ajenas_extra  {asin: [palabras]}: más vocabulario de cosas que el producto no es
  margen_unitario_eur  {asin: €}: lo que Juan gana por unidad antes de publicidad (si no rellena la hoja Economía)
  reactivar            {id campaña: €/día}: campañas que Juan ha pedido reactivar (van en bulk_cambios, sin propuesta)
  limites              [{"asin", "max_gasto_sin_ganancia_eur", "desde", "accion"}]: si el producto gasta más que
                       eso en anuncios desde esa fecha sin ganar dinero (margen de las ventas ≤ gasto), aviso para
                       que el agente lo reestructure
  vetos                [{"tipo", "texto" o "clave", "hasta" (AAAA-MM-DD), "motivo"}]: cambios que el Agente
                       ADS (o Juan) no quiere aunque las reglas los propongan; "tipo" "*" vale para todos
  visibilidad          {"desde", "hasta", "tope_perdida_semana_eur", "pujas": {id elemento: €}, "motivo"}: plan
                       que Juan elige para comprar alcance por encima del equilibrio (plan B, 18/10/2026). Mientras
                       la pérdida de la semana (lunes a hoy) de esos elementos (gasto − ventas × margen) no llegue
                       al tope, sus pujas se fijan a esas cifras y el motor no las baja; al llegar, el plan se para
                       hasta el lunes y vuelven las reglas normales (que las bajan al equilibrio)
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
    config.MARGEN_UNITARIO = {str(k): float(v) for k, v in (d.get("margen_unitario_eur") or {}).items()}
    config.REACTIVAR_ORDEN = {str(k): float(v) for k, v in (d.get("reactivar") or {}).items()}
    config.LIMITES = list(d.get("limites") or [])
    config.VISIBILIDAD = dict(d.get("visibilidad") or {})
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


def comprobar_limites(cuenta, series, hoy):
    """Avisos (tipo, clave, mensaje) de los productos que han pasado su límite de gasto sin ganancia."""
    from datetime import date as _d
    out = []
    for lim in config.LIMITES:
        asin, maximo = str(lim.get("asin")), float(lim.get("max_gasto_sin_ganancia_eur") or 0)
        desde = _d.fromisoformat(str(lim.get("desde"))[:10]) if lim.get("desde") else None
        if not maximo or not desde:
            continue
        claves = [e.clave for e in cuenta.elementos.values() if cuenta.producto_de_grupo(e.id_grupo) == asin]
        gasto = compras = 0.0
        from datetime import timedelta
        for k in claves:
            m = series.acumulado(k, hoy) - series.acumulado(k, desde - timedelta(days=1))
            gasto, compras = gasto + m.coste, compras + m.compras
        ganancia = compras * config.MARGEN_UNITARIO.get(asin, 0.0) - gasto
        estado = f"{gasto:.2f} € gastados desde el {desde:%d/%m}, {compras:.0f} ventas, ganancia {ganancia:+.2f} €"
        if gasto > maximo and ganancia <= 0:
            out.append(("limite", asin, f"LÍMITE DE JUAN SUPERADO ({asin}): {estado} (límite {maximo:.0f} € sin ganar "
                        f"nada). {lim.get('accion') or 'Reestructurar'}"))
        else:
            out.append(("limite_estado", asin, f"Límite de Juan ({asin}): {estado}; límite {maximo:.0f} € sin ganancia"))
    return out


def visibilidad(cuenta, series, hoy):
    """Plan de visibilidad de Juan: ({id elemento: puja} vigentes hoy, aviso (tipo, clave, mensaje) o None)."""
    from datetime import date as _d, timedelta
    v = config.VISIBILIDAD
    pujas = {str(k): float(x) for k, x in (v.get("pujas") or {}).items()}
    if not pujas:
        return {}, None
    desde = _d.fromisoformat(str(v.get("desde"))[:10]) if v.get("desde") else hoy
    hasta = _d.fromisoformat(str(v.get("hasta"))[:10]) if v.get("hasta") else None
    if hoy < desde:
        return {}, None
    if hasta and hoy > hasta:
        return {}, ("visibilidad", "plan", f"Plan de visibilidad terminado el {hasta:%d/%m}: vuelven las pujas de equilibrio")
    tope = float(v.get("tope_perdida_semana_eur") or 0)
    inicio = max(desde, hoy - timedelta(days=hoy.weekday()))     # lunes de esta semana (o el día que empezó)
    gasto = margen = 0.0
    for k in pujas:
        el = cuenta.elementos.get(k)
        asin = cuenta.producto_de_grupo(el.id_grupo) if el else None
        m = series.acumulado(k, hoy) - series.acumulado(k, inicio - timedelta(days=1))
        gasto += m.coste
        margen += m.compras * config.MARGEN_UNITARIO.get(asin, 0.0)
    perdida = gasto - margen
    estado = (f"desde el {inicio:%d/%m}: {gasto:.2f} € gastados, {margen:.2f} € de margen de las ventas, "
              f"pérdida {perdida:.2f} € (tope {tope:.0f} €/semana)")
    if tope and perdida >= tope:
        return {}, ("visibilidad", "plan", f"PLAN DE VISIBILIDAD PARADO hasta el lunes: {estado}. Vuelven las pujas de equilibrio")
    return pujas, ("visibilidad_estado", "plan", f"Plan de visibilidad activo, {estado}")


def cambios_visibilidad(cuenta, pujas):
    """Cambios de puja para llevar cada elemento del plan a su puja fijada."""
    from modelo import ACTIVO, PUJA, Cambio
    motivo = config.VISIBILIDAD.get("motivo") or "Plan de visibilidad de Juan"
    out = []
    for k, puja in sorted(pujas.items()):
        el = cuenta.elementos.get(k)
        if el is None or el.estado != ACTIVO or el.puja is None or abs(el.puja - puja) < 0.01:
            continue
        camp = cuenta.campanas.get(el.id_campana)
        out.append(Cambio(tipo=PUJA, clave=el.clave, producto=cuenta.producto_de_grupo(el.id_grupo),
                          id_campana=el.id_campana, id_grupo=el.id_grupo, campana=camp.nombre if camp else "",
                          texto=el.texto, coincidencia=el.coincidencia, antes=el.puja, despues=puja,
                          motivo=f"{motivo}: puja fijada a {puja:.2f} € (por encima del equilibrio, con tope de pérdida "
                                 f"semanal {float(config.VISIBILIDAD.get('tope_perdida_semana_eur') or 0):.0f} €)",
                          extra={"visibilidad": True}))
    return out
