"""
marketing_agent.py
-------------------
Desde que existe ai_marketing_agent.py, este archivo YA NO es el que
decide pujas ni genera experimentos en el flujo normal — eso lo hace la
IA directamente, viendo keywords y términos de búsqueda a la vez y
proponiendo tanto harvesting como experimentos en la misma respuesta.

Lo que SÍ sigue usando run_daily.py de aquí es monitor_experiments(): el
stop-loss de experimentos activos es una regla dura y determinista a
propósito — una vez algo demuestra que no funciona, se mata siempre
igual, sin dejarlo a interpretación de la IA cada día.

El resto de funciones (decide_for_keyword, decide_for_search_term,
decide_all, generate_experiments) se quedan como un "modo determinista"
alternativo — útil si algún día se quiere apagar la IA y volver a reglas
fijas de ACOS sin reescribir nada, o para comparar sus decisiones contra
las de la IA. No se llaman en el flujo actual de run_daily.py.
"""

from datetime import datetime
from typing import Optional

from browser_agent import KeywordRow, SearchTermRow
from analyzer import decide_base_action, decide_new_keyword_action, Action
from learner import get_keyword_history, aggressiveness_multiplier, last_change_timestamp
from safety import (
    is_within_reset_window,
    capped_new_bid,
    budget_allows_bid_increase,
    new_keyword_bid,
    should_kill_experiment,
    experiment_budget_per_keyword,
    EXPERIMENT_STARTING_BID_EUR,
    MAX_NEW_KEYWORDS_PER_DAY,
)
from commands import Command
from keyword_generator import generate_keyword_ideas


def decide_for_keyword(
    row: KeywordRow, now: datetime, spend_so_far: float
) -> Optional[Command]:
    """Decide qué hacer con una keyword ya existente. Devuelve None si no
    hay que tocar nada (incluye: en reset de 24h, sin datos suficientes,
    dentro de objetivo, o requiere revisión manual por pausas repetidas).
    """
    campaign, product, keyword = row.campaign_name, row.product_sku, row.keyword_text

    last_change = last_change_timestamp(product, keyword)
    if is_within_reset_window(last_change, now):
        return None

    decision = decide_base_action(row.clicks, row.cost, row.sales)
    if decision.action == Action.SIN_CAMBIO:
        return None

    history = get_keyword_history(product, keyword)
    if history.requiere_revision:
        return None

    aggressiveness = aggressiveness_multiplier(history)

    if decision.action == Action.SUBIR_PUJA:
        if not budget_allows_bid_increase(spend_so_far, now.day):
            return None
        new_bid = capped_new_bid(row.current_bid, "subir", aggressiveness)
    elif decision.action == Action.BAJAR_PUJA:
        new_bid = capped_new_bid(row.current_bid, "bajar", aggressiveness)
    else:  # PAUSAR — no implementado como escritura todavía, ver CLAUDE.md
        return None

    return Command(
        action=decision.action,
        producto=product,
        campana=campaign,
        ad_group=row.ad_group_name,
        keyword=keyword,
        match_type=row.match_type,
        valor_antes=row.current_bid,
        valor_despues=new_bid,
        motivo=decision.reason,
    )


def decide_for_search_term(
    row: SearchTermRow, already_a_keyword: bool
) -> Optional[Command]:
    """Decide si un término de búsqueda real merece promoverse a keyword
    nueva. Devuelve None si no.
    """
    decision = decide_new_keyword_action(
        row.search_term, row.clicks, row.cost, row.sales, row.orders, already_a_keyword
    )
    if decision.action != Action.AÑADIR_KEYWORD:
        return None

    bid = new_keyword_bid(row.avg_cpc)
    return Command(
        action=Action.AÑADIR_KEYWORD,
        producto=row.product_sku,
        campana=row.campaign_name,
        ad_group=row.ad_group_name,
        keyword=row.search_term,
        match_type="Exacta",
        valor_antes=None,
        valor_despues=bid,
        motivo=decision.reason,
    )


def decide_all(
    keyword_rows: list[KeywordRow],
    search_term_rows: list[SearchTermRow],
    existing_keyword_texts: set[str],
    now: datetime,
    spend_so_far: float,
) -> list[Command]:
    """Punto de entrada único del agente de marketing: le pasas todo lo
    que el subagente ha leído, y te devuelve la lista completa de órdenes
    a ejecutar, ya con el tope de keywords nuevas por día aplicado.

    existing_keyword_texts: conjunto de textos de keyword ya configuradas
    (para no duplicar al evaluar términos de búsqueda) — el subagente lo
    construye a partir de keyword_rows o de una consulta aparte.
    """
    commands: list[Command] = []

    for row in keyword_rows:
        cmd = decide_for_keyword(row, now, spend_so_far)
        if cmd:
            commands.append(cmd)

    new_keyword_count = 0
    for row in search_term_rows:
        if new_keyword_count >= MAX_NEW_KEYWORDS_PER_DAY:
            break
        already = row.search_term in existing_keyword_texts
        cmd = decide_for_search_term(row, already)
        if cmd:
            commands.append(cmd)
            new_keyword_count += 1

    return commands


def monitor_experiments(
    keyword_rows: list[KeywordRow], active_experiments: set[tuple]
) -> list[Command]:
    """Revisa cada keyword experimental que sigue activa (creada por
    generate_experiments en un día anterior o el mismo día, y que todavía
    no se ha resuelto) y aplica el stop-loss.

    active_experiments: conjunto de (producto, keyword) de experimentos
    activos, tal como los devuelve learner.get_active_experiments().
    keyword_rows: lectura actual del subagente — como la keyword ya se
    creó, su coste/compras acumulados en la tabla de Amazon Ads SON el
    gasto y las ventas desde su creación (no hay historial anterior).
    """
    commands = []
    for row in keyword_rows:
        key = (row.product_sku, row.keyword_text)
        if key not in active_experiments:
            continue
        if should_kill_experiment(row.cost, row.orders):
            commands.append(Command(
                action=Action.MATAR_EXPERIMENTO,
                producto=row.product_sku,
                campana=row.campaign_name,
                ad_group=row.ad_group_name,
                keyword=row.keyword_text,
                match_type=row.match_type,
                valor_antes=row.current_bid,
                valor_despues=0.0,
                motivo=(
                    f"Stop-loss: {row.cost:.2f}€ gastados sin ninguna venta, "
                    f"supera el 50% de su presupuesto de exploración "
                    f"({experiment_budget_per_keyword():.2f}€) — se elimina."
                ),
            ))
    return commands


def generate_experiments(
    product_sku: str,
    product_title: str,
    product_category: str,
    campaign: str,
    ad_group: str,
    already_tried: set[str],
    count: int,
) -> list[Command]:
    """Pide ideas nuevas al generador (vía API de Claude) y las convierte
    en Command de tipo GENERAR_EXPERIMENTO, listas para que el subagente
    las añada con coincidencia Frase y la puja de partida conservadora.

    already_tried debe incluir TODO lo que ya existe como keyword para
    este producto más todo lo que ya se probó como experimento antes
    (ganado o perdido) — el generador no debe repetir ideas.
    """
    ideas = generate_keyword_ideas(product_title, product_category, already_tried, count)
    return [
        Command(
            action=Action.GENERAR_EXPERIMENTO,
            producto=product_sku,
            campana=campaign,
            ad_group=ad_group,
            keyword=idea,
            match_type="Frase",
            valor_antes=None,
            valor_despues=EXPERIMENT_STARTING_BID_EUR,
            motivo=(
                f"Idea nueva generada para probar — presupuesto asignado "
                f"{experiment_budget_per_keyword():.2f}€, se mata sola si "
                f"gasta más del 50% sin ninguna venta."
            ),
        )
        for idea in ideas
    ]
