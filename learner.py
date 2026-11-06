"""
learner.py — aprendizaje a dos niveles (AGENTE_AUTONOMO.md §3), leyendo la hoja Tickets.

1. Evaluar tickets pendientes: pasado el tiempo de madurez, se mira qué pasó DESPUÉS de cada
   cambio (solo con clics de más de 7 días, cuando la atribución de Amazon ya está completa) y
   se escribe el veredicto en el ticket: "mejora" / "empeora" (o "sin datos" si no llegó a
   tener suficientes clics antes del siguiente cambio: no cuenta ni a favor ni en contra).

2. Nivel keyword (producto + keyword + coincidencia, nunca por campaña):
      success_rate  = subidas de puja que mejoraron / subidas evaluadas
      agresividad   = 0,2 + 0,8 × success_rate      (sin historial: 0,5 neutro)
   La agresividad decide dónde cae la puja dentro del ACOS objetivo 30-35 %.

3. Nivel campaña: lo mismo con las subidas de presupuesto (¿trajeron más ventas al día
   manteniendo el ACOS en objetivo?). Da la "confianza" de la campaña para repartir el presupuesto.

Una decisión todavía sin evaluar no cuenta ni como acierto ni como fallo.
"""

import json
from datetime import timedelta

import config
import keyword_ml as kml
from documento import fecha, num
from modelo import NUEVA_KEYWORD, PAUSAR, PRESUPUESTO, PUJA, REACTIVAR, Metricas

EVALUABLES = (PUJA, NUEVA_KEYWORD, "añadir_asin", REACTIVAR, PRESUPUESTO)


def _clave_aprendizaje(producto, texto, coincidencia):
    return (str(producto or ""), kml.firma(str(texto or "")), str(coincidencia or ""))


def _base(t):
    return Metricas(num(t.get("Base: clics")), num(t.get("Base: coste")), num(t.get("Base: compras")),
                    num(t.get("Base: ventas")))


def _extra(t):
    try:
        return json.loads(t.get("Datos extra") or "{}")
    except (TypeError, ValueError):
        return {}


def _acum_campana(series, id_campana, hasta):
    m = Metricas()
    for k in series.claves_de_campana(id_campana):
        m = m + series.acumulado(k, hasta)
    return m


def _fin_ventana(series, clave, hoy):
    return hoy - timedelta(days=config.DIAS_MADUREZ + (1 if series.tiene_diario(clave) else 0))


def evaluar_pendientes(doc, series, hoy):
    """Escribe el veredicto en los tickets que ya se pueden evaluar. Devuelve cuántos."""
    n = 0
    tickets = doc.tickets(estados=("confirmado", "enviado_bulk"))
    for t in tickets:
        if t["Tipo"] not in EVALUABLES or t.get("Veredicto"):
            continue
        f0 = fecha(t["Fecha"])
        siguiente = next((fecha(o["Fecha"]) for o in tickets
                          if o["Clave"] == t["Clave"] and o["Tipo"] in (PUJA, PAUSAR, REACTIVAR, PRESUPUESTO)
                          and fecha(o["Fecha"]) > f0), None)
        if t["Tipo"] == PRESUPUESTO:
            res = _evaluar_presupuesto(t, series, hoy, f0, siguiente)
        else:
            res = _evaluar_elemento(t, series, hoy, f0, siguiente)
        if res is None:
            continue
        veredicto, despues = res
        t.update({"Veredicto": veredicto, "Fecha veredicto": hoy.isoformat(),
                  "Después: clics": despues.clics, "Después: coste": round(despues.coste, 2),
                  "Después: compras": despues.compras, "Después: ventas": round(despues.ventas, 2),
                  "ACOS después": round(despues.acos, 3) if despues.acos not in (None, float("inf")) else None})
        n += 1
    return n


def _evaluar_elemento(t, series, hoy, f0, siguiente):
    clave = str(t["Clave"])
    fin = _fin_ventana(series, clave, hoy)
    cerrada = siguiente is not None and siguiente <= fin
    if cerrada:
        fin = siguiente - timedelta(days=1)
    if fin < f0:
        return None                                   # aún no hay ni un clic maduro tras el cambio
    base = series.base_en(clave, f0, _base(t))
    despues = series.acumulado(clave, fin) - base
    if despues.clics < config.MIN_CLICS_NUEVOS:
        return ("sin datos", despues) if cerrada else None
    acos_antes = base.acos if base.clics >= config.MIN_CLICS_NUEVOS else None
    acos_d = despues.acos
    if acos_d is None:                                 # clics pero ni coste ni ventas: no hay señal
        return ("sin datos", despues) if cerrada else None
    mejora = acos_d <= config.ACOS_OBJETIVO_MAX or (acos_antes not in (None, float("inf")) and acos_d < acos_antes)
    return ("mejora" if mejora else "empeora"), despues


def _evaluar_presupuesto(t, series, hoy, f0, siguiente):
    id_c = str(t.get("ID campaña") or "")
    claves = series.claves_de_campana(id_c)
    if not claves:
        return None
    fin = hoy - timedelta(days=config.DIAS_MADUREZ + 1)
    cerrada = siguiente is not None and siguiente <= fin
    if cerrada:
        fin = siguiente - timedelta(days=1)
    dias = (fin - f0).days + 1
    if dias < config.DIAS_ENTRE_CAMBIOS:
        return ("sin datos", Metricas()) if cerrada else None
    despues = _acum_campana(series, id_c, fin) - _acum_campana(series, id_c, f0 - timedelta(days=1))
    if despues.clics < config.MIN_CLICS_NUEVOS:
        return ("sin datos", despues) if cerrada else None
    ventas_dia_antes = num(_extra(t).get("ventas_dia_antes"))
    acos_d = despues.acos
    mejora = despues.ventas / dias > ventas_dia_antes and acos_d is not None and acos_d <= config.ACOS_OBJETIVO_MAX
    return ("mejora" if mejora else "empeora"), despues


# ---------------------------------------------------------------- nivel keyword
def agresividad(doc, producto, texto, coincidencia):
    """0,2 + 0,8 × tasa de acierto de las SUBIDAS de puja de esta keyword en este producto."""
    objetivo = _clave_aprendizaje(producto, texto, coincidencia)
    subidas = [t for t in doc.tickets(tipos=(PUJA,))
               if _clave_aprendizaje(t["Producto (ASIN)"], t["Palabra clave / segmentación"], t["Coincidencia"]) == objetivo
               and num(t["Después"]) > num(t["Antes"]) and t.get("Veredicto") in ("mejora", "empeora")]
    if not subidas:
        return 0.5
    return 0.2 + 0.8 * sum(t["Veredicto"] == "mejora" for t in subidas) / len(subidas)


def veces_pausada(doc, producto, texto, coincidencia):
    objetivo = _clave_aprendizaje(producto, texto, coincidencia)
    return sum(1 for t in doc.tickets(tipos=(PAUSAR,))
               if _clave_aprendizaje(t["Producto (ASIN)"], t["Palabra clave / segmentación"], t["Coincidencia"]) == objetivo)


# ---------------------------------------------------------------- nivel campaña
def confianza_campana(doc, id_campana):
    subidas = [t for t in doc.tickets(tipos=(PRESUPUESTO,)) if str(t["ID campaña"]) == str(id_campana)
               and num(t["Después"]) > num(t["Antes"]) and t.get("Veredicto") in ("mejora", "empeora")]
    if not subidas:
        return 0.5
    return 0.2 + 0.8 * sum(t["Veredicto"] == "mejora" for t in subidas) / len(subidas)


def acumulado_campana(series, id_campana, hasta):
    return _acum_campana(series, id_campana, hasta)
