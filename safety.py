"""
safety.py — los límites que ninguna otra pieza puede saltarse.

Se aplican a TODO lo que propongan analyzer.py, presupuesto.py y campanas.py, justo antes de
ejecutar. Si algo no pasa, se descarta y queda anotado (nunca se "arregla" a ciegas).

  - Puja: nunca por debajo de 0,02 € (suelo de Amazon). Sin techo artificial (§2.2), pero sí
    uno matemático (pujas.py): lo que Amazon pueda cobrar por un clic (puja × lo que la suba la
    estrategia y los emplazamientos) nunca pasa del tope rentable.
  - Presupuesto: la suma de presupuestos diarios nunca permite pasar de 840 €/mes (§2.5).
  - Subidas de puja: prohibidas si el gasto del mes proyectado ya llega al tope (CLAUDE.md).
  - Cuenta: si todas las campañas están en pausa sin que el agente las pausara, o Amazon
    avisa de un problema de cuenta/pago, no se toca NADA y se avisa (§2.9-bis).
  - Nada fuera de lo que cubren las reglas: el agente nunca reactiva nada que esté en pausa.
"""

import calendar

import config
import pujas
from modelo import ACTIVO, CREAR_CAMPANA, ESTRATEGIA, NUEVA_KEYWORD, NUEVO_ASIN, PAUSAR, PRESUPUESTO, PUJA
from pujas import puja_valida

SEÑALES_PROBLEMA_CUENTA = ("PAYMENT_FAILURE", "SUSPENDED", "ACCOUNT_OUT_OF_BUDGET", "ADVERTISER_POLICING",
                           "ADVERTISER_OUT_OF_BUDGET", "ACCOUNT_SUSPENDED")


def dias_mes(hoy):
    return calendar.monthrange(hoy.year, hoy.month)[1]


def presupuesto_diario_total(hoy, gasto_mes):
    """Lo máximo que pueden sumar los presupuestos diarios hoy sin pasar de 840 €/mes:
    el ritmo medio del mes (840 / días del mes) y, si ya se ha gastado de más, lo que queda
    repartido entre los días que faltan (hoy incluido). Lo menor de los dos."""
    ritmo = config.TOPE_MENSUAL_EUR / dias_mes(hoy)
    if gasto_mes is None:
        return round(ritmo, 2)
    quedan = dias_mes(hoy) - hoy.day + 1
    restante = max(0.0, config.TOPE_MENSUAL_EUR - gasto_mes)
    return round(min(ritmo, restante / quedan), 2)


def gasto_proyectado(hoy, gasto_mes):
    if gasto_mes is None:
        return None
    transcurridos = max(1, hoy.day - 1)          # los datos llegan hasta ayer
    return gasto_mes / transcurridos * dias_mes(hoy)


def permite_subidas(hoy, gasto_mes):
    proy = gasto_proyectado(hoy, gasto_mes)
    return proy is None or proy < config.TOPE_MENSUAL_EUR


def problema_de_cuenta(cuenta, pausadas_por_el_agente):
    """Motivo para parar y avisar, o None si la cuenta está sana (§2.9-bis y CLAUDE.md)."""
    if cuenta.avisos_cuenta:
        return "Amazon avisa de un problema de cuenta: " + "; ".join(cuenta.avisos_cuenta)
    estados = [c.estado_servicio or "" for c in cuenta.campanas.values()] + \
              [a.estado_servicio or "" for a in cuenta.anuncios]
    malas = sorted({s for s in estados if any(x in s.upper() for x in SEÑALES_PROBLEMA_CUENTA)})
    if malas:
        return "Amazon marca un problema de cuenta o de pago: " + ", ".join(malas)
    ajenas = [c for c in cuenta.campanas.values() if c.id not in pausadas_por_el_agente]
    if not ajenas:
        return "No hay ninguna campaña en la cuenta (o no se ha podido leer ninguna)."
    if not any(c.estado == ACTIVO for c in ajenas):
        return (f"Todas las campañas ({len(ajenas)}) están en pausa o terminadas (fecha de finalización pasada) y "
                "no las ha pausado el agente (¿saldo de Seller Central, Oferta Destacada, stock, suspensión?). "
                "No se reactiva nada.")
    return None


def filtrar(cambios, cuenta, hoy, gasto_mes, ticket_de):
    """Última barrera antes de ejecutar. Devuelve (aprobados, descartados[(cambio, motivo)])."""
    aprobados, descartados = [], []
    subidas_ok = permite_subidas(hoy, gasto_mes)
    tope_dia = presupuesto_diario_total(hoy, gasto_mes)
    for c in cambios:
        motivo = None
        camp = cuenta.campanas.get(c.id_campana)
        mult = pujas.multiplicador(camp) if camp else 1.0
        tope = c.extra.get("tope_rentable")
        if c.tipo == PUJA:
            el = cuenta.elementos.get(c.clave)
            if el is None or el.estado != ACTIVO or not cuenta.grupo_activo(el.id_grupo):
                motivo = "el elemento ya no está activo"
            else:
                p = puja_valida(c.despues, ticket_de(c.producto), mult, c.producto)
                if p is None:
                    motivo = f"puja {c.despues} fuera de lo posible (con la subida de Amazon, más que ticket × equilibrio)"
                elif tope is not None and p * mult > tope + 0.005 and p > config.PUJA_MINIMA_AMAZON:
                    motivo = f"con la subida de Amazon (×{mult:.2f}) el clic podría costar más que el tope rentable {tope:.2f} €"
                elif p > (c.antes or 0) and not subidas_ok:
                    motivo = "el gasto del mes proyectado ya llega al tope: solo se permiten bajadas y pausas"
                else:
                    c.despues = p
        elif c.tipo == PAUSAR:
            el = cuenta.elementos.get(c.clave)
            if el is None or el.estado != ACTIVO:
                motivo = "el elemento ya no está activo"
        elif c.tipo in (NUEVA_KEYWORD, NUEVO_ASIN):
            if not cuenta.grupo_activo(c.id_grupo):
                motivo = "el grupo no está activo"
            elif puja_valida(c.despues, ticket_de(c.producto), mult, c.producto) is None:
                motivo = "puja fuera de lo posible"
            elif tope and c.despues * mult > tope + 0.005 and c.despues > config.PUJA_MINIMA_AMAZON:
                motivo = f"con la subida de Amazon (×{mult:.2f}) el clic podría costar más que el tope rentable {tope:.2f} €"
            elif not subidas_ok:
                motivo = "el gasto del mes proyectado ya llega al tope: no se añade gasto nuevo"
        elif c.tipo == PRESUPUESTO:
            if c.despues < config.PRESUPUESTO_MINIMO_AMAZON:
                motivo = "por debajo del mínimo de Amazon (1 €/día)"
        elif c.tipo == CREAR_CAMPANA:
            if not subidas_ok:
                motivo = "el gasto del mes proyectado ya llega al tope"
        elif c.tipo == ESTRATEGIA:
            if camp is None or camp.estado != ACTIVO:
                motivo = "la campaña no está activa"
        else:
            motivo = f"tipo de cambio no permitido: {c.tipo}"
        if motivo:
            descartados.append((c, motivo))
        else:
            aprobados.append(c)
    # el total de presupuestos diarios (campañas activas + nuevas) nunca pasa del tope del día
    nuevos = {c.id_campana: c.despues for c in aprobados if c.tipo == PRESUPUESTO}
    total = sum(nuevos.get(c.id, c.presupuesto) for c in cuenta.campanas.values() if c.estado == ACTIVO)
    total += sum(c.extra.get("presupuesto", 0) for c in aprobados if c.tipo == CREAR_CAMPANA)
    if total > tope_dia + 0.01:
        subidas = [c for c in aprobados if (c.tipo == PRESUPUESTO and c.despues > c.antes) or c.tipo == CREAR_CAMPANA]
        for c in subidas:
            aprobados.remove(c)
            descartados.append((c, f"los presupuestos sumarían {total:.2f} €/día, más que el tope de {tope_dia:.2f} €/día"))
    return aprobados, descartados
