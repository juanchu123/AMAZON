"""
safety.py
---------
Estas reglas van SIEMPRE antes de aplicar cualquier cambio, sin excepción.
Ninguna otra parte del sistema puede saltárselas, y no se relajan solas
aunque el rendimiento parezca justificarlo — solo Juan las cambia, y a mano.
"""

from datetime import datetime, timedelta

MAX_BID_CHANGE_PCT = 0.20      # tope: ±20% por ejecución
RESET_HOURS = 24                # no tocar la misma keyword antes de 24h
MONTHLY_BUDGET_CAP_EUR = 100.0  # presupuesto duro mensual
MAX_NEW_KEYWORDS_PER_DAY = 3    # tope de keywords "cosechadas" (con datos reales) por ejecución
NEW_KEYWORD_STARTING_BID_FACTOR = 1.0  # puja inicial = puja actual del grupo (ajustable)

# --- Fondo de exploración: keywords 100% nuevas, inventadas, sin datos previos ---
# Distinto del harvesting de arriba: aquí no hay ningún dato real detrás, es una
# apuesta pura para que el sistema aprenda qué frases nuevas podrían funcionar.
EXPLORATION_FUND_MONTHLY_EUR = 20.0   # asumido de una conversación anterior — ajustable
MAX_NEW_EXPERIMENTS_PER_DAY = 3       # cuántas ideas nuevas se prueban por día
EXPERIMENT_STOP_LOSS_RATIO = 0.5      # se mata al superar el 50% de su presupuesto sin ventas
EXPERIMENT_STARTING_BID_EUR = 0.30    # puja de partida conservadora para algo sin historial


def is_within_reset_window(last_change_iso: str | None, now: datetime) -> bool:
    """True si la keyword YA fue tocada dentro de las últimas RESET_HOURS
    horas -> en ese caso, NO se debe volver a tocar en esta ejecución.
    """
    if last_change_iso is None:
        return False
    last_change = datetime.fromisoformat(last_change_iso)
    return (now - last_change) < timedelta(hours=RESET_HOURS)


def capped_new_bid(current_bid: float, direction: str, aggressiveness: float) -> float:
    """direction: 'subir' o 'bajar'. aggressiveness: 0.0–1.0 (de learner.py).

    El cambio real aplicado es aggressiveness * MAX_BID_CHANGE_PCT, nunca
    más que el tope. aggressiveness solo decide CUÁNTO dentro del tope,
    jamás lo supera.
    """
    if not (0.0 <= aggressiveness <= 1.0):
        raise ValueError("aggressiveness debe estar entre 0 y 1")

    pct_change = MAX_BID_CHANGE_PCT * aggressiveness

    if direction == "subir":
        return round(current_bid * (1 + pct_change), 2)
    elif direction == "bajar":
        return round(current_bid * (1 - pct_change), 2)
    else:
        raise ValueError("direction debe ser 'subir' o 'bajar'")


def projected_monthly_spend(spend_so_far_this_month: float, day_of_month: int) -> float:
    """Proyección lineal simple: gasto hasta ahora / días transcurridos * 30.
    Conservadora a propósito — mejor sobreestimar el gasto que quedarse corto.
    """
    if day_of_month <= 0:
        return spend_so_far_this_month
    daily_avg = spend_so_far_this_month / day_of_month
    return round(daily_avg * 30, 2)


def budget_allows_bid_increase(spend_so_far_this_month: float, day_of_month: int) -> bool:
    """False si el gasto proyectado ya roza el presupuesto mensual — en ese
    caso solo se permiten bajadas/pausas, ninguna subida de puja, el resto
    del mes, aunque el rendimiento lo justifique.
    """
    projected = projected_monthly_spend(spend_so_far_this_month, day_of_month)
    return projected < MONTHLY_BUDGET_CAP_EUR


def new_keyword_bid(current_search_term_cpc: float) -> float:
    """Puja inicial para una keyword recién promovida desde un término de
    búsqueda: parte del CPC medio que ya venía pagando ese término (no un
    valor arbitrario), para no sobrepagar de salida por algo sin historial
    propio como keyword independiente.
    """
    return round(current_search_term_cpc * NEW_KEYWORD_STARTING_BID_FACTOR, 2)


def experiment_budget_per_keyword() -> float:
    """Cuánto presupuesto tiene asignado, en total, cada keyword experimental
    (inventada, sin datos previos): el fondo de exploración mensual repartido
    entre el número de experimentos que se lanzan cada día.
    """
    return round(EXPLORATION_FUND_MONTHLY_EUR / MAX_NEW_EXPERIMENTS_PER_DAY, 2)


def should_kill_experiment(cost_since_creation: float, orders_since_creation: int) -> bool:
    """Stop-loss de una keyword experimental. Se revisa en cada ejecución
    diaria para cada experimento activo — no espera a que termine el mes.

    Regla: si NO ha generado ninguna venta todavía y su gasto acumulado
    desde que se creó supera el 50% de su presupuesto asignado, se mata
    inmediatamente. Una sola venta, aunque sea pequeña, la salva de esta
    regla (entonces pasa a tratarse como una keyword normal, vía
    decide_base_action en el siguiente ciclo).
    """
    if orders_since_creation > 0:
        return False
    return cost_since_creation > experiment_budget_per_keyword() * EXPERIMENT_STOP_LOSS_RATIO
