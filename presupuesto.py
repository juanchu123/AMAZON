"""
presupuesto.py — reparto del presupuesto diario entre campañas (AGENTE_AUTONOMO.md §2.5 y §3).

  Tope del día   = lo que permite llegar a fin de mes sin pasar de 840 € (safety.py).
  20 % del tope  -> fondo de EXPERIMENTACIÓN (global): campañas de pruebas, productos sin
                    historial probado y campañas abiertas por el agente. A partes iguales.
  80 % del tope  -> campañas PROBADAS, según su puntuación:
                      puntuación = clamp(35 % / ACOS de los últimos 30 días, 0,25 … 3)
                                   × (0,5 + confianza aprendida al subirle el presupuesto)
Reasignación libre (sin tope por movimiento). Mínimo 1 €/día por campaña (lo exige Amazon);
nunca se pausa una campaña por presupuesto. Una campaña experimental que ya vende (≥ 3 compras
maduras con ACOS ≤ 35 %) se "gradúa" y pasa al 80 %.
Solo se cambia un presupuesto si la diferencia es de verdad (≥ 0,50 € y ≥ 10 %), y una subida
no se repite hasta pasados 3 días de la anterior.
"""

from datetime import timedelta

import config
import learner
import safety
from documento import fecha
from modelo import ACTIVO, CREAR_CAMPANA, PRESUPUESTO, Cambio

PROBADO, EXPERIMENTACION = "probado", "experimentación"


def _ventana(series, id_campana, desde, hasta):
    return learner.acumulado_campana(series, id_campana, hasta) - learner.acumulado_campana(series, id_campana, desde)


def metricas_30d(series, id_campana, hoy):
    fin = hoy - timedelta(days=config.DIAS_MADUREZ + 1)
    return _ventana(series, id_campana, fin - timedelta(days=config.VENTANA_PUNTUACION_DIAS), fin)


def creadas_por_agente(doc):
    return {str((t.get("ID campaña") or "")) for t in doc.tickets(tipos=(CREAR_CAMPANA,))}


def fondo(campana, cuenta, doc, series, catalogo, hoy):
    """(fondo, motivo)."""
    asin = cuenta.producto_de_campana(campana.id)
    m = learner.acumulado_campana(series, campana.id, hoy - timedelta(days=config.DIAS_MADUREZ + 1))
    if m.compras >= config.GRADUACION_MIN_COMPRAS and m.acos is not None and m.acos <= config.GRADUACION_ACOS_MAX:
        return PROBADO, f"graduada: {m.compras:.0f} compras maduras con ACOS {m.acos:.0%}"
    if "prueba" in campana.nombre.lower():
        return EXPERIMENTACION, "campaña de pruebas"
    if campana.id in creadas_por_agente(doc):
        return EXPERIMENTACION, "abierta por el agente, aún sin graduar"
    compras = catalogo.producto(asin).compras if asin else 0
    if compras >= config.PROBADO_MIN_COMPRAS_HISTORICO:
        return PROBADO, f"producto con {compras:.0f} compras en el histórico"
    return EXPERIMENTACION, f"producto con solo {compras:.0f} compras en el histórico"


def puntuacion(campana, cuenta, doc, series, catalogo, hoy):
    m = metricas_30d(series, campana.id, hoy)
    if m.ventas > 0:
        acos, origen = m.acos, "últimos 30 días"
    elif m.coste > 0:
        acos, origen = float("inf"), "últimos 30 días (sin ventas)"
    else:
        asin = cuenta.producto_de_campana(campana.id)
        p = catalogo.producto(asin) if asin else None
        acos = p.coste / p.ventas if p and p.ventas else None
        origen = "histórico del producto"
    base = 1.0 if acos is None else min(3.0, max(0.25, config.ACOS_OBJETIVO_MAX / acos)) if acos > 0 else 3.0
    conf = learner.confianza_campana(doc, campana.id)
    return base * (0.5 + conf), acos, conf, origen


def _repartir(total, pesos):
    """Reparte 'total' según pesos con un mínimo de 1 € por campaña."""
    minimo = config.PRESUPUESTO_MINIMO_AMAZON
    res, libres = {}, dict(pesos)
    while libres:
        resto = total - sum(res.values())
        suma = sum(libres.values()) or 1.0
        bajos = {k for k, w in libres.items() if resto * w / suma < minimo}
        if not bajos:
            for k, w in libres.items():
                res[k] = resto * w / suma
            break
        for k in bajos:
            res[k] = minimo
            del libres[k]
    return {k: int(v * 100) / 100 for k, v in res.items()}   # redondeo hacia abajo: nunca pasar del tope


def _estrategia(c):
    ajustes = ", ".join(f"{e} +{v:.0f} %" for e, v in sorted((c.ajustes_emplazamiento or {}).items()) if v)
    return {"Estrategia de pujas": c.estrategia_pujas or "desconocida", "Estrategia elegida": c.estrategia_objetivo,
            "Motivo de la estrategia": c.motivo_estrategia, "Ajustes de emplazamiento": ajustes or "0 %"}


def planificar(cuenta, doc, series, catalogo, hoy, gasto_mes, nuevas=()):
    """nuevas: campañas que se van a crear en esta ronda [{"nombre"}], financiadas por el 20 %.
    Devuelve (cambios, filas para la hoja Campañas, presupuesto por campaña nueva)."""
    total = safety.presupuesto_diario_total(hoy, gasto_mes)
    activas = [c for c in cuenta.campanas.values() if c.estado == ACTIVO]
    info = {c.id: fondo(c, cuenta, doc, series, catalogo, hoy) for c in activas}
    probadas = [c for c in activas if info[c.id][0] == PROBADO]
    experimentales = [c for c in activas if info[c.id][0] == EXPERIMENTACION]

    puntos = {c.id: puntuacion(c, cuenta, doc, series, catalogo, hoy) for c in activas}
    plan = _repartir(total * (1 - config.PCT_EXPERIMENTACION), {c.id: puntos[c.id][0] for c in probadas}) if probadas else {}
    pesos_exp = {c.id: 1.0 for c in experimentales} | {f"nueva:{i}": 1.0 for i in range(len(nuevas))}
    plan |= _repartir(total * config.PCT_EXPERIMENTACION, pesos_exp) if pesos_exp else {}

    cambios, filas = [], []
    for c in activas:
        nuevo = plan[c.id]
        dif = nuevo - c.presupuesto
        nota = ""
        if abs(dif) >= max(config.CAMBIO_MINIMO_PRESUPUESTO_EUR, config.CAMBIO_MINIMO_PRESUPUESTO_PCT * c.presupuesto):
            ult = doc.tickets(clave=f"camp:{c.id}", tipos=(PRESUPUESTO,))
            ult_subida = next((t for t in reversed(ult) if (t["Después"] or 0) > (t["Antes"] or 0)), None)
            if dif > 0 and ult_subida and (hoy - fecha(ult_subida["Fecha"])).days < config.DIAS_ENTRE_SUBIDAS_PRESUPUESTO:
                nota = "subida aplazada: hubo otra hace menos de 3 días"
            else:
                fin = hoy - timedelta(days=config.DIAS_MADUREZ + 1)
                antes = _ventana(series, c.id, fin - timedelta(days=14), fin)
                pts, acos, conf, origen = puntos[c.id]
                acos_txt = "sin datos" if acos is None else ("sin ventas" if acos == float("inf") else f"{acos:.0%}")
                cambios.append(Cambio(
                    tipo=PRESUPUESTO, clave=f"camp:{c.id}", producto=cuenta.producto_de_campana(c.id), id_campana=c.id,
                    id_grupo=None, campana=c.nombre, texto="(presupuesto diario)", coincidencia="", antes=c.presupuesto,
                    despues=nuevo, base=learner.acumulado_campana(series, c.id, hoy),
                    motivo=(f"Fondo {info[c.id][0]} ({info[c.id][1]}). Tope del día {total:.2f} € "
                            f"(840 €/mes). ACOS {acos_txt} ({origen}), confianza {conf:.2f}, puntuación {pts:.2f}"),
                    extra={"fondo": info[c.id][0], "ventas_dia_antes": round(antes.ventas / 14, 2)}))
        pts, acos, conf, origen = puntos[c.id]
        filas.append({"ID campaña": c.id, "Campaña": c.nombre, "Estado": c.estado,
                      "Producto (ASIN)": cuenta.producto_de_campana(c.id), "Fondo": info[c.id][0],
                      "Presupuesto diario (€)": c.presupuesto, "Presupuesto objetivo (€)": nuevo,
                      "ACOS 30 días": None if acos in (None, float("inf")) else round(acos, 3),
                      "Puntuación": round(pts, 2), "Confianza (aprendizaje)": round(conf, 2),
                      **_estrategia(c),
                      "Creada por el agente": "Sí" if c.id in creadas_por_agente(doc) else "",
                      "Actualizado": hoy.isoformat() + (f" ({nota})" if nota else "")})
    for c in cuenta.campanas.values():
        if c.estado != ACTIVO:
            filas.append({"ID campaña": c.id, "Campaña": c.nombre, "Estado": c.estado,
                          "Producto (ASIN)": cuenta.producto_de_campana(c.id), "Fondo": "",
                          "Presupuesto diario (€)": c.presupuesto, "Presupuesto objetivo (€)": None, **_estrategia(c),
                          "Actualizado": hoy.isoformat() + f" ({c.estado}: no se le asigna presupuesto)"})
    por_nueva = [plan[f"nueva:{i}"] for i in range(len(nuevas))]
    return cambios, filas, por_nueva, total


def hueco_experimental(cuenta, doc, series, catalogo, hoy, gasto_mes):
    """Lo que le tocaría a una campaña experimental más si se abriera ahora (coste de oportunidad, §2.6)."""
    total = safety.presupuesto_diario_total(hoy, gasto_mes)
    n = sum(1 for c in cuenta.campanas.values() if c.estado == ACTIVO
            and fondo(c, cuenta, doc, series, catalogo, hoy)[0] == EXPERIMENTACION)
    return total * config.PCT_EXPERIMENTACION / (n + 1)
