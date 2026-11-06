"""
presupuesto.py — reparto del presupuesto diario entre campañas (AGENTE_AUTONOMO.md §2.5; Juan, 30/09/2026).

El presupuesto lo gestiona el agente entero, sin fondo fijo de experimentación:

  Tope del día = lo que permite llegar a fin de mes sin pasar de 840 € (safety.py).
  Se reparte entre TODAS las campañas activas (y las que se abren o reactivan en la ronda) según su
  puntuación:
      puntuación = clamp(35 % / ACOS de los últimos 30 días, 0,25 … 3) × (0,5 + confianza aprendida)
  Sin 30 días de datos se usa el ACOS histórico del producto; sin nada, puntúa 1 (ni premio ni castigo).

Reglas de Amazon Ads Academy:
  - Las campañas buenas que agotan su presupuesto ("limitadas": gastan ≥ 90 % de media en 7 días)
    reciben más, y ese dinero sale de las flojas; nunca de las buenas a las malas (la puntuación).
  - A una campaña que gasta mucho menos de lo que tiene no le sirve más: como mucho recibe 1,5 × lo
    que gasta de media, y lo que sobra va a las demás. Si sobra de todas, se queda sin asignar
    (nunca se fuerza el gasto). Pero no se le recorta si ese dinero no le hace falta a nadie.
  - Una campaña nueva o reactivada empieza con ≤ 5 €/día (config.PRESUPUESTO_MAX_CAMPANA_NUEVA).
Mínimo 1 €/día por campaña (lo exige Amazon); nunca se pausa una campaña por presupuesto. Solo se
cambia un presupuesto si la diferencia es de verdad (≥ 0,50 € y ≥ 10 %), y una subida no se repite
hasta pasados 3 días de la anterior.
"""

from datetime import timedelta

import config
import learner
import safety
from documento import fecha
from modelo import ACTIVO, CREAR_CAMPANA, PRESUPUESTO, Cambio


def _ventana(series, id_campana, desde, hasta):
    return learner.acumulado_campana(series, id_campana, hasta) - learner.acumulado_campana(series, id_campana, desde)


def metricas_30d(series, id_campana, hoy):
    fin = hoy - timedelta(days=config.DIAS_MADUREZ + 1)
    return _ventana(series, id_campana, fin - timedelta(days=config.VENTANA_PUNTUACION_DIAS), fin)


def creadas_por_agente(doc):
    return {str((t.get("ID campaña") or "")) for t in doc.tickets(tipos=(CREAR_CAMPANA,))}


def gasto_medio(series, id_campana, hoy):
    """Gasto medio diario de los últimos 7 días, o None si no hay datos de antes (el gasto se
    conoce al momento: no hace falta esperar a la madurez)."""
    claves = series.claves_de_campana(id_campana)
    inicio = hoy - timedelta(days=config.DIAS_GASTO_MEDIO + 1)
    if not claves or not any(series.tiene_diario(k) and series.diario[k] and series.diario[k][0][0] <= inicio
                             or any(d <= inicio for d, _ in series.fotos.get(k, [])) for k in claves):
        return None
    fin = hoy - timedelta(days=1)
    return _ventana(series, id_campana, fin - timedelta(days=config.DIAS_GASTO_MEDIO), fin).coste / config.DIAS_GASTO_MEDIO


def limite_util(campana, gasto):
    """(tope útil o None, limitada). Sin datos de gasto: sin tope."""
    if gasto is None:
        return None, False
    if gasto >= config.UMBRAL_LIMITADA * campana.presupuesto:
        return None, True
    return max(config.PRESUPUESTO_MINIMO_AMAZON, round(gasto * config.HOLGURA_PRESUPUESTO, 2)), False


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
        origen = "histórico del producto" if acos is not None else "sin datos: neutra"
    base = 1.0 if acos is None else min(3.0, max(0.25, config.ACOS_OBJETIVO_MAX / acos)) if acos > 0 else 3.0
    conf = learner.confianza_campana(doc, campana.id)
    return base * (0.5 + conf), acos, conf, origen


def _repartir(total, pesos, topes=None):
    """Reparte 'total' según pesos, con un mínimo de 1 € por campaña y, si lo tiene, un tope útil;
    lo que no cabe en una campaña con tope pasa a las demás."""
    minimo, topes = config.PRESUPUESTO_MINIMO_AMAZON, topes or {}
    res, libres = {}, dict(pesos)
    while libres:
        resto = total - sum(res.values())
        suma = sum(libres.values()) or 1.0
        parte = {k: resto * w / suma for k, w in libres.items()}
        bajos = {k for k, v in parte.items() if v < minimo}
        altos = {k for k, v in parte.items() if topes.get(k) is not None and v > topes[k]}
        if bajos:
            for k in bajos:
                res[k] = minimo
                del libres[k]
        elif altos:
            for k in altos:
                res[k] = topes[k]
                del libres[k]
        else:
            res |= parte
            break
    return {k: int(v * 100) / 100 for k, v in res.items()}   # redondeo hacia abajo: nunca pasar del tope


def _estrategia(c):
    ajustes = ", ".join(f"{e} +{v:.0f} %" for e, v in sorted((c.ajustes_emplazamiento or {}).items()) if v)
    return {"Estrategia de pujas": c.estrategia_pujas or "desconocida", "Estrategia elegida": c.estrategia_objetivo,
            "Motivo de la estrategia": c.motivo_estrategia, "Ajustes de emplazamiento": ajustes or "0 %"}


def planificar(cuenta, doc, series, catalogo, hoy, gasto_mes, nuevas=()):
    """nuevas: campañas que se abren o reactivan en esta ronda (Cambios). Devuelve (cambios, filas
    para la hoja Campañas, presupuesto por campaña nueva, tope del día)."""
    total = safety.presupuesto_diario_total(hoy, gasto_mes)
    activas = [c for c in cuenta.campanas.values() if c.estado == ACTIVO]
    puntos = {c.id: puntuacion(c, cuenta, doc, series, catalogo, hoy) for c in activas}
    gastos = {c.id: gasto_medio(series, c.id, hoy) for c in activas}
    limites = {c.id: limite_util(c, gastos[c.id]) for c in activas}
    pesos = {c.id: puntos[c.id][0] for c in activas} | {f"nueva:{i}": 1.0 for i in range(len(nuevas))}
    plan = _repartir(total, pesos, {k: v[0] for k, v in limites.items()}) if pesos else {}
    for i in range(len(nuevas)):
        if f"nueva:{i}" in plan:
            plan[f"nueva:{i}"] = min(plan[f"nueva:{i}"], config.PRESUPUESTO_MAX_CAMPANA_NUEVA)
    # A una campaña que no gasta su presupuesto no se le recorta si ese dinero no le hace falta a nadie
    # (lo libre del tope ya cubre lo que piden las demás): bajarlo solo ahogaría lo que se le añada.
    holgadas = [c for c in activas if limites[c.id][0] is not None and plan[c.id] < c.presupuesto]
    if holgadas:
        resto = {k: v for k, v in plan.items() if k not in {c.id for c in holgadas}}
        if sum(resto.values()) + sum(c.presupuesto for c in holgadas) <= total + 0.01:
            for c in holgadas:
                plan[c.id] = c.presupuesto

    cambios, filas = [], []
    for c in activas:
        nuevo = plan[c.id]
        dif = nuevo - c.presupuesto
        pts, acos, conf, origen = puntos[c.id]
        tope_util, limitada = limites[c.id]
        acos_txt = "sin datos" if acos is None else ("sin ventas" if acos == float("inf") else f"{acos:.0%}")
        gasto_txt = ("gasto medio desconocido" if gastos[c.id] is None else
                     f"gasta {gastos[c.id]:.2f} €/día de media" + (" (limitada por presupuesto)" if limitada else
                                                                     f"; más de {tope_util:.2f} € no le sirve"))
        nota = ""
        if abs(dif) >= max(config.CAMBIO_MINIMO_PRESUPUESTO_EUR, config.CAMBIO_MINIMO_PRESUPUESTO_PCT * c.presupuesto):
            ult = doc.tickets(clave=f"camp:{c.id}", tipos=(PRESUPUESTO,))
            ult_subida = next((t for t in reversed(ult) if (t["Después"] or 0) > (t["Antes"] or 0)), None)
            if dif > 0 and ult_subida and (hoy - fecha(ult_subida["Fecha"])).days < config.DIAS_ENTRE_SUBIDAS_PRESUPUESTO:
                nota = "subida aplazada: hubo otra hace menos de 3 días"
            else:
                fin = hoy - timedelta(days=config.DIAS_MADUREZ + 1)
                antes = _ventana(series, c.id, fin - timedelta(days=14), fin)
                cambios.append(Cambio(
                    tipo=PRESUPUESTO, clave=f"camp:{c.id}", producto=cuenta.producto_de_campana(c.id), id_campana=c.id,
                    id_grupo=None, campana=c.nombre, texto="(presupuesto diario)", coincidencia="", antes=c.presupuesto,
                    despues=nuevo, base=learner.acumulado_campana(series, c.id, hoy),
                    motivo=(f"Tope del día {total:.2f} € (840 €/mes) repartido por puntuación entre todas las campañas. "
                            f"ACOS {acos_txt} ({origen}), confianza {conf:.2f}, puntuación {pts:.2f}; {gasto_txt}"),
                    extra={"ventas_dia_antes": round(antes.ventas / 14, 2), "limitada": limitada}))
        filas.append({"ID campaña": c.id, "Campaña": c.nombre, "Estado": c.estado,
                      "Producto (ASIN)": cuenta.producto_de_campana(c.id),
                      "Gasto medio 7 días (€)": None if gastos[c.id] is None else round(gastos[c.id], 2),
                      "Limitada por presupuesto": "Sí" if limitada else "",
                      "Presupuesto diario (€)": c.presupuesto, "Presupuesto objetivo (€)": nuevo,
                      "ACOS 30 días": None if acos in (None, float("inf")) else round(acos, 3),
                      "Puntuación": round(pts, 2), "Confianza (aprendizaje)": round(conf, 2),
                      **_estrategia(c),
                      "Creada por el agente": "Sí" if c.id in creadas_por_agente(doc) else "",
                      "Actualizado": hoy.isoformat() + (f" ({nota})" if nota else "")})
    for c in cuenta.campanas.values():
        if c.estado != ACTIVO:
            filas.append({"ID campaña": c.id, "Campaña": c.nombre, "Estado": c.estado,
                          "Producto (ASIN)": cuenta.producto_de_campana(c.id),
                          "Presupuesto diario (€)": c.presupuesto, "Presupuesto objetivo (€)": None, **_estrategia(c),
                          "Actualizado": hoy.isoformat() + f" ({c.estado}: no se le asigna presupuesto)"})
    por_nueva = [plan[f"nueva:{i}"] for i in range(len(nuevas))]
    return cambios, filas, por_nueva, total


def presupuesto_para_nueva(cuenta, doc, series, catalogo, hoy, gasto_mes):
    """Lo que le tocaría a una campaña más si se abriera (o reactivara) ahora (coste de oportunidad, §2.6)."""
    _, _, por_nueva, _ = planificar(cuenta, doc, series, catalogo, hoy, gasto_mes, nuevas=[None])
    return por_nueva[0]
