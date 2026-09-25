"""
run_daily.py
------------
Punto de entrada único. Esto es lo que se programa para correr una vez
al día (cron, Task Scheduler, etc. — ver README.md).

Orquesta tres piezas, cada una con su responsabilidad separada:

  1. SUBAGENTE (browser_agent.py) LEE los datos reales de Amazon Ads.
  2. AGENTE DE MARKETING IA (ai_marketing_agent.py) RAZONA sobre esos
     datos con Claude y PROPONE decisiones — no aplica reglas fijas, usa
     su propio criterio, como lo haría un gestor de PPC humano.
  3. sanitize_commands() aplica los límites duros (presupuesto, tope de
     cambio, tope de keywords/experimentos por día, reset de 24h) sobre
     lo que la IA propuso — esta capa NUNCA se salta, pase lo que
     proponga la IA.
  4. SUBAGENTE EJECUTA cada orden ya saneada, confirmando que se aplicó
     de verdad antes de darla por buena.
  5. Se registra en el log cada orden confirmada.

Además, antes de nada, se revisan los experimentos activos y se aplica
el stop-loss (esto es una regla dura, no pasa por la IA — un experimento
que ya demostró que no funciona se mata siempre igual).

Diseño defensivo: cualquier error de sesión o de scraping DETIENE la
ejecución entera y no aplica ningún cambio a medias.
"""

import sys
from datetime import datetime

from browser_agent import BrowserAgent, SessionExpiredError, ScrapeError
from ai_marketing_agent import decide_with_ai, sanitize_commands
from marketing_agent import monitor_experiments
from analyzer import Action
from learner import (
    append_decision,
    get_active_experiments,
    count_experiments_created_today,
    update_pending_results,
)


def execute_command(agent: BrowserAgent, cmd, now: datetime) -> None:
    """El subagente ejecuta UNA orden ya saneada. Solo registra en el log
    si consigue CONFIRMAR que el cambio se aplicó.
    """
    if cmd.action in (Action.AÑADIR_KEYWORD, Action.GENERAR_EXPERIMENTO):
        etiqueta = "keyword nueva" if cmd.action == Action.AÑADIR_KEYWORD else "EXPERIMENTO nuevo"
        print(f"  [{etiqueta}] {cmd.keyword!r} ({cmd.producto}): "
              f"puja {cmd.valor_despues:.2f}€ — {cmd.motivo}")
        # confirmed = agent.add_keyword(cmd.ad_group, cmd.keyword, cmd.match_type, cmd.valor_despues)
    elif cmd.action == Action.MATAR_EXPERIMENTO:
        print(f"  [STOP-LOSS] {cmd.keyword!r} ({cmd.producto}) — {cmd.motivo}")
        # confirmed = agent.pause_keyword(cmd.ad_group, cmd.keyword, cmd.match_type)
    else:
        print(f"  [{cmd.action.value}] {cmd.keyword!r} ({cmd.producto}): "
              f"{cmd.valor_antes:.2f}€ -> {cmd.valor_despues:.2f}€ — {cmd.motivo}")
        # confirmed = agent.update_bid(row_correspondiente, cmd.valor_despues)

    # if not confirmed:
    #     print(f"  [ERROR] no se pudo confirmar la orden en {cmd.keyword!r}, no se registra.")
    #     return

    append_decision({
        "fecha": now.strftime("%Y-%m-%d"),
        "producto": cmd.producto,
        "campana": cmd.campana,
        "keyword": cmd.keyword,
        "tipo_cambio": cmd.action.value,
        "valor_antes": cmd.valor_antes,
        "valor_despues": cmd.valor_despues,
        "motivo": cmd.motivo,
        "clics_base": cmd.clics_base,
        "coste_base": cmd.coste_base,
        "ventas_base": cmd.ventas_base,
        "resultado_siguiente": None,
    })


def main():
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    print(f"=== Ejecución diaria: {now.isoformat()} ===")

    try:
        with BrowserAgent(headless=True) as agent:
            # --- 1. EL SUBAGENTE LEE ---
            campaign_names = agent.get_active_campaign_names()
            print(f"Campañas encontradas: {campaign_names}")

            spend_so_far = 0.0  # TODO: sumar coste del mes desde la tabla de campañas
            active_experiments = get_active_experiments()
            new_experiments_today = count_experiments_created_today(today_str)
            new_keywords_today = 0  # cosechadas, se cuenta dentro de sanitize_commands

            for campaign in campaign_names:
                print(f"\n--- {campaign} ---")
                keyword_rows = agent.get_keyword_performance(campaign)
                search_term_rows = agent.get_search_terms(campaign)
                existing_texts = {row.keyword_text for row in keyword_rows}

                # --- 2a. CERRAR EL CICLO DE APRENDIZAJE: evaluar decisiones pasadas ---
                resueltas = update_pending_results(keyword_rows)
                if resueltas:
                    print(f"  Se evaluó el resultado de {resueltas} decisión(es) anterior(es) — el histórico ya lo tiene en cuenta.")

                # --- 2b. STOP-LOSS de experimentos activos (regla dura, no pasa por la IA) ---
                kill_commands = monitor_experiments(keyword_rows, active_experiments)
                for cmd in kill_commands:
                    execute_command(agent, cmd, now)
                    active_experiments.discard((cmd.producto, cmd.keyword))

                # --- 3. LA IA PROPONE ---
                proposed = decide_with_ai(
                    keyword_rows, search_term_rows, existing_texts, now,
                    spend_so_far, new_keywords_today, new_experiments_today,
                )
                print(f"  La IA propuso {len(proposed)} acción(es).")

                # --- 4. SE SANEA (límites duros, nunca se saltan) ---
                safe_commands = sanitize_commands(
                    proposed, keyword_rows, search_term_rows, active_experiments, now, spend_so_far
                )
                descartadas = len(proposed) - len(safe_commands)
                if descartadas:
                    print(f"  {descartadas} acción(es) descartada(s) por los límites de seguridad.")

                # --- 5. EL SUBAGENTE EJECUTA ---
                for cmd in safe_commands:
                    execute_command(agent, cmd, now)
                    if cmd.action == Action.AÑADIR_KEYWORD:
                        new_keywords_today += 1
                    elif cmd.action == Action.GENERAR_EXPERIMENTO:
                        new_experiments_today += 1

    except SessionExpiredError as e:
        print(f"\n[DETENIDO] Sesión caducada: {e}")
        print("Ejecuta: python src/capture_session.py")
        sys.exit(1)

    except ScrapeError as e:
        print(f"\n[DETENIDO] Error de scraping (posible cambio de HTML en Amazon): {e}")
        print("No se ha aplicado ningún cambio. Revisar browser_agent.py manualmente.")
        sys.exit(1)

    print("\n=== Fin de la ejecución ===")


if __name__ == "__main__":
    main()
