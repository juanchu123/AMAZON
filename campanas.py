"""
campanas.py — ¿abrir una campaña nueva? (AGENTE_AUTONOMO.md §2.6)

Por defecto se AÑADE a la campaña que ya tiene el producto (analyzer.py rellena huecos hasta 12).
Solo se abre una campaña nueva cuando:
  A) un producto del catálogo no tiene ninguna campaña (ni activa ni en pausa) y tiene al menos
     3 candidatas con ACOS predicho ≤ 30 % (expansión de catálogo, autónoma), o
  B) todas las campañas del producto están llenas (12/12) y sobra una candidata claramente
     buena (ACOS predicho ≤ 25 %) sin sitio.
Y en los dos casos solo si el fondo de experimentación da para pagarla DE VERDAD: abrirla
reparte el 20 % entre una campaña más, y si a cada una le tocaría menos de 2,50 €/día no se
abre (coste de oportunidad: mejor seguir con lo que ya hay). Máximo una campaña por ronda.
Nunca se abre una campaña para un producto cuyas campañas ha pausado Juan.
"""

from collections import Counter

import config
import keyword_ml as kml
import presupuesto
from modelo import ACTIVO, ARCHIVADO, CREAR_CAMPANA, KEYWORD, NUEVA_KEYWORD, Cambio, Metricas


def proponer(cuenta, doc, series, catalogo, hoy, gasto_mes, cambios_previos):
    """Devuelve ([Cambio CREAR_CAMPANA], nota)."""
    hueco = presupuesto.hueco_experimental(cuenta, doc, series, catalogo, hoy, gasto_mes)
    if hueco < config.PRESUPUESTO_MIN_CAMPANA_EXPERIMENTAL:
        return [], (f"No se abre ninguna campaña: con una más, a cada experimental le tocarían {hueco:.2f} €/día "
                    f"(< {config.PRESUPUESTO_MIN_CAMPANA_EXPERIMENTAL:.2f} €)")

    con_campana = {}
    for a in cuenta.anuncios:
        c = cuenta.campanas.get(a.id_campana)
        if c and c.estado != ARCHIVADO:
            con_campana.setdefault(a.asin, []).append(c)
    planeadas = [c for c in cambios_previos if c.tipo == NUEVA_KEYWORD]
    propuestas = []

    for asin, prod in catalogo.productos.items():
        sku = cuenta.sku_de_producto(asin) or prod.sku
        if not sku:
            continue
        _, investig = doc.investigacion(asin)
        campanas = con_campana.get(asin, [])
        if not campanas:                                              # caso A
            cands = catalogo.candidatas(asin, set(), investig)
            if len(cands) >= config.MIN_KEYWORDS_CAMPANA_NUEVA:
                propuestas.append(("A", asin, prod, sku, cands[:config.MAX_KEYWORDS_POR_GRUPO],
                                   f"{prod.corto} no tiene ninguna campaña y hay {len(cands)} candidatas con ACOS predicho ≤ 30 %"))
            continue
        if not any(c.estado == ACTIVO for c in campanas):
            continue                                                  # Juan las pausó: no se abre otra
        grupos = [g for g in cuenta.grupos.values() if g.id_campana in {c.id for c in campanas}
                  and cuenta.grupo_activo(g.id) and any(e.tipo == KEYWORD for e in cuenta.elementos_de_grupo(g.id))]
        if not grupos:
            continue
        llenos = all(sum(1 for e in cuenta.elementos_de_grupo(g.id) if e.estado == ACTIVO)
                     + sum(1 for c in planeadas if c.id_grupo == g.id) >= config.MAX_KEYWORDS_POR_GRUPO for g in grupos)
        if not llenos:
            continue
        usadas = {kml.firma(e.texto) for e in cuenta.elementos.values() if cuenta.producto_de_grupo(e.id_grupo) == asin}
        usadas |= {kml.firma(c.texto) for c in planeadas if c.producto == asin}
        cands = catalogo.candidatas(asin, usadas, investig)
        buenas = [c for c in cands if c["acos_pred"] <= config.ACOS_CLARAMENTE_BUENA]
        if buenas and len(cands) >= config.MIN_KEYWORDS_CAMPANA_NUEVA:     # caso B
            propuestas.append(("B", asin, prod, sku, cands[:config.MAX_KEYWORDS_POR_GRUPO],
                               f"Las campañas de {prod.corto} están llenas (12/12) y '{buenas[0]['texto']}' tiene "
                               f"ACOS predicho {buenas[0]['acos_pred']:.0%}"))
    if not propuestas:
        return [], "No hace falta abrir ninguna campaña"

    # la mejor: la de menor ACOS predicho medio en sus 3 mejores candidatas
    propuestas.sort(key=lambda p: sum(c["acos_pred"] for c in p[4][:3]) / 3)
    carteras = Counter(c.id_cartera for c in cuenta.campanas.values() if c.id_cartera)
    nombres = {c.nombre for c in cuenta.campanas.values()}
    out = []
    for caso, asin, prod, sku, cands, motivo in propuestas[:config.MAX_CAMPANAS_NUEVAS_POR_RONDA]:
        nombre = f"{prod.corto} - Principal (agente)" if caso == "A" else f"{prod.corto} - Ampliación {hoy:%d-%m-%Y}"
        while nombre in nombres:
            nombre += " bis"
        pujas = sorted(c["puja"] for c in cands)
        out.append(Cambio(
            tipo=CREAR_CAMPANA, clave=f"nueva:{nombre}", producto=asin, id_campana=None, id_grupo=None, campana=nombre,
            texto=f"{len(cands)} keywords", coincidencia="", antes=None, despues=None, base=Metricas(),
            motivo=motivo + f". Financiada con el fondo de experimentación (≈{hueco:.2f} €/día)",
            extra={"nombre": nombre, "nombre_grupo": nombre, "sku": sku, "asin": asin,
                   "puja_grupo": pujas[len(pujas) // 2] if pujas else config.PUJA_GRUPO_DEFECTO,
                   "id_cartera": carteras.most_common(1)[0][0] if carteras else None,
                   "keywords": [{"texto": c["texto"], "coincidencia": c["coincidencia"], "puja": c["puja"],
                                 "motivo": f"ACOS predicho {c['acos_pred']:.0%}, fuente {c['fuente']}"} for c in cands]}))
    return out, "Se propone abrir: " + ", ".join(c.campana for c in out)
