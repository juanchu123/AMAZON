"""
emplazamientos.py — ajustes de puja por emplazamiento, gestionados por el agente (Juan, 30/09/2026).

Amazon cobra la misma keyword en tres sitios que convierten distinto: arriba del todo de la búsqueda
(superior), el resto de la búsqueda y las páginas de producto. Con la puja base igual en los tres, se
paga de más donde convierte peor o se pierde tráfico donde convierte mejor. Amazon deja subir la puja
en cada emplazamiento de 0 % a +900 % (Amazon Ads Academy, informe de emplazamiento).

Regla (por campaña activa, con ≥ 5 compras y ≥ 100 clics en total):
  conversión de cada emplazamiento, prudente = (compras + 20 × conversión de la campaña) / (clics + 20)
  r = esa conversión / la de la campaña          (1 = convierte como la media)
  ajuste = r / r del peor emplazamiento − 1      (el peor queda a 0 %; tope +900 %)
Y la puja de cada keyword (pujas.py) se calcula para el peor emplazamiento, así que en cada uno el
clic cuesta lo que vale ahí: nunca por encima del equilibrio, ni sumando la subida de la estrategia.
Solo se cambia un ajuste si se mueve ≥ 10 puntos. Sin datos suficientes no se toca (y lo que haya
puesto cuenta igualmente en la puja). Amazon Business no se toca.
"""

import config
from modelo import ACTIVO, EMPLAZAMIENTO, PAGINA_PRODUCTO, RESTO_BUSQUEDA, SUPERIOR, Cambio, Metricas

LUGARES = (SUPERIOR, RESTO_BUSQUEDA, PAGINA_PRODUCTO)
PESO = 20.0


def ratios(campana):
    """{emplazamiento: r} o None si no hay datos suficientes."""
    met = {e: campana.metricas_emplazamiento.get(e) or Metricas() for e in LUGARES}
    total = sum((m for m in met.values()), Metricas())
    if total.compras < config.EMPLAZAMIENTO_MIN_COMPRAS or total.clics < config.EMPLAZAMIENTO_MIN_CLICS:
        return None
    conv = total.compras / total.clics
    return {e: ((m.compras + PESO * conv) / (m.clics + PESO)) / conv for e, m in met.items()}


def decidir(cuenta):
    """Fija campana.ratios_emplazamiento y campana.ajustes_objetivo; devuelve los Cambios."""
    cambios = []
    for c in sorted(cuenta.campanas.values(), key=lambda c: c.nombre):
        if c.estado != ACTIVO:
            continue
        r = ratios(c)
        if r is None:
            continue
        c.ratios_emplazamiento = r
        peor = min(r.values())
        actuales = {e: float(c.ajustes_emplazamiento.get(e) or 0) for e in LUGARES}
        nuevos = {e: float(min(900, round(100 * (r[e] / peor - 1)))) for e in LUGARES}
        if all(abs(nuevos[e] - actuales[e]) < config.EMPLAZAMIENTO_CAMBIO_MIN for e in LUGARES):
            continue
        c.ajustes_objetivo = dict(c.ajustes_emplazamiento) | nuevos
        m = c.metricas_emplazamiento
        detalle = "; ".join(f"{e}: {(m.get(e) or Metricas()).clics:.0f} clics, {(m.get(e) or Metricas()).compras:.0f} "
                            f"compras (×{r[e]:.2f}) -> +{nuevos[e]:.0f} %" for e in LUGARES)
        cambios.append(Cambio(
            tipo=EMPLAZAMIENTO, clave=f"camp:{c.id}", producto=cuenta.producto_de_campana(c.id), id_campana=c.id,
            id_grupo=None, campana=c.nombre, texto="(ajustes de emplazamiento)", coincidencia="",
            antes={e: actuales[e] for e in LUGARES}, despues=nuevos,
            motivo=(f"Conversión por emplazamiento frente a la media de la campaña: {detalle}. El peor queda a 0 % y "
                    "las pujas de esta ronda se calculan para él, así que en ningún sitio el clic pasa de lo que vale.")))
    return cambios
