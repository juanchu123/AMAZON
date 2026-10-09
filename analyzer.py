"""
analyzer.py — reglas de decisión por keyword / ASIN (AGENTE_AUTONOMO.md §2.1-2.4 y §2.7).

Para cada elemento de un grupo activo:
  0. Elegibilidad (§2.7): si el anuncio del grupo no puede mostrarse (sin Oferta Destacada,
     sin stock, ficha rechazada…) no se toca nada del grupo y se avisa aparte.
  1. Ronda (§2.1): solo se decide si han pasado ≥ 3 días desde su último cambio Y tiene
     ≥ 10 clics nuevos desde entonces. Si no, "esperar".
  2. Stop-loss (§2.4): 20 clics MADUROS (>7 días) o 4 € en clics maduros sin ninguna venta
     -> PAUSAR (nunca borrar). Una sola venta lo libra. Segunda pausa -> revisión de Juan.
     Se cuenta desde que el agente la creó o la reactivó.
  3. Puja (§2.2): una keyword que el agente acaba de crear o reactivar no se juzga hasta los 14 días
     (Amazon Ads Academy: tiempo para que se asiente la atribución); mientras, solo el stop-loss.
     La calcula pujas.py — P(compra|clic) × ticket medio × ACOS objetivo (30-35 % según
     la agresividad que ha aprendido learner.py), limitada para que ni con lo que Amazon suba por la
     estrategia y los emplazamientos se pague un clic por encima del equilibrio.
Y por cada grupo:
  4. Huecos (§2.3): hasta 12 keywords (o ASIN) activas; los huecos se rellenan, por este orden, con
     los términos de búsqueda que ya venden (cosecha, en Exacta: terminos.py) y después con lo mejor
     (menor ACOS predicho, ≤ 30 %) entre: keywords en pausa del grupo que los datos justifican
     reactivar (Juan, 30/09/2026; nunca las que requieren revisión de Juan), keywords que funcionaban
     en campañas terminadas (una campaña caducada no se reactiva: se copia lo bueno) y candidatas
     nuevas (histórico, investigación, modelo), corregidas por lo aprendido de cada tipo de frase.
     Si aún quedan huecos y hay cupo (pruebas.py), PRUEBAS: frases que no pasan de media pero sí con
     su potencial; su pérdida la limita el stop-loss.

No ejecuta nada: devuelve Cambios que pasan por safety.py y después por la fuente.
"""

import config
import keyword_ml as kml
import learner
import pujas
from modelo import (ACTIVO, ARCHIVADO, AUTO, FINALIZADA, KEYWORD, NUEVA_KEYWORD, NUEVO_ASIN, PAUSADO, PAUSAR,
                    PRODUCTO, PUJA, REACTIVAR, CATEGORIA, Cambio, Metricas)

CREA = (NUEVA_KEYWORD, NUEVO_ASIN, REACTIVAR)      # cambios desde los que se cuenta la vida del elemento

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


def decidir(cuenta, doc, series, catalogo, hoy, cosecha=None, cupo_pruebas=0, aprendizaje=None):
    """cosecha: {asin: [candidata]} de terminos.decidir (términos de búsqueda que ya venden).
    cupo_pruebas: pruebas nuevas que caben en esta ronda; aprendizaje: pruebas.Aprendizaje."""
    d = Decision()
    d.cupo_pruebas, d.aprendizaje = cupo_pruebas, aprendizaje
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
    _rellenar_huecos(cuenta, doc, series, catalogo, hoy, d, pausadas_ahora, grupos_no_elegibles, cosecha or {})
    return d


def _decidir_elemento(el, cuenta, doc, series, catalogo, hoy, d):
    asin = cuenta.producto_de_grupo(el.id_grupo)
    campana = cuenta.campanas[el.id_campana].nombre
    ult = _ultimo(doc, el.clave, (PUJA, PAUSAR) + CREA)
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

    # --- stop-loss: desde que el elemento existe (o el agente lo creó o reactivó), sin ninguna venta
    creado = _ultimo(doc, el.clave, CREA)
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

    # --- puja (lo recién creado o reactivado por el agente, o con menos de 14 días de datos, no se juzga)
    primera = _primera_fecha(series, el.clave)
    if not creado and primera and (hoy - primera).days < config.DIAS_PRIMERA_EVALUACION:
        d.notas[el.clave] = (f"Esperar: {(hoy - primera).days} días de datos (la puja se juzga a los "
                             f"{config.DIAS_PRIMERA_EVALUACION}; el stop-loss sí vigila)")
        return None
    if creado and (hoy - learner.fecha(creado["Fecha"])).days < config.DIAS_PRIMERA_EVALUACION:
        d.notas[el.clave] = (f"Esperar: {(hoy - learner.fecha(creado['Fecha'])).days} días desde que el agente la "
                             f"{'reactivó' if creado['Tipo'] == REACTIVAR else 'creó'} (la puja se juzga a los "
                             f"{config.DIAS_PRIMERA_EVALUACION}; el stop-loss sí vigila)")
        return None
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


def _reactivables(cuenta, doc, series, catalogo, hoy, g, asin, ticket):
    """Elementos en pausa del grupo que los datos justifican volver a activar (ACOS predicho ≤ 30 %
    con lo que ya se sabe de ellos). Nunca los que el agente ha pausado 2 veces (revisión de Juan)."""
    out = []
    camp = cuenta.campanas[g.id_campana]
    if camp.id in config.NO_REACTIVAR:
        return out
    for e in cuenta.elementos_de_grupo(g.id):
        if e.estado != PAUSADO or e.tipo not in (KEYWORD, PRODUCTO):
            continue
        if learner.veces_pausada(doc, asin, e.texto, e.coincidencia) >= config.PAUSAS_PARA_REVISION:
            continue
        cand = _evaluar_propia(e, asin, ticket, series, catalogo, hoy)
        if cand:
            cand |= {"clave": e.clave, "fuente": "reactivar", "puja_antes": e.puja,
                     "motivo": f"En pausa; con sus datos ({cand['datos']}) ya compensa: ACOS predicho {cand['acos_pred']:.0%}"}
            out.append(cand)
    return out


def _evaluar_propia(e, asin, ticket, series, catalogo, hoy):
    """Candidata a partir de un elemento propio (en pausa o de una campaña terminada), con sus clics
    maduros: P(compra|clic) mezclada con el modelo y el CPC que se pagó de verdad (si hay ≥ 5 clics)."""
    mad = series.maduro(e.clave, hoy)
    if not mad.clics and not mad.compras:
        mad = e.metricas
    p = catalogo.p_compra(asin, e.texto, e.coincidencia, mad)
    if e.tipo == KEYWORD:
        ev = catalogo.evaluar(asin, e.texto, e.coincidencia, pc=p)
        cpc = ev["cpc"] if ev["acos_pred"] is not None else None
    else:
        prod = catalogo.producto(asin)
        cpc = prod.cpc_competir * prod.factor_cpc if prod.cpc_competir else None
    if mad.clics >= config.FACTOR_CPC_MIN_CLICS and mad.coste > 0:
        cpc = mad.coste / mad.clics
    if not cpc or p <= 0 or not ticket:
        return None
    acos_pred = cpc / (p * ticket)
    if acos_pred > config.ACOS_MAX_KEYWORD_NUEVA:
        return None
    return {"texto": e.texto, "coincidencia": e.coincidencia, "p": p, "acos_pred": acos_pred,
            "datos": f"{mad.clics:.0f} clics maduros, {mad.compras:.0f} compras"}


def terminadas(cuenta, series, catalogo, hoy, asin, ticket):
    """Lo bueno de las campañas terminadas del producto (fecha de fin pasada): Amazon no deja
    reactivarlas, así que se copia a las campañas vivas."""
    out = []
    for e in cuenta.elementos.values():
        c = cuenta.campanas.get(e.id_campana)
        if (c is None or c.estado != FINALIZADA or e.tipo != KEYWORD or e.estado == ARCHIVADO
                or cuenta.producto_de_grupo(e.id_grupo) != asin):
            continue
        cand = _evaluar_propia(e, asin, ticket, series, catalogo, hoy)
        if cand:
            cand |= {"fuente": "campaña terminada",
                     "motivo": f"Funcionaba en '{c.nombre}' (terminada: se copia): {cand['datos']}"}
            out.append(cand)
    return sorted(out, key=lambda c: c["acos_pred"])


def _rellenar_huecos(cuenta, doc, series, catalogo, hoy, d, pausadas_ahora, no_elegibles, cosecha):
    usadas = {}  # asin -> firmas / ASIN que el producto ya tiene en campañas vivas (activas o en pausa)
    for el in cuenta.elementos.values():
        c = cuenta.campanas.get(el.id_campana)
        if el.estado == ARCHIVADO or c is None or c.estado in (FINALIZADA, ARCHIVADO):
            continue
        asin = cuenta.producto_de_grupo(el.id_grupo)
        s = usadas.setdefault(asin, set())
        s.add(el.texto.strip().upper() if el.tipo == PRODUCTO else kml.firma(el.texto))
    investig, copias = {}, {}
    cosecha = {a: list(v) for a, v in cosecha.items()}
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
        camp = cuenta.campanas[g.id_campana]
        ticket = (catalogo.producto(asin).ticket if catalogo.producto(asin) else None) or 0
        reactivar = [c for c in _reactivables(cuenta, doc, series, catalogo, hoy, g, asin, ticket)
                     if c["clave"] not in pausadas_ahora]
        if de_asin:
            nuevas = catalogo.candidatas_asin(asin, doc.competidores(asin), ya)
            primero = []
        else:
            if asin not in investig:
                investig[asin] = doc.investigacion(asin)[1]
                copias[asin] = terminadas(cuenta, series, catalogo, hoy, asin, ticket)
            ajuste = (lambda t, m, a=asin: d.aprendizaje.factor(a, t, m)) if d.aprendizaje else None
            nuevas = ([c for c in copias[asin] if kml.firma(c["texto"]) not in ya]
                      + catalogo.candidatas(asin, ya, investig[asin], ajuste=ajuste))
            primero = cosecha.get(asin, [])
        resto = sorted(reactivar + nuevas, key=lambda c: c["acos_pred"])
        elegidas = []
        while primero and len(elegidas) < huecos:          # la cosecha va antes que nada
            elegidas.append(primero.pop(0))
        for c in resto:
            if len(elegidas) >= huecos:
                break
            if c.get("fuente") != "reactivar":
                fi = c["texto"].upper() if de_asin else kml.firma(c["texto"])
                if fi in ya or any((x["texto"].upper() if de_asin else kml.firma(x["texto"])) == fi
                                   for x in elegidas if x.get("fuente") != "términos de búsqueda"):
                    continue
            elegidas.append(c)
        if not de_asin and len(elegidas) < huecos and d.cupo_pruebas > 0:
            vistas = ya | {kml.firma(x["texto"]) for x in elegidas}
            for c in catalogo.candidatas(asin, vistas, investig[asin], ajuste=ajuste, pruebas=True):
                if len(elegidas) >= huecos or d.cupo_pruebas <= 0:
                    break
                elegidas.append(c)
                d.cupo_pruebas -= 1
        for c in elegidas:
            if c.get("fuente") != "términos de búsqueda":
                ya.add(c["texto"].upper() if de_asin else kml.firma(c["texto"]))
            tope = c["p"] * ticket * config.acos_equilibrio(asin)
            if c.get("fuente") in ("reactivar", "términos de búsqueda", "campaña terminada") or "puja" not in c:
                aggr = learner.agresividad(doc, asin, c["texto"], c["coincidencia"])
                puja = pujas.calcular(camp, c["p"], ticket, aggr, asin).puja
                if c.get("cpc_real"):     # cosecha con pocos clics: no pagar mucho más de lo que costó
                    puja = max(config.PUJA_MINIMA_AMAZON, min(puja, round(config.COSECHA_MAX_X_CPC * c["cpc_real"], 2)))
            else:
                puja = pujas.limitar(camp, c["puja"], tope) if tope > 0 else c["puja"]
            extra = {"fuente": c["fuente"], "acos_pred": round(c["acos_pred"], 3), "p": round(c["p"], 5),
                     "p_modelo": round(c.get("p_modelo") or catalogo.p_modelo(asin, c["texto"], c["coincidencia"]), 5),
                     "tope_rentable": round(tope, 4), "multiplicador": round(pujas.multiplicador(camp), 3)}
            if c.get("prueba"):
                extra |= {"prueba": True, "acos_media": round(c["acos_media"], 3)}
            n = len(activos) + 1
            if c.get("fuente") == "reactivar":
                d.notas[c["clave"]] = f"REACTIVAR con puja {puja:.2f} €"
                d.cambios.append(Cambio(
                    tipo=REACTIVAR, clave=c["clave"], producto=asin, id_campana=g.id_campana, id_grupo=g.id,
                    campana=camp.nombre, texto=c["texto"], coincidencia=c["coincidencia"], antes=c.get("puja_antes"),
                    despues=puja, base=series.acumulado(c["clave"], hoy),
                    motivo=f"Hueco {n}/{config.MAX_KEYWORDS_POR_GRUPO}: {c['motivo']}", extra=extra))
            else:
                d.cambios.append(Cambio(
                    tipo=NUEVO_ASIN if de_asin else NUEVA_KEYWORD, clave=f"nuevo:{g.id}:{c['texto']}", producto=asin,
                    id_campana=g.id_campana, id_grupo=g.id, campana=camp.nombre, texto=c["texto"],
                    coincidencia=c["coincidencia"], antes=None, despues=puja,
                    motivo=(f"PRUEBA (hueco {n}/{config.MAX_KEYWORDS_POR_GRUPO}): de media ACOS {c['acos_media']:.0%}, "
                            f"pero con su potencial (conversión {c['p']:.1%}, percentil 80) {c['acos_pred']:.0%}. Pérdida "
                            f"limitada por el stop-loss. Fuente {c['fuente']}. {c['motivo']}") if c.get("prueba") else
                           (f"Hueco {n}/{config.MAX_KEYWORDS_POR_GRUPO}: ACOS "
                            f"{'real' if c['fuente'] == 'términos de búsqueda' else 'predicho'} {c['acos_pred']:.0%} "
                            f"(≤ {config.ACOS_MAX_KEYWORD_NUEVA if c['fuente'] != 'términos de búsqueda' else config.ACOS_OBJETIVO_MAX:.0%}), "
                            f"P(compra|clic) {c['p']:.1%}, fuente {c['fuente']}. {c['motivo']}"),
                    extra=extra | ({"grupo_origen": c["grupo_origen"]} if c.get("grupo_origen") else {})))
            activos.append(None)
