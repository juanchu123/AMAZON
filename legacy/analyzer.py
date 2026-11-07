"""
analyzer.py
-----------
Lógica pura, sin navegador ni ficheros: dado el rendimiento de una
keyword, decide qué tipo de acción tendría sentido según el ACOS objetivo.

No aplica límites de seguridad (eso es safety.py) ni mira el histórico
de aprendizaje (eso es learner.py) — esas dos capas ajustan/filtran lo
que decide esta.
"""

from dataclasses import dataclass
from enum import Enum

ACOS_TARGET_MIN = 0.30
ACOS_TARGET_MAX = 0.35
MIN_CLICKS_FOR_DECISION = 10  # por debajo de esto, no hay señal suficiente

# --- Descubrimiento de nuevas keywords (harvesting de términos de búsqueda) ---
# Un término de búsqueda real (de la pestaña "Términos de búsqueda", NO de la
# lista de keywords) se promueve a keyword nueva en coincidencia Exacta si
# demuestra rendimiento suficiente por sí mismo. Es más exigente que ajustar
# una puja existente: crear algo nuevo debe tener más evidencia detrás que
# simplemente tocar algo que ya existe.
MIN_CLICKS_FOR_NEW_KEYWORD = 5
MIN_ORDERS_FOR_NEW_KEYWORD = 1


class Action(str, Enum):
    SUBIR_PUJA = "subida_puja"
    BAJAR_PUJA = "bajada_puja"
    PAUSAR = "pausa"
    AÑADIR_KEYWORD = "añadir_keyword"                        # cosechada de datos reales
    GENERAR_EXPERIMENTO = "añadir_keyword_experimental"       # inventada, sin datos previos
    MATAR_EXPERIMENTO = "pausar_experimento_stop_loss"        # stop-loss de un experimento
    SIN_CAMBIO = "sin_cambio"


@dataclass
class Decision:
    action: Action
    reason: str


def decide_base_action(clicks: int, cost: float, sales: float) -> Decision:
    """Decisión "en frío", solo con los datos de la keyword — antes de que
    learner.py y safety.py la ajusten o la bloqueen.
    """
    if clicks < MIN_CLICKS_FOR_DECISION:
        return Decision(
            Action.SIN_CAMBIO,
            f"Solo {clicks} clics (mínimo {MIN_CLICKS_FOR_DECISION}) — "
            f"sin datos suficientes, dejar madurar.",
        )

    if sales <= 0:
        return Decision(
            Action.BAJAR_PUJA,
            f"{clicks} clics, {cost:.2f}€ de coste, 0€ en ventas — "
            f"gastando sin convertir.",
        )

    acos = cost / sales

    if acos < ACOS_TARGET_MIN:
        return Decision(
            Action.SUBIR_PUJA,
            f"ACOS {acos:.1%} por debajo del objetivo "
            f"({ACOS_TARGET_MIN:.0%}-{ACOS_TARGET_MAX:.0%}) — rentable, subir puja.",
        )

    if acos > ACOS_TARGET_MAX:
        return Decision(
            Action.BAJAR_PUJA,
            f"ACOS {acos:.1%} por encima del objetivo "
            f"({ACOS_TARGET_MIN:.0%}-{ACOS_TARGET_MAX:.0%}) — no rentable, bajar puja.",
        )

    return Decision(
        Action.SIN_CAMBIO,
        f"ACOS {acos:.1%} dentro del rango objetivo — sin cambios.",
    )


def decide_new_keyword_action(
    search_term: str,
    clicks: int,
    cost: float,
    sales: float,
    orders: int,
    already_a_keyword: bool,
) -> Decision:
    """Decide si un término de búsqueda real (de la pestaña "Términos de
    búsqueda" de una campaña automática) merece promoverse a keyword nueva
    en coincidencia Exacta.

    Reglas, más exigentes que las de ajustar una keyword ya existente:
    - Si ya existe como keyword (en cualquier tipo de coincidencia), nunca
      se duplica — devuelve SIN_CAMBIO.
    - Necesita al menos MIN_CLICKS_FOR_NEW_KEYWORD clics para tener señal.
    - Necesita al menos MIN_ORDERS_FOR_NEW_KEYWORD compra real — clics sin
      ninguna venta nunca generan una keyword nueva, por muchos que sean
      (eso es una señal para negativizar el término, no para promoverlo;
      la negativización no está implementada todavía, ver CLAUDE.md).
    - El ACOS del propio término debe estar dentro o por debajo del rango
      objetivo — un término que convierte pero con ACOS disparado no es
      un buen candidato a keyword propia con puja más alta.
    """
    if already_a_keyword:
        return Decision(
            Action.SIN_CAMBIO,
            "Ya existe como keyword — no se duplica.",
        )

    if clicks < MIN_CLICKS_FOR_NEW_KEYWORD:
        return Decision(
            Action.SIN_CAMBIO,
            f"Solo {clicks} clics (mínimo {MIN_CLICKS_FOR_NEW_KEYWORD} para "
            f"considerar una keyword nueva).",
        )

    if orders < MIN_ORDERS_FOR_NEW_KEYWORD:
        return Decision(
            Action.SIN_CAMBIO,
            f"{clicks} clics pero 0 compras — no se promueve sin conversión "
            f"real, aunque haya tráfico.",
        )

    acos = cost / sales if sales > 0 else None
    if acos is not None and acos > ACOS_TARGET_MAX:
        return Decision(
            Action.SIN_CAMBIO,
            f"Convierte pero con ACOS {acos:.1%}, por encima del objetivo — "
            f"no es un buen candidato a keyword propia todavía.",
        )

    return Decision(
        Action.AÑADIR_KEYWORD,
        f"Término de búsqueda con {clicks} clics, {orders} compra(s) y "
        f"ACOS {acos:.1%} — se promueve a keyword Exacta." if acos is not None
        else f"Término de búsqueda con {clicks} clics, {orders} compra(s) — "
             f"se promueve a keyword Exacta.",
    )
