"""
campanas.py — ¿abrir o reactivar una campaña? (AGENTE_AUTONOMO.md §2.6; Juan, 30/09/2026)

Por defecto se AÑADE a la campaña que ya tiene el producto (analyzer.py rellena huecos hasta 12).
Solo se abre o se reactiva una campaña cuando hay al menos UNA candidata rentable (ACOS predicho
≤ 30 %, o un término de búsqueda que ya vende) y:
  A) el producto no tiene ninguna campaña activa:
       - si tiene alguna EN PAUSA cuyas keywords compensan con sus propios datos, se reactiva la mejor
         (Juan autorizó reactivar cuando los datos lo justifican); nunca las que acabaron por fecha
         (Amazon no deja: se copian). Una campaña en pausa sin keywords que compensen no se reactiva:
         volvería a gastar en lo que ya se sabe que no vende,
       - si no, se abre una nueva con las candidatas y lo que funcionaba en las terminadas;
  B) todas las campañas del producto están llenas (12/12) y sobra una candidata rentable sin sitio.
Y en los dos casos solo si el presupuesto da para pagarla DE VERDAD: con una campaña más, a la nueva
le tendrían que tocar ≥ 2,50 €/día; si no, no se abre (mejor seguir con lo que ya hay). Máximo una
por ronda. Nunca con la cuenta parada (eso lo para antes agente.py).
"""

from collections import Counter

import analyzer
import config
import keyword_ml as kml
import presupuesto
import pujas as pujas_
from modelo import (ACTIVO, ARCHIVADO, CREAR_CAMPANA, KEYWORD, NUEVA_KEYWORD, PAUSADO, REACTIVAR_CAMPANA,
                    SOLO_BAJA, Cambio, Campana, Metricas)


def proponer(cuenta, doc, series, catalogo, hoy, gasto_mes, cambios_previos, cosecha=None):
    """Devuelve ([Cambio CREAR_CAMPANA o REACTIVAR_CAMPANA], nota)."""
    hueco = presupuesto.presupuesto_para_nueva(cuenta, doc, series, catalogo, hoy, gasto_mes)
    if hueco < config.PRESUPUESTO_MIN_CAMPANA_NUEVA:
        return [], (f"No se abre ninguna campaña: con una más le tocarían {hueco:.2f} €/día "
                    f"(< {config.PRESUPUESTO_MIN_CAMPANA_NUEVA:.2f} €)")
    cosecha = cosecha or {}
    campanas_de = {}
    for a in cuenta.anuncios:
        c = cuenta.campanas.get(a.id_campana)
        if c and c.estado != ARCHIVADO and c not in campanas_de.setdefault(a.asin, []):
            campanas_de[a.asin].append(c)
    planeadas = [c for c in cambios_previos if c.tipo == NUEVA_KEYWORD]
    propuestas = []

    for asin, prod in catalogo.productos.items():
        sku = cuenta.sku_de_producto(asin) or prod.sku
        if not sku or not prod.ticket:
            continue
        _, investig = doc.investigacion(asin)
        campanas = campanas_de.get(asin, [])
        activas = [c for c in campanas if c.estado == ACTIVO]
        if not activas:                                                # caso A
            usadas = {kml.firma(e.texto) for e in cuenta.elementos.values()
                      if cuenta.producto_de_grupo(e.id_grupo) == asin and e.estado != ARCHIVADO
                      and cuenta.campanas.get(e.id_campana) and cuenta.campanas[e.id_campana].estado == PAUSADO}
            copias = analyzer.terminadas(cuenta, series, catalogo, hoy, asin, prod.ticket)
            cands = _unicas(cosecha.get(asin, []) + copias + catalogo.candidatas(asin, usadas, investig), asin, prod.ticket)
            pausadas = [c for c in campanas if c.estado == PAUSADO]
            mejor = _mejor_pausada(cuenta, series, catalogo, hoy, asin, prod.ticket, pausadas) if pausadas else None
            if mejor and mejor[1]:
                propuestas.append(("R", asin, prod, sku, mejor, (
                    f"{prod.corto} no tiene ninguna campaña activa; '{mejor[0].nombre}' está en pausa y "
                    f"{len(mejor[1])} de sus keywords compensan ya con sus propios datos")))
                continue
            if len(cands) >= config.MIN_KEYWORDS_CAMPANA_NUEVA:
                terminada = " (sus campañas acabaron por fecha: se copia lo bueno)" if campanas else ""
                propuestas.append(("A", asin, prod, sku, cands[:config.MAX_KEYWORDS_POR_GRUPO],
                                   f"{prod.corto} no tiene ninguna campaña viva{terminada} y hay {len(cands)} "
                                   "candidatas rentables"))
            continue
        grupos = [g for g in cuenta.grupos.values() if g.id_campana in {c.id for c in activas}
                  and cuenta.grupo_activo(g.id) and any(e.tipo == KEYWORD for e in cuenta.elementos_de_grupo(g.id))]
        if not grupos:
            continue
        llenos = all(sum(1 for e in cuenta.elementos_de_grupo(g.id) if e.estado == ACTIVO)
                     + sum(1 for c in cambios_previos if c.id_grupo == g.id and c.tipo in analyzer.CREA)
                     >= config.MAX_KEYWORDS_POR_GRUPO for g in grupos)
        if not llenos:
            continue
        usadas = {kml.firma(e.texto) for e in cuenta.elementos.values() if cuenta.producto_de_grupo(e.id_grupo) == asin
                  and cuenta.campanas.get(e.id_campana) and cuenta.campanas[e.id_campana].estado in (ACTIVO, PAUSADO)}
        usadas |= {kml.firma(c.texto) for c in planeadas if c.producto == asin}
        cands = _unicas([c for c in cosecha.get(asin, []) if not any(
            c["texto"] == x.texto for x in cambios_previos if x.producto == asin)]
            + catalogo.candidatas(asin, usadas, investig), asin, prod.ticket)
        if len(cands) >= config.MIN_KEYWORDS_CAMPANA_NUEVA:            # caso B
            propuestas.append(("B", asin, prod, sku, cands[:config.MAX_KEYWORDS_POR_GRUPO],
                               f"Las campañas de {prod.corto} están llenas (12/12) y '{cands[0]['texto']}' es rentable "
                               f"(ACOS {'real' if cands[0]['fuente'] == 'términos de búsqueda' else 'predicho'} "
                               f"{cands[0]['acos_pred']:.0%})"))
    if not propuestas:
        return [], "No hace falta abrir ni reactivar ninguna campaña"

    def orden(p):
        lista = p[4][1] if p[0] == "R" else p[4]
        mejores = sorted(c["acos_pred"] for c in lista)[:3] or [config.ACOS_MAX_KEYWORD_NUEVA]
        return sum(mejores) / len(mejores)

    propuestas.sort(key=orden)
    carteras = Counter(c.id_cartera for c in cuenta.campanas.values() if c.id_cartera)
    nombres = {c.nombre for c in cuenta.campanas.values()}
    out = []
    for caso, asin, prod, sku, datos, motivo in propuestas[:config.MAX_CAMPANAS_NUEVAS_POR_RONDA]:
        if caso == "R":
            camp, buenas = datos
            grupos = [g.id for g in cuenta.grupos.values() if g.id_campana == camp.id and g.estado == PAUSADO]
            anuncios = [a.id for a in cuenta.anuncios if a.id_campana == camp.id and a.asin == asin and a.estado == PAUSADO]
            out.append(Cambio(
                tipo=REACTIVAR_CAMPANA, clave=f"camp:{camp.id}", producto=asin, id_campana=camp.id, id_grupo=None,
                campana=camp.nombre, texto="(reactivar campaña)", coincidencia="", antes="pausado", despues="activo",
                base=Metricas(), motivo=motivo + f". Presupuesto ≈{hueco:.2f} €/día",
                extra={"grupos": grupos, "anuncios": anuncios}))
            continue
        cands = datos
        nombre = f"{prod.corto} - Principal (agente)" if caso == "A" else f"{prod.corto} - Ampliación {hoy:%d-%m-%Y}"
        while nombre in nombres:
            nombre += " bis"
        pujas = sorted(c["puja"] for c in cands)
        out.append(Cambio(
            tipo=CREAR_CAMPANA, clave=f"nueva:{nombre}", producto=asin, id_campana=None, id_grupo=None, campana=nombre,
            texto=f"{len(cands)} keywords", coincidencia="", antes=None, despues=None, base=Metricas(),
            motivo=motivo + f". Presupuesto ≈{hueco:.2f} €/día",
            extra={"nombre": nombre, "nombre_grupo": nombre, "sku": sku, "asin": asin,
                   "puja_grupo": pujas[len(pujas) // 2] if pujas else config.PUJA_GRUPO_DEFECTO,
                   "id_cartera": carteras.most_common(1)[0][0] if carteras else None,
                   "keywords": [{"texto": c["texto"], "coincidencia": c["coincidencia"], "puja": c["puja"],
                                 "motivo": f"ACOS {'real' if c['fuente'] == 'términos de búsqueda' else 'predicho'} "
                                           f"{c['acos_pred']:.0%}, fuente {c['fuente']}"} for c in cands]}))
    return out, "Se propone: " + ", ".join(
        ("reactivar " if c.tipo == REACTIVAR_CAMPANA else "abrir ") + c.campana for c in out)


def _unicas(cands, asin, ticket):
    """Sin repetir frase (la primera que aparece manda) y con puja: las que no la traen (cosecha,
    copias de campañas terminadas) la calculan como el resto, para una campaña nueva en solo a la baja."""
    out, vistas = [], set()
    nueva = Campana("", "", ACTIVO, 0.0, estrategia_pujas=SOLO_BAJA)
    for c in cands:
        fi = (kml.firma(c["texto"]), c["coincidencia"])
        if fi in vistas:
            continue
        vistas.add(fi)
        if c.get("puja") is None:
            c = c | {"puja": pujas_.calcular(nueva, c["p"], ticket, 0.5, asin).puja}
        out.append(c)
    return out


def _mejor_pausada(cuenta, series, catalogo, hoy, asin, ticket, pausadas):
    """(campaña, [candidatas propias que compensan]) de la campaña en pausa con más keywords buenas."""
    mejor = None
    for camp in sorted(pausadas, key=lambda c: c.nombre):
        buenas = []
        for e in cuenta.elementos.values():
            if e.id_campana != camp.id or e.estado == ARCHIVADO or e.tipo != KEYWORD:
                continue
            cand = analyzer._evaluar_propia(e, asin, ticket, series, catalogo, hoy)
            if cand:
                buenas.append(cand)
        if mejor is None or len(buenas) > len(mejor[1]):
            mejor = (camp, buenas)
    return mejor
