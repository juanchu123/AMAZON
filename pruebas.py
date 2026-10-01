"""
pruebas.py — pruebas autónomas (Juan, 30/09/2026): "el histórico es malo y hay que aprender".

Además de las candidatas que ya salen rentables de media (ACOS predicho ≤ 30 %), el agente prueba
frases con POTENCIAL: las que serían rentables si su conversión real estuviera en la parte buena de lo
que es plausible. Sin datos propios, la conversión de una frase es incierta: con el modelo como punto
de partida (peso de 20 clics) su conversión sigue una Beta(20·p, 20·(1−p)); el potencial es su
percentil 80. Una prueba entra si su ACOS con ese potencial es ≤ 30 %.

  - Pérdida limitada: cada prueba tiene el mismo stop-loss que todo (20 clics o 4 € maduros sin
    venta -> pausa); con el retraso de 7 días de la atribución, una prueba fallida cuesta como mucho
    ~8 € (config.PERDIDA_MAX_PRUEBA_EUR).
  - Cuántas: las que quepan en lo que queda del tope del mes al ritmo de gasto actual, a 8 € cada una,
    menos las que ya están en marcha, y como mucho 3 nuevas por ronda.
  - Cuándo no: en periodos de ventas raras (Black Friday, Navidad…; config.PERIODOS_SIN_PRUEBAS): se
    aprende mal y se paga caro (Amazon Ads Academy: probar en periodos estables).
  - Aprender qué tipo de frases funcionan: por producto, tipo = (específica o genérica, coincidencia).
    Con lo que ha pasado en las keywords que ha añadido el agente se calcula
        factor del tipo = (compras reales + 1) / (compras que esperaba el modelo + 1)   (entre 0,25 y 2)
    y ese factor corrige la conversión que se espera de las frases nuevas de ese tipo (pruebas y
    candidatas normales). Si las genéricas en amplia no venden, cada vez se prueban menos.
"""

import json
import math

from scipy.stats import beta

import config
import safety
from modelo import ACTIVO, NUEVA_KEYWORD, REACTIVAR

CUANTIL_POTENCIAL = 0.80
FACTOR_MIN, FACTOR_MAX = 0.25, 2.0


def p_potencial(p, peso=None):
    """Percentil 80 de la conversión plausible de una frase sin datos propios."""
    peso = peso or config.PRIOR_CLICS
    if p <= 0:
        return 0.0
    p = min(p, 0.99)
    return float(beta.ppf(CUANTIL_POTENCIAL, peso * p, peso * (1 - p)))


def periodo_sin_pruebas(hoy):
    """Nombre del periodo si hoy no se abren pruebas nuevas, o None."""
    md = hoy.strftime("%m-%d")
    for ini, fin, nombre in config.PERIODOS_SIN_PRUEBAS:
        if (ini <= md <= fin) if ini <= fin else (md >= ini or md <= fin):
            return nombre
    return None


def _extra(t):
    try:
        return json.loads(t.get("Datos extra") or "{}")
    except (TypeError, ValueError):
        return {}


def tipo(catalogo, asin, texto, coincidencia):
    return ("específica" if catalogo._especifica(catalogo.producto(asin), texto) else "genérica", coincidencia)


class Aprendizaje:
    """Factor por (producto, tipo de frase) a partir de las keywords que ha añadido el agente."""

    def __init__(self, doc, series, catalogo, hoy):
        self.catalogo = catalogo
        acum = {}
        for t in doc.tickets(tipos=(NUEVA_KEYWORD, REACTIVAR)):
            x = _extra(t)
            if "p_modelo" not in x:
                continue
            asin = str(t["Producto (ASIN)"])
            clave = (asin,) + tipo(catalogo, asin, t["Palabra clave / segmentación"], t["Coincidencia"])
            base_clics = float(t.get("Base: clics") or 0)
            m = series.maduro(str(t["Clave"]), hoy)
            clics = max(0.0, m.clics - base_clics)
            compras = max(0.0, m.compras - float(t.get("Base: compras") or 0))
            a = acum.setdefault(clave, [0.0, 0.0, 0.0])     # clics, compras, compras esperadas
            a[0] += clics
            a[1] += compras
            a[2] += clics * x["p_modelo"]
        self.datos = acum

    def factor(self, asin, texto, coincidencia):
        a = self.datos.get((asin,) + tipo(self.catalogo, asin, texto, coincidencia))
        return self.factor_de(*a) if a else 1.0

    def filas(self):
        """Para la hoja 'Aprendizaje': qué tipo de frases funcionan."""
        out = []
        for (asin, clase, coinc), (clics, compras, esperadas) in sorted(self.datos.items()):
            out.append({"Producto (ASIN)": asin, "Producto": self.catalogo.producto(asin).corto, "Tipo de frase": clase,
                        "Coincidencia": coinc, "Clics maduros": clics, "Compras": compras,
                        "Compras que esperaba el modelo": round(esperadas, 2),
                        "Factor": round(self.factor_de(clics, compras, esperadas), 2)})
        return out

    @staticmethod
    def factor_de(clics, compras, esperadas):
        return min(FACTOR_MAX, max(FACTOR_MIN, (compras + 1) / (esperadas + 1)))


def activas(doc, cuenta, series, hoy):
    """Pruebas en marcha: keywords que el agente añadió como prueba, activas y aún sin ninguna venta."""
    n = 0
    for t in doc.tickets(tipos=(NUEVA_KEYWORD,)):
        if not _extra(t).get("prueba"):
            continue
        el = cuenta.elementos.get(str(t["Clave"]))
        if el and el.estado == ACTIVO and series.acumulado(el.clave, hoy).compras <= float(t.get("Base: compras") or 0):
            n += 1
    return n


def cupo(doc, cuenta, series, hoy, gasto_mes):
    """(pruebas nuevas que caben hoy, explicación)."""
    periodo = periodo_sin_pruebas(hoy)
    if periodo:
        return 0, f"{periodo}: no se abren pruebas (ventas raras, se aprende mal y se paga caro)"
    en_marcha = activas(doc, cuenta, series, hoy)
    dias = safety.dias_mes(hoy)
    if gasto_mes is None:
        return max(0, min(1, config.MAX_PRUEBAS_NUEVAS_POR_RONDA - en_marcha)), (
            "gasto del mes desconocido: como mucho 1 prueba nueva")
    ritmo = gasto_mes / max(1, hoy.day - 1)
    queda = config.TOPE_MENSUAL_EUR - gasto_mes - ritmo * (dias - hoy.day + 1)
    caben = max(0, math.floor(queda / config.PERDIDA_MAX_PRUEBA_EUR) - en_marcha)
    n = min(caben, config.MAX_PRUEBAS_NUEVAS_POR_RONDA)
    return n, (f"al ritmo actual quedan {queda:.0f} € del tope: caben {caben} pruebas más de "
               f"{config.PERDIDA_MAX_PRUEBA_EUR:.0f} € ({en_marcha} en marcha)")
