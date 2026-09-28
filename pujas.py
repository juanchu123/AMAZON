"""
pujas.py — el sistema de pujas del agente (especificación de mejoras, P0-B §4).

Todo lo que decide cuánto se puja vive aquí; analyzer.py y safety.py solo llaman a estas funciones.

  Puja objetivo     = P(compra|clic) × ticket medio × ACOS objetivo (30-35 % según la agresividad).
  Tope rentable     = P(compra|clic) × ticket medio × ACOS de equilibrio: si un clic cuesta más,
                      cada venta pierde dinero.
  Multiplicador     = cuánto puede subir Amazon por su cuenta la puja escrita, en el peor emplazamiento:
                      (1 + ajuste del emplazamiento) × (1 + subida dinámica). Con "al alza y a la baja"
                      Amazon sube hasta +100 % arriba de la búsqueda y +50 % en el resto; con "solo a la
                      baja" y "puja fija" no sube nada.
  Puja que se escribe = min(objetivo, tope rentable / multiplicador): lo máximo que Amazon puede llegar
                      a cobrar por un clic nunca pasa del equilibrio.

Estrategia (la elige el agente, autorizado por Juan):
  "al alza y a la baja" solo si la campaña está probada (≥ 10 compras maduras en 30 días con ACOS ≤
  equilibrio) Y el margen deja que Amazon suba la puja sin pasar del equilibrio (ACOS objetivo ×
  multiplicador ≤ equilibrio). Si no, subir la puja por su cuenta obligaría a escribirla más baja y no
  compensa: "solo a la baja". El cambio va en la misma ronda que las pujas (misma hoja de cambios o
  misma llamada a la API, aplicado antes), así que las pujas se calculan ya para la estrategia elegida.
"""

import math
from dataclasses import dataclass

import config
from modelo import (ACTIVO, ALZA_BAJA, AMAZON_BUSINESS, ESTRATEGIA, PAGINA_PRODUCTO, PUJA_FIJA, RESTO_BUSQUEDA,
                    ESTRATEGIA_DESCONOCIDA, SOLO_BAJA, SUPERIOR, Cambio)


def normalizar_estrategia(texto):
    s = str(texto or "").lower()
    if ("solo" in s and "baja" in s) or s in ("legacy_for_sales", "down only", "dynamic bids - down only"):
        return SOLO_BAJA
    if "alza" in s or s in ("auto_for_sales", "up and down", "dynamic bids - up and down"):
        return ALZA_BAJA
    if "fija" in s or s in ("manual", "fixed bids"):
        return PUJA_FIJA
    return ESTRATEGIA_DESCONOCIDA


def normalizar_emplazamiento(texto):
    s = str(texto or "").lower()
    if "superior" in s or "top" in s:
        return SUPERIOR
    if "resto" in s or "rest_of_search" in s:
        return RESTO_BUSQUEDA
    if "producto" in s or "product_page" in s:
        return PAGINA_PRODUCTO
    if "business" in s:
        return AMAZON_BUSINESS
    return None


def _subida_dinamica(estrategia, emplazamiento):
    if estrategia in (SOLO_BAJA, PUJA_FIJA):
        return 0.0
    # "al alza y a la baja" o desconocida (se supone el peor caso)
    return config.SUBIDA_DINAMICA_SUPERIOR if emplazamiento == SUPERIOR else config.SUBIDA_DINAMICA_RESTO


def elegir_estrategia(campana, metricas_30d, asin=None):
    """(estrategia, motivo) para una campaña activa, con sus métricas maduras de los últimos 30 días."""
    eq = config.acos_equilibrio(asin)
    m = metricas_30d
    if m.compras < config.ALZA_MIN_COMPRAS_30D or m.acos is None or m.acos > eq:
        acos = "sin ventas" if m.acos in (None, float("inf")) else f"ACOS {m.acos:.0%}"
        return SOLO_BAJA, (f"{m.compras:.0f} compras maduras en 30 días ({acos}); hacen falta "
                           f"≥ {config.ALZA_MIN_COMPRAS_30D} con ACOS ≤ {eq:.0%} para dejar que Amazon suba pujas")
    mult = multiplicador(campana, ALZA_BAJA)
    if config.ACOS_OBJETIVO_MAX * mult > eq + 1e-9:
        return SOLO_BAJA, (f"probada ({m.compras:.0f} compras, ACOS {m.acos:.0%}), pero con ACOS objetivo "
                           f"{config.ACOS_OBJETIVO_MAX:.0%} × {mult:.2f} se pasaría del equilibrio {eq:.0%}: "
                           "habría que escribir la puja más baja y no compensa")
    return ALZA_BAJA, (f"probada ({m.compras:.0f} compras, ACOS {m.acos:.0%}) y con margen para que Amazon suba "
                       f"la puja ×{mult:.2f} sin pasar del equilibrio {eq:.0%}")


def decidir_estrategias(cuenta, metricas_30d_de):
    """Fija campana.estrategia_objetivo en cada campaña activa. metricas_30d_de(id_campana) -> Metricas."""
    for c in cuenta.campanas.values():
        if c.estado == ACTIVO:
            c.estrategia_objetivo, c.motivo_estrategia = elegir_estrategia(
                c, metricas_30d_de(c.id), cuenta.producto_de_campana(c.id))


def estrategia_gestionada(campana):
    """La estrategia con la que corre la campaña después de esta ronda."""
    return campana.estrategia_objetivo or campana.estrategia_pujas


def multiplicador(campana, estrategia=None):
    """Lo máximo que Amazon puede multiplicar la puja escrita en esta campaña (peor emplazamiento)."""
    estrategia = estrategia_gestionada(campana) if estrategia is None else estrategia
    ajustes = campana.ajustes_emplazamiento or {}
    lugares = set(ajustes) | {SUPERIOR, RESTO_BUSQUEDA}
    return max((1 + (ajustes.get(e) or 0) / 100) * (1 + _subida_dinamica(estrategia, e)) for e in lugares)


def puja_efectiva_max(campana, puja, estrategia=None):
    return puja * multiplicador(campana, estrategia)


def limitar(campana, puja, tope):
    """La puja que se puede escribir: nunca tanta que, con lo que Amazon suba, pase del tope.
    Si el redondeo al céntimo la dejara por encima, se redondea hacia abajo."""
    maximo = tope / multiplicador(campana)
    puja = round(min(puja, maximo), 2)
    if puja > maximo:
        puja = math.floor(maximo * 100) / 100
    return max(config.PUJA_MINIMA_AMAZON, puja)


@dataclass
class Calculo:
    puja: float           # la que se escribe
    objetivo: float       # p × ticket × ACOS objetivo
    tope: float           # p × ticket × ACOS de equilibrio
    multiplicador: float
    acos: float

    def explicacion(self, p, ticket):
        txt = f"P(compra|clic) {p:.1%} × ticket {ticket:.2f} € × ACOS {self.acos:.1%} = {self.objetivo:.2f} €"
        if self.puja < round(self.objetivo, 2):
            txt += (f"; Amazon puede subirla ×{self.multiplicador:.2f} (estrategia/emplazamiento) y el tope "
                    f"rentable es {self.tope:.2f} € -> {self.tope:.2f} / {self.multiplicador:.2f} = {self.puja:.2f} €")
        return txt


def calcular(campana, p, ticket, agresividad, asin=None):
    acos = config.ACOS_OBJETIVO_MIN + (config.ACOS_OBJETIVO_MAX - config.ACOS_OBJETIVO_MIN) * agresividad
    objetivo = p * ticket * acos
    tope = p * ticket * config.acos_equilibrio(asin)
    return Calculo(limitar(campana, objetivo, tope), objetivo, tope, multiplicador(campana), acos)


def puja_valida(puja, ticket, mult=1.0, asin=None):
    """La puja ajustada al suelo de Amazon, o None si es absurda (señal de un error de datos): ni con
    un 100 % de conversión sería rentable que Amazon cobrara puja × multiplicador por un clic."""
    if puja is None:
        return None
    puja = round(max(config.PUJA_MINIMA_AMAZON, puja), 2)
    if ticket and puja * mult > ticket * config.acos_equilibrio(asin) + 0.005:
        return None
    return puja


def proponer_estrategias(cuenta):
    """Cambio de estrategia para cada campaña activa cuya estrategia no sea la elegida. Se repite en
    cada ronda mientras Amazon no lo refleje: actualizar dos veces lo mismo no hace daño."""
    cambios = []
    for c in sorted(cuenta.campanas.values(), key=lambda c: c.nombre):
        if c.estado != ACTIVO or not c.estrategia_objetivo or c.estrategia_pujas == c.estrategia_objetivo:
            continue
        antes = c.estrategia_pujas or "desconocida"
        cambios.append(Cambio(
            tipo=ESTRATEGIA, clave=f"camp:{c.id}", producto=cuenta.producto_de_campana(c.id), id_campana=c.id,
            id_grupo=None, campana=c.nombre, texto="(estrategia de pujas)", coincidencia="", antes=antes,
            despues=c.estrategia_objetivo,
            motivo=(f"{c.motivo_estrategia}. Las pujas de esta ronda ya se calculan para '{c.estrategia_objetivo}' "
                    f"(Amazon puede subirlas hasta ×{multiplicador(c):.2f}): este cambio va con ellas.")))
    return cambios


def avisos(cuenta):
    """Ajustes de emplazamiento > 0 en campañas activas: el agente no los toca, pero cuentan en la puja."""
    out = []
    for c in cuenta.campanas.values():
        subidos = {e: v for e, v in (c.ajustes_emplazamiento or {}).items() if v}
        if c.estado == ACTIVO and subidos:
            txt = ", ".join(f"{e} +{v:.0f} %" for e, v in sorted(subidos.items()))
            out.append(("emplazamiento", c.id, f"La campaña '{c.nombre}' tiene ajustes de emplazamiento ({txt}). "
                        "El agente no los cambia, pero divide las pujas para que el clic más caro posible siga "
                        "siendo rentable. Si no los quieres, ponlos a 0 % en Amazon."))
    return out
