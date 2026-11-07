"""
ai_marketing_agent.py
----------------------
El agente de marketing "de verdad": en vez de aplicar un umbral fijo de
ACOS con un if/else, le pasa TODOS los datos reales del día a Claude (vía
API) y le pide que razone y decida qué hacer con su propio criterio — como
lo haría un gestor de PPC humano mirando la cuenta.

IMPORTANTE — esto NO sustituye a safety.py, lo complementa:
Lo que la IA proponga pasa SIEMPRE por sanitize_commands() antes de
ejecutarse. Los límites (tope de cambio ±20%, presupuesto mensual, tope de
keywords/experimentos por día, stop-loss) son inviolables pase lo que
pase — si la IA propone algo fuera de esos límites, se recorta o se
descarta, nunca se ejecuta tal cual. La IA decide el QUÉ y el POR QUÉ;
safety.py decide los límites del CUÁNTO. Esta doble capa es la que hace
que "que piense por sí sola" sea seguro con dinero real.

Requiere ANTHROPIC_API_KEY (ver README.md) — distinta de cualquier acceso
a Claude en el chat o en Claude Code.
"""

import json
import os
from dataclasses import asdict
from datetime import datetime

import anthropic

from browser_agent import KeywordRow, SearchTermRow
from learner import get_keyword_history, aggressiveness_multiplier, last_change_timestamp
from safety import (
    MAX_BID_CHANGE_PCT,
    RESET_HOURS,
    MONTHLY_BUDGET_CAP_EUR,
    MAX_NEW_KEYWORDS_PER_DAY,
    MAX_NEW_EXPERIMENTS_PER_DAY,
    EXPERIMENT_STARTING_BID_EUR,
    experiment_budget_per_keyword,
    is_within_reset_window,
    capped_new_bid,
    budget_allows_bid_increase,
)
from commands import Command
from analyzer import Action, ACOS_TARGET_MIN, ACOS_TARGET_MAX
from import_historical_data import load_historical_data

MODEL = os.environ.get("MARKETING_AGENT_MODEL", "claude-sonnet-4-5")

VALID_ACTIONS = {a.value for a in Action}

SYSTEM_PROMPT = f"""Eres una experta en marketing de Amazon Ads, con años de experiencia \
gestionando campañas de PPC. Trabajas para FreshFinder (tienda de \
juguetes y artículos de deporte en Amazon) y tu trabajo es revisar el \
rendimiento real de hoy y decidir qué acciones tomar sobre las \
keywords — con criterio propio, no aplicando una fórmula rígida.

Una parte importante de tu trabajo es APRENDER de tus propias decisiones \
pasadas, no solo de los datos de hoy: se te da la tasa de acierto \
histórica de cada keyword (cuántas de tus subidas de puja anteriores \
mejoraron el ACOS realmente, no solo sobre el papel) y, cuando existe, \
rendimiento real anterior a que gestionaras esta cuenta. Trata ese \
historial como lo haría una gestora experta: confía más en una keyword \
que ya ha demostrado responder bien, sé más cautelosa con una que ya te \
ha fallado antes, aunque sus métricas de hoy parezcan buenas.

Reglas de negocio que debes respetar en tu razonamiento (los límites \
NUMÉRICOS exactos los aplica un sistema aparte después, tú céntrate en \
el criterio):
- ACOS objetivo: entre {ACOS_TARGET_MIN:.0%} y {ACOS_TARGET_MAX:.0%}. Por debajo es rentable \
  (candidato a subir puja); por encima no lo es (candidato a bajar o pausar).
- Presupuesto mensual total: {MONTHLY_BUDGET_CAP_EUR:.0f}€ — sé conservador si el mes ya \
  va gastado.
- Puedes proponer promover un término de búsqueda real (con clics y \
  ventas ya demostradas) a keyword propia.
- Puedes proponer un experimento: una frase de búsqueda NUEVA, sin \
  ningún dato previo, que creas que un cliente real podría usar para \
  este producto — esto es una apuesta deliberada para aprender, así que \
  sé selectivo y justifica bien por qué crees que puede funcionar.
- Ten en cuenta el histórico de cada keyword si se te da (tasa de \
  acierto de cambios anteriores) — una keyword que ha respondido bien a \
  subidas antes merece más confianza que una sin historial.
- Si se te da "rendimiento_historico_previo", es rendimiento REAL de \
  antes de que este sistema existiera (importado de exports de Amazon) — \
  trátalo como una señal fuerte, no como ruido: una keyword con buen \
  historial previo, aunque hoy tenga pocos clics, ya ha demostrado algo.

Responde ÚNICAMENTE con un array JSON de decisiones, sin texto adicional, \
sin backticks. Cada elemento debe tener este formato exacto:
{{"action": "subida_puja|bajada_puja|añadir_keyword|añadir_keyword_experimental|sin_cambio",
  "producto": "SKU/ASIN", "campana": "...", "ad_group": "...", "keyword": "...",
  "match_type": "Exacta|Frase|null", "puja_propuesta": 0.00 o null,
  "razonamiento": "por qué, en una frase"}}
Omite las keywords en las que tu decisión sea "sin_cambio" — no hace \
falta que las incluyas. No incluyas nada fuera del array JSON."""


def _build_context(
    keyword_rows: list[KeywordRow],
    search_term_rows: list[SearchTermRow],
    existing_keyword_texts: set,
    spend_so_far: float,
    day_of_month: int,
    new_keywords_today: int,
    new_experiments_today: int,
) -> str:
    """Construye el bloque de datos reales que ve la IA. Incluye el
    histórico de aprendizaje resumido por keyword — la IA ve la tasa de
    acierto, no el log crudo entero.
    """
    kw_data = []
    for row in keyword_rows:
        history = get_keyword_history(row.product_sku, row.keyword_text)
        kw_data.append({
            "producto": row.product_sku,
            "campana": row.campaign_name,
            "ad_group": row.ad_group_name,
            "keyword": row.keyword_text,
            "match_type": row.match_type,
            "puja_actual": row.current_bid,
            "clics": row.clicks,
            "coste": row.cost,
            "ventas": row.sales,
            "compras": row.orders,
            "acos": round(row.cost / row.sales, 3) if row.sales > 0 else None,
            "historial_tasa_acierto": history.success_rate,
            "historial_cambios_previos": history.total_changes,
        })

    st_data = [
        {
            "producto": row.product_sku,
            "campana": row.campaign_name,
            "ad_group": row.ad_group_name,
            "termino_busqueda": row.search_term,
            "ya_es_keyword": row.search_term in existing_keyword_texts,
            "clics": row.clicks,
            "coste": row.cost,
            "ventas": row.sales,
            "compras": row.orders,
            "cpc_medio": row.avg_cpc,
        }
        for row in search_term_rows
    ]

    context = {
        "presupuesto": {
            "gastado_este_mes": spend_so_far,
            "tope_mensual": MONTHLY_BUDGET_CAP_EUR,
            "dia_del_mes": day_of_month,
        },
        "cupos_restantes_hoy": {
            "keywords_cosechadas": max(0, MAX_NEW_KEYWORDS_PER_DAY - new_keywords_today),
            "experimentos_nuevos": max(0, MAX_NEW_EXPERIMENTS_PER_DAY - new_experiments_today),
            "presupuesto_por_experimento": experiment_budget_per_keyword(),
        },
        "keywords_existentes": kw_data,
        "terminos_de_busqueda": st_data,
        "rendimiento_historico_previo": _historical_context_for(keyword_rows),
    }
    return json.dumps(context, ensure_ascii=False, indent=2)


def _historical_context_for(keyword_rows: list[KeywordRow]) -> list[dict]:
    """Rendimiento histórico importado (import_historical_data.py) de los
    productos que aparecen hoy — datos reales previos a este sistema, que
    la IA debe poder usar de contexto desde el primer día. Se filtra solo
    a los productos relevantes de esta ejecución para no inflar el prompt
    con histórico de productos que hoy ni se están mirando.
    """
    productos_hoy = {row.product_sku for row in keyword_rows}
    historico = load_historical_data()
    return [h for h in historico if h.get("producto") in productos_hoy]


def decide_with_ai(
    keyword_rows: list[KeywordRow],
    search_term_rows: list[SearchTermRow],
    existing_keyword_texts: set,
    now: datetime,
    spend_so_far: float,
    new_keywords_today: int,
    new_experiments_today: int,
) -> list[Command]:
    """Le pasa todo el contexto real a Claude y devuelve sus decisiones
    YA convertidas a Command — pero SIN aplicar todavía los límites duros.
    Eso lo hace sanitize_commands() a continuación, siempre, sin excepción.
    """
    client = anthropic.Anthropic()
    context = _build_context(
        keyword_rows, search_term_rows, existing_keyword_texts,
        spend_so_far, now.day, new_keywords_today, new_experiments_today,
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            temperature=0.2,  # decisiones sobre dinero real -> consistencia, no creatividad
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Datos de hoy:\n{context}"}],
        )
        raw = json.loads(response.content[0].text.strip())
    except Exception as e:
        print(f"  [ai_marketing_agent] Fallo al decidir con IA: {e} — no se aplica ningún cambio este ciclo.")
        return []

    commands = []
    for item in raw:
        action_str = item.get("action")
        if action_str not in VALID_ACTIONS or action_str == "sin_cambio":
            continue
        commands.append(Command(
            action=Action(action_str),
            producto=item.get("producto", ""),
            campana=item.get("campana", ""),
            ad_group=item.get("ad_group", ""),
            keyword=item.get("keyword", ""),
            match_type=item.get("match_type"),
            valor_antes=None,  # se rellena en sanitize_commands con el dato real
            valor_despues=item.get("puja_propuesta"),
            motivo=f"[IA] {item.get('razonamiento', '')}",
        ))
    return commands


def sanitize_commands(
    raw_commands: list[Command],
    keyword_rows: list[KeywordRow],
    active_experiments: set,
    now: datetime,
    spend_so_far: float,
) -> list[Command]:
    """La barrera que NUNCA se salta. Cada Command que propuso la IA pasa
    por aquí antes de ejecutarse. Si algo no cumple los límites duros, se
    recorta (pujas) o se descarta entero (todo lo demás) — nunca se
    ejecuta lo que pidió la IA tal cual sin pasar por esto.
    """
    by_key = {(r.product_sku, r.keyword_text): r for r in keyword_rows}
    safe: list[Command] = []
    new_kw_count = 0
    new_exp_count = 0

    for cmd in raw_commands:
        key = (cmd.producto, cmd.keyword)
        row = by_key.get(key)

        if cmd.action in (Action.SUBIR_PUJA, Action.BAJAR_PUJA):
            if row is None:
                continue  # la IA propuso algo sobre una keyword que no existe -> descartar
            last_change = last_change_timestamp(cmd.producto, cmd.keyword)
            if is_within_reset_window(last_change, now):
                continue  # tocada hace <24h -> se descarta, aunque la IA insista
            direction = "subir" if cmd.action == Action.SUBIR_PUJA else "bajar"
            if direction == "subir" and not budget_allows_bid_increase(spend_so_far, now.day):
                continue
            history = get_keyword_history(cmd.producto, cmd.keyword)
            aggressiveness = aggressiveness_multiplier(history)
            cmd.valor_antes = row.current_bid
            cmd.valor_despues = capped_new_bid(row.current_bid, direction, aggressiveness)
            # Foto del rendimiento AHORA, para poder medir el efecto del
            # cambio más adelante sin mezclarlo con el histórico previo.
            cmd.clics_base = row.clicks
            cmd.coste_base = row.cost
            cmd.ventas_base = row.sales

        elif cmd.action == Action.AÑADIR_KEYWORD:
            if new_kw_count >= MAX_NEW_KEYWORDS_PER_DAY:
                continue
            if cmd.keyword in by_key or key in active_experiments:
                continue  # ya existe, no se duplica
            new_kw_count += 1

        elif cmd.action == Action.GENERAR_EXPERIMENTO:
            if new_exp_count >= MAX_NEW_EXPERIMENTS_PER_DAY:
                continue
            cmd.valor_despues = EXPERIMENT_STARTING_BID_EUR  # nunca el valor libre que proponga la IA
            new_exp_count += 1

        else:
            continue  # cualquier acción no reconocida aquí se descarta, nunca se ejecuta

        safe.append(cmd)

    return safe
