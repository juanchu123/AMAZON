"""
analyzer.py — reglas de decisión por keyword / ASIN (AGENTE_AUTONOMO.md §2.1-2.4 y §2.7).

Para cada elemento de un grupo activo:
  0. Elegibilidad (§2.7): si el anuncio del grupo no puede mostrarse (sin Oferta Destacada,
     sin stock, ficha rechazada…) no se toca nada del grupo y se avisa aparte.
  1. Ronda (§2.1): solo se decide si han pasado ≥ 3 días desde su último cambio Y tiene
     ≥ 10 clics nuevos desde entonces. Si no, "esperar".
  2. Stop-loss (§2.4): 20 clics MADUROS (>7 días) o 4 € en clics maduros sin ninguna venta
     -> PAUSAR (nunca borrar). Una sola venta lo libra. Segunda pausa -> revisión de Juan.
  3. Puja (§2.2): la calcula pujas.py — P(compra|clic) × ticket medio × ACOS objetivo (30-35 % según
     la agresividad que ha aprendido learner.py), limitada para que ni con lo que Amazon suba por la
     estrategia y los emplazamientos se pague un clic por encima del equilibrio.
Y por cada grupo:
  4. Huecos (§2.3): hasta 12 keywords (o ASIN) activas; los huecos se rellenan con las mejores
     candidatas con ACOS predicho ≤ 30 %.

No ejecuta nada: devuelve Cambios que pasan por safety.py y después por la fuente.
"""

import config
import keyword_ml as kml
import learner
import pujas
from modelo import (ACTIVO, AUTO, KEYWORD, NUEVA_KEYWORD, NUEVO_ASIN, PAUSAR, PRODUCTO, PUJA, CATEGORIA,
                    Cambio, Metricas)

MARCAS_NO_ELEGIBLE = ("NOT_BUYABLE", "OUT_OF_STOCK", "INELIGIBLE", "NOT_ELIGIBLE", "POLICING", "REJECTED",
                      "LANDING_PAGE", "BUYBOX", "BUY_BOX", "MISSING", "SUSPENDED", "NO_INVENTORY")


def anuncio_elegible(anuncio):
    s = (anuncio.estado_servicio or "").upper()
    return not any(m in s for m in MARCAS_NO_ELEGIBLE)


def elegibilidad_grupo(cuenta, id_grupo):
    """(elegible, motivo). Elegible si al menos un anuncio activo del grupo puede mostrarse."""
    anuncios = [a for a in cuenta.anuncios if a.id_grupo == id_grupo and a.estado == ACTIVO]
    if not anuncios:
        return False, "el grupo no tiene ningún anuncio activo"
    if any(anuncio_elegible(a) for a in anuncios):
        return True, ""
    return False, "; ".join(f"{a.asin}: {a.estado_servicio}" for a in anuncios)


def _ultimo(doc, clave, tipos):
    ts = doc.tickets(clave=clave, tipos=tipos)
    return ts[-1] if ts else None


def _primera_fecha(series, clave):
    fechas = [d for d, _ in series.diario.get(str(clave), [])] + [d for d, _ in series.fotos.get(str(clave), [])]
    return min(fechas) if fechas else None


class Decision:
    """Lo que se decide de cada elemento (va a la columna 'Decisión de esta ronda')."""

    def __init__(self):
        self.cambios, self.notas, self.alertas, self.revision = [], {}, [], set()


def decidir(cuenta, doc, series, catalogo, hoy):
    d = Decision()
    grupos_no_elegibles = {}
    for g in cuenta.grupos.values():
        if cuenta.grupo_activo(g.id):
            ok, motivo = elegibilidad_grupo(cuenta, g.id)
            if not ok:
                grupos_no_elegibles[g.id] = motivo
                c = cuenta.campanas[g.id_campana]
                d.alertas.append(("no_elegible", g.id, f"Anuncio no elegible en '{c.nombre}' / '{g.nombre}': {motivo}. "
                                  "No se toca ninguna puja de ese grupo (es un problema de la ficha o la cuenta)."))

    pausadas_ahora = set()
    for el in sorted(cuenta.elementos.values(), key=lambda e: e.clave):
        if el.estado != ACTIVO or not cuenta.grupo_activo(el.id_grupo):
            continue
        if el.id_grupo in grupos_no_elegibles:
            d.notas[el.clave] = "No elegible: no se toca"
            continue
        cambio = _decidir_elemento(el, cuenta, doc, series, catalogo, hoy, d)
        if cambio:
            d.cambios.append(cambio)
            if cambio.tipo == PAUSAR:
                pausadas_ahora.add(el.clave)
    _rellenar_huecos(cuenta, doc, catalogo, hoy, d, pausadas_ahora, grupos_no_elegibles)
    return d


def _decidir_elemento(el, cuenta, doc, series, catalogo, hoy, d):
    asin = cuenta.producto_de_grupo(el.id_grupo)
    campana = cuenta.campanas[el.id_campana].nombre
    ult = _ultimo(doc, el.clave, (PUJA, PAUSAR, NUEVA_KEYWORD, NUEVO_ASIN))
    if ult:
        f_cambio = learner.fecha(ult["Fecha"])
        base = series.base_en(el.clave, f_cambio, learner._base(ult))
    else:
        f_cambio, base = _primera_fecha(series, el.clave), Metricas()
    if f_cambio is None:
        d.notas[el.clave] = "Esperar: aún sin datos"
        return None
    ahora = series.acumulado(el.clave, hoy)
    dias, nuevos = (hoy - f_cambio).days, ahora.clics - base.clics
    if dias < config.DIAS_ENTRE_CAMBIOS or nuevos < config.MIN_CLICS_NUEVOS:
        d.notas[el.clave] = f"Esperar: {dias} días y {nuevos:.0f} clics nuevos desde el último cambio (hace falta ≥3 y ≥10)"
        return None

    comun = dict(clave=el.clave, producto=asin, id_campana=el.id_campana, id_grupo=el.id_grupo, campana=campana,
                 texto=el.texto, coincidencia=el.coincidencia, base=ahora)

    # --- stop-loss: desde que el elemento existe (o se creó por el agente), sin ninguna venta
    creado = _ultimo(doc, el.clave, (NUEVA_KEYWORD, NUEVO_ASIN))
    inicio = series.base_en(el.clave, learner.fecha(creado["Fecha"]), learner._base(creado)) if creado else Metricas()
    maduro = series.maduro(el.clave, hoy) - inicio
    compras = ahora.compras - inicio.compras
    if compras <= 0 and (maduro.clics >= config.STOPLOSS_CLICS_MADUROS or maduro.coste >= config.STOPLOSS_COSTE_MADURO_EUR):
        previas = learner.veces_pausada(doc, asin, el.texto, el.coincidencia)
        revision = previas + 1 >= config.PAUSAS_PARA_REVISION
        if revision:
            d.revision.add(el.clave)
        d.notas[el.clave] = "PAUSAR (stop-loss)"
        return Cambio(tipo=PAUSAR, antes="activo", despues="pausado", requiere_revision=revision,
                      motivo=(f"Stop-loss: {maduro.clics:.0f} clics maduros y {maduro.coste:.2f} € maduros sin ninguna venta "
                              f"(límite {config.STOPLOSS_CLICS_MADUROS} clics o {config.STOPLOSS_COSTE_MADURO_EUR:.0f} €)"
                              + (f". Es su pausa nº {previas + 1}: requiere revisión de Juan, no se reactiva sola" if revision else "")),
                      **comun)

    # --- puja
    if el.puja is None:
        d.notas[el.clave] = "Sin puja propia"
        return None
    prod = catalogo.producto(asin) if asin else None
    ticket = prod.ticket if prod else None
    if not ticket:
        d.notas[el.clave] = "Sin ticket medio del producto: no se puede calcular la puja"
        return None
    mad_total = series.maduro(el.clave, hoy)
    p = catalogo.p_compra(asin, el.texto, el.coincidencia, mad_total)
    aggr = learner.agresividad(doc, asin, el.texto, el.coincidencia)
    calc = pujas.calcular(cuenta.campanas[el.id_campana], p, ticket, aggr, asin)
    nueva = calc.puja
    diferencia = abs(nueva - el.puja)
    if diferencia < max(config.CAMBIO_MINIMO_PUJA_EUR, config.CAMBIO_MINIMO_PUJA_PCT * el.puja):
        d.notas[el.clave] = f"Mantener: puja {el.puja:.2f} € ya está en su punto ({nueva:.2f} €)"
        return None
    sentido = "Subir" if nueva > el.puja else "Bajar"
    d.notas[el.clave] = f"{sentido} puja {el.puja:.2f} -> {nueva:.2f} €"
    return Cambio(tipo=PUJA, antes=el.puja, despues=nueva,
                  motivo=(f"{sentido}: {calc.explicacion(p, ticket)} "
                          f"({mad_total.clics:.0f} clics maduros, {mad_total.compras:.0f} compras; agresividad {aggr:.2f})"),
                  extra={"tope_rentable": round(calc.tope, 4), "multiplicador": round(calc.multiplicador, 3)},
                  **comun)


def _rellenar_huecos(cuenta, doc, catalogo, hoy, d, pausadas_ahora, no_elegibles):
    usadas = {}  # asin -> firmas / ASIN que el producto ya tiene (en cualquier estado)
    for el in cuenta.elementos.values():
        asin = cuenta.producto_de_grupo(el.id_grupo)
        s = usadas.setdefault(asin, set())
        s.add(el.texto.strip().upper() if el.tipo == PRODUCTO else kml.firma(el.texto))
    investig = {}
    activos_ = [g for g in cuenta.grupos.values() if cuenta.grupo_activo(g.id)]
    for g in sorted(activos_, key=lambda g: (cuenta.campanas[g.id_campana].nombre, g.nombre)):
        if g.id in no_elegibles:
            continue
        if cuenta.campanas[g.id_campana].segmentacion == "AUTO":
            continue
        asin = cuenta.producto_de_grupo(g.id)
        if not asin:
            continue
        els = cuenta.elementos_de_grupo(g.id)
        if any(e.tipo == AUTO for e in els):
            continue
        de_asin = any(e.tipo == PRODUCTO for e in els)
        activos = [e for e in els if e.estado == ACTIVO and e.clave not in pausadas_ahora
                   and e.tipo in (KEYWORD, PRODUCTO, CATEGORIA)]
        huecos = config.MAX_KEYWORDS_POR_GRUPO - len(activos)
        if huecos <= 0:
            continue
        ya = usadas.setdefault(asin, set())
        if de_asin:
            cands = catalogo.candidatas_asin(asin, doc.competidores(asin), ya)
        else:
            if asin not in investig:
                investig[asin] = doc.investigacion(asin)[1]
            cands = catalogo.candidatas(asin, ya, investig[asin])
        camp = cuenta.campanas[g.id_campana]
        campana = camp.nombre
        ticket = (catalogo.producto(asin).ticket if catalogo.producto(asin) else None) or 0
        for c in cands[:huecos]:
            ya.add(c["texto"].upper() if de_asin else kml.firma(c["texto"]))
            tope = c["p"] * ticket * config.acos_equilibrio(asin)
            puja = pujas.limitar(camp, c["puja"], tope) if tope > 0 else c["puja"]
            d.cambios.append(Cambio(
                tipo=NUEVO_ASIN if de_asin else NUEVA_KEYWORD, clave=f"nuevo:{g.id}:{c['texto']}", producto=asin,
                id_campana=g.id_campana, id_grupo=g.id, campana=campana, texto=c["texto"],
                coincidencia=c["coincidencia"], antes=None, despues=puja,
                motivo=(f"Hueco {len(activos) + 1}/{config.MAX_KEYWORDS_POR_GRUPO}: ACOS predicho {c['acos_pred']:.0%} "
                        f"(≤ {config.ACOS_MAX_KEYWORD_NUEVA:.0%}), P(compra|clic) {c['p']:.1%}, fuente {c['fuente']}. {c['motivo']}"),
                extra={"fuente": c["fuente"], "acos_pred": round(c["acos_pred"], 3), "tope_rentable": round(tope, 4),
                       "multiplicador": round(pujas.multiplicador(camp), 3)}))
            activos.append(None)
