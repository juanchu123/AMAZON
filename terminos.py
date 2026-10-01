"""
terminos.py — el informe de términos de búsqueda: cosecha y negativas (Amazon Ads Academy; Juan, 30/09/2026).

Lo que escribe el cliente (término) no es la keyword: una keyword en amplia o frase, o una campaña
automática, caza muchos términos distintos. En el histórico de la rejilla, las genéricas en amplia se
comieron el 88 % del gasto. Regla del curso, con CPA objetivo = ticket × ACOS objetivo (lo máximo que
se puede pagar en anuncios por una venta sin salirse del objetivo; nunca más que el equilibrio):

  - Término con ventas y ACOS ≤ objetivo  -> COSECHA: se añade como keyword en Exacta a un grupo manual
    del producto (analyzer.py le busca hueco, antes que a cualquier otra candidata).
  - Término sin ninguna venta con gasto MADURO ≥ CPA objetivo -> NEGATIVA (Exacta negativa) en el grupo
    que lo cazó. Una venta lo libra.
  - Término sin ventas con gasto por debajo del CPA -> seguir vigilando.
  - Cuando el término ya es keyword en Exacta en otro grupo -> Exacta negativa en el grupo de origen
    (automática, amplia o frase), para que el tráfico vaya a la exacta (pauta automática -> manual).

Nunca se pone negativa a un término que es la propia keyword que lo cazó (eso lo decide el stop-loss
de la keyword) ni a un ASIN (páginas de producto: pendiente).

Madurez: con la API el informe se pide solo con clics de más de 7 días. Con la hoja masiva cada
descarga trae acumulados sin fechas, así que se guarda una foto por día en la hoja "Términos" y el
gasto maduro es el de la foto de hace ≥ 7 días (las ventas, las de hoy: una venta es una venta).
"""

from datetime import timedelta

import config
import keyword_ml as kml
import pujas
import validacion
from documento import num
from modelo import ACTIVO, ARCHIVADO, KEYWORD, NEGATIVA, Cambio, Metricas

COINCIDENCIA_NEGATIVA = "Exacta negativa"
DIAS_FOTOS = 35          # fotos de términos que se guardan (hace falta una de hace 7-35 días)


def cpa_objetivo(ticket, asin):
    return ticket * min(config.ACOS_OBJETIVO_MAX, config.acos_equilibrio(asin))


def guardar_fotos(doc, cuenta, hoy):
    """Foto del día de cada término (solo con la hoja masiva: la API ya da clics maduros)."""
    hoy_s = hoy.isoformat()
    corte = (hoy - timedelta(days=DIAS_FOTOS)).isoformat()
    filas = [f for f in doc.hojas["Términos"] if corte <= str(f["Fecha"])[:10] != hoy_s]
    for t in cuenta.terminos:
        m = t.metricas
        filas.append({"Fecha": hoy_s, "Clave": t.clave, "ID campaña": t.id_campana, "ID grupo": t.id_grupo,
                      "Término de búsqueda": t.termino, "Keyword que lo cazó": t.origen, "Coincidencia": t.coincidencia,
                      "Clics": m.clics, "Coste (€)": round(m.coste, 2), "Compras": m.compras, "Ventas (€)": round(m.ventas, 2)})
    doc.hojas["Términos"] = filas


def maduro(doc, cuenta, termino, hoy):
    """Métricas maduras del término, o None si aún no se pueden saber (hoja masiva sin foto antigua)."""
    if cuenta.terminos_maduros:
        return termino.metricas
    limite = (hoy - timedelta(days=config.DIAS_MADUREZ)).isoformat()
    fotos = [f for f in doc.hojas["Términos"] if str(f["Clave"]) == termino.clave and str(f["Fecha"])[:10] <= limite]
    if not fotos:
        return None
    f = max(fotos, key=lambda f: str(f["Fecha"])[:10])
    return Metricas(num(f.get("Clics")), num(f.get("Coste (€)")), termino.metricas.compras, termino.metricas.ventas)


class Resultado:
    def __init__(self):
        self.negativas, self.cosecha, self.notas = [], {}, {}   # cosecha: asin -> [candidata]


def decidir(cuenta, doc, catalogo, hoy):
    r = Resultado()
    existentes = {(n.id_grupo, n.texto.strip().lower()) for n in cuenta.negativas if n.estado != ARCHIVADO}
    exactas = {}      # (asin, firma) -> [Elemento en Exacta]
    for e in cuenta.elementos.values():
        if e.tipo == KEYWORD and e.coincidencia == "Exacta" and e.estado != ARCHIVADO:
            exactas.setdefault((cuenta.producto_de_grupo(e.id_grupo), kml.firma(e.texto)), []).append(e)
    for t in sorted(cuenta.terminos, key=lambda t: -t.metricas.coste):
        g = cuenta.grupos.get(t.id_grupo)
        asin = cuenta.producto_de_grupo(t.id_grupo)
        if g is None or not asin or not cuenta.grupo_activo(g.id):
            continue
        texto = t.termino.strip().lower()
        fi = kml.firma(texto)
        if not fi or validacion.asin(texto):
            r.notas[t.clave] = "ASIN (página de producto): no se tocan por ahora"
            continue
        if not validacion.keyword(texto)[0]:
            r.notas[t.clave] = "Amazon no aceptaría este texto como keyword"
            continue
        prod = catalogo.producto(asin)
        if not prod.ticket:
            continue
        camp = cuenta.campanas[t.id_campana]
        base = dict(producto=asin, id_campana=t.id_campana, id_grupo=t.id_grupo, campana=camp.nombre, texto=texto,
                    coincidencia=COINCIDENCIA_NEGATIVA, antes=None, despues=COINCIDENCIA_NEGATIVA, base=t.metricas,
                    clave=f"neg:{t.id_grupo}:{texto}")
        ya_negativa = (t.id_grupo, texto) in existentes
        es_la_keyword = fi == kml.firma(t.origen)
        m = t.metricas

        # 1) traslado: el término ya es keyword en Exacta en otro grupo del producto
        destino = [e for e in exactas.get((asin, fi), []) if e.id_grupo != t.id_grupo and e.estado == ACTIVO
                   and cuenta.grupo_activo(e.id_grupo)]
        if destino and not ya_negativa and not es_la_keyword:
            r.negativas.append(Cambio(tipo=NEGATIVA, motivo=(
                f"El término ya es keyword en Exacta en '{cuenta.campanas[destino[0].id_campana].nombre}': negativa aquí "
                f"para que su tráfico vaya a la exacta (pauta automática/amplia -> manual exacta)"), **base))
            existentes.add((t.id_grupo, texto))
            r.notas[t.clave] = "Negativa de traslado a la exacta"
            continue

        # 2) cosecha
        if m.compras >= 1 and m.acos is not None and m.acos <= config.ACOS_OBJETIVO_MAX:
            if (asin, fi) in exactas or es_la_keyword and t.coincidencia == "Exacta":
                r.notas[t.clave] = "Vende; ya es keyword en Exacta"
                continue
            k = config.PRIOR_CLICS
            p = (m.compras + k * catalogo.p_modelo(asin, texto, "Exacta")) / (m.clics + k)
            if any(kml.firma(c["texto"]) == fi for c in r.cosecha.get(asin, [])):
                continue
            r.cosecha.setdefault(asin, []).append({
                "texto": texto, "coincidencia": "Exacta", "p": p, "acos_pred": m.acos, "fuente": "términos de búsqueda",
                "motivo": (f"Término de búsqueda que vende: {m.clics:.0f} clics, {m.compras:.0f} compras, ACOS {m.acos:.0%} "
                           f"(≤ {config.ACOS_OBJETIVO_MAX:.0%}), cazado por '{t.origen}' ({t.coincidencia})"),
                "grupo_origen": t.id_grupo})
            r.notas[t.clave] = "Cosecha: pasa a keyword en Exacta"
            continue

        # 3) negativa por CPA
        if m.compras > 0 or ya_negativa:
            continue
        if es_la_keyword:
            r.notas[t.clave] = "Es la propia keyword: lo decide su stop-loss"
            continue
        cpa = cpa_objetivo(prod.ticket, asin)
        mad = maduro(doc, cuenta, t, hoy)
        if mad is None:
            r.notas[t.clave] = "Sin ventas; aún no hay una foto de hace 7 días para saber el gasto maduro"
            continue
        if mad.coste >= cpa:
            r.negativas.append(Cambio(tipo=NEGATIVA, motivo=(
                f"Término sin ninguna venta con {mad.coste:.2f} € maduros gastados ({mad.clics:.0f} clics), más que el CPA "
                f"objetivo {cpa:.2f} € (ticket {prod.ticket:.2f} € × ACOS {cpa / prod.ticket:.0%}); cazado por "
                f"'{t.origen}' ({t.coincidencia})"), **base))
            existentes.add((t.id_grupo, texto))
            r.notas[t.clave] = "Negativa (gasto > CPA sin ventas)"
        else:
            r.notas[t.clave] = f"Vigilar: {mad.coste:.2f} € maduros sin ventas (CPA objetivo {cpa:.2f} €)"
    return r


def anotar(doc, hoy, resultado):
    """Escribe la decisión de hoy en las fotos del día."""
    for f in doc.hojas["Términos"]:
        if str(f["Fecha"])[:10] == hoy.isoformat():
            f["Decisión"] = resultado.notas.get(str(f["Clave"]), "")


def puja_cosecha(campana, cand, ticket, asin):
    return pujas.calcular(campana, cand["p"], ticket, 0.5, asin)
