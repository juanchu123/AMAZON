"""
learner.py
----------
Esto es lo que hace que el sistema "aprenda" en vez de aplicar siempre
la misma regla ciega. Lee logs/decisions.jsonl, calcula cómo ha
respondido cada keyword a cambios anteriores, y devuelve un multiplicador
de agresividad que safety.py usa para escalar el cambio dentro del tope
máximo permitido (nunca lo supera, solo decide dónde caer dentro de él).

IMPORTANTE - aprendizaje por producto, no solo por keyword:
La misma palabra clave ("soporte movil coche") puede promocionar productos
distintos en campañas distintas, y puede funcionar genial para uno y mal
para otro. Si el histórico se mezclara entre productos, el sistema
aprendería una media borrosa que no sirve para ninguno de los dos.

Por eso el histórico se indexa por (product_sku, keyword) - el SKU (o ASIN
si no hay SKU) del producto que promociona ese grupo de anuncios, tal como
aparece en la pestaña "Anuncios" del grupo. La campaña se guarda en el log
por trazabilidad, pero NUNCA se usa para agrupar el aprendizaje - dos
campañas distintas para el mismo producto SI deben compartir historial;
una campaña que promocione productos distintos NO debe mezclar el suyo.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

LOG_FILE = Path(__file__).resolve().parent.parent / "logs" / "decisions.jsonl"


@dataclass
class KeywordHistory:
    total_changes: int
    subidas_con_mejora: int
    subidas_totales: int
    pausas_consecutivas_recientes: int

    @property
    def success_rate(self) -> Optional[float]:
        if self.subidas_totales == 0:
            return None
        return self.subidas_con_mejora / self.subidas_totales

    @property
    def requiere_revision(self) -> bool:
        """2+ pausas seguidas por mal rendimiento -> no reactivar solo."""
        return self.pausas_consecutivas_recientes >= 2


def _load_entries() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    entries = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _entries_for(product_sku: str, keyword: str) -> list[dict]:
    entries = [
        e
        for e in _load_entries()
        if e.get("producto") == product_sku and e.get("keyword") == keyword
    ]
    entries.sort(key=lambda e: e.get("fecha", ""))
    return entries


def get_keyword_history(product_sku: str, keyword: str) -> KeywordHistory:
    """Agrega el histórico de una keyword PARA UN PRODUCTO CONCRETO.

    product_sku: el SKU (o ASIN si no hay SKU) del producto del grupo de
    anuncios - NO la campaña. Esto es lo que evita que el aprendizaje se
    mezcle entre productos distintos que compartan la misma palabra clave.

    Sin historial previo, devuelve una KeywordHistory "neutra" (sin datos,
    agresividad por defecto).
    """
    entries = _entries_for(product_sku, keyword)

    subidas_totales = 0
    subidas_con_mejora = 0
    pausas_consecutivas = 0

    for e in entries:
        tipo = e.get("tipo_cambio")
        resultado = e.get("resultado_siguiente")

        if tipo == "subida_puja":
            if resultado is not None:
                # Solo cuenta hacia la tasa de acierto una vez evaluada —
                # una decisión pendiente no es ni un acierto ni un fallo,
                # es simplemente "todavía no lo sabemos".
                subidas_totales += 1
                if resultado.get("evaluacion") == "mejora":
                    subidas_con_mejora += 1

        if tipo == "pausa":
            pausas_consecutivas += 1
        elif tipo in ("subida_puja", "bajada_puja"):
            pausas_consecutivas = 0  # se reactivo, se rompe la racha

    return KeywordHistory(
        total_changes=len(entries),
        subidas_con_mejora=subidas_con_mejora,
        subidas_totales=subidas_totales,
        pausas_consecutivas_recientes=pausas_consecutivas,
    )


def aggressiveness_multiplier(history: KeywordHistory) -> float:
    """Devuelve un valor entre 0 y 1 que safety.py multiplica por el tope
    máximo de cambio permitido (ej. 20%).

    - Sin historial -> 0.5 (agresividad media, conservador por defecto)
    - Buena tasa de acierto reciente -> se acerca a 1.0 (más agresivo)
    - Mala tasa de acierto -> se acerca a 0.2 (muy conservador, pero nunca 0
      del todo, salvo que requiera revisión manual)
    """
    rate = history.success_rate
    if rate is None:
        return 0.5
    # Interpolación simple: 0% acierto -> 0.2, 100% acierto -> 1.0
    return round(0.2 + 0.8 * rate, 2)


def last_change_timestamp(product_sku: str, keyword: str) -> Optional[str]:
    """Para que safety.py aplique el reset de 24h. Igual que arriba,
    indexado por producto, no por campaña.
    """
    entries = _entries_for(product_sku, keyword)
    if not entries:
        return None
    return entries[-1].get("fecha")


def append_decision(entry: dict) -> None:
    """Añade una línea al log. entry debe incluir al menos:
    fecha, producto (SKU/ASIN), campana (trazabilidad), keyword,
    tipo_cambio, valor_antes, valor_despues, motivo

    'producto' es el campo que usa el aprendizaje para agrupar. 'campana'
    se guarda solo para que un humano pueda rastrear de dónde vino el
    cambio, nunca se usa para calcular historial.
    """
    if "producto" not in entry:
        raise ValueError(
            "append_decision requiere 'producto' (SKU/ASIN) - sin esto, "
            "el aprendizaje no puede separarse correctamente entre productos."
        )
    LOG_FILE.parent.mkdir(exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_active_experiments() -> set[tuple]:
    """Devuelve el conjunto de (producto, keyword) de experimentos
    todavía activos: se crearon (GENERAR_EXPERIMENTO) y no tienen
    ningún MATAR_EXPERIMENTO posterior para ese mismo (producto, keyword).
    """
    entries = _load_entries()
    entries.sort(key=lambda e: e.get("fecha", ""))

    active = set()
    for e in entries:
        key = (e.get("producto"), e.get("keyword"))
        if e.get("tipo_cambio") == "añadir_keyword_experimental":
            active.add(key)
        elif e.get("tipo_cambio") == "pausar_experimento_stop_loss":
            active.discard(key)
    return active


def get_all_tried_keywords(product_sku: str) -> set[str]:
    """Todo lo que ya se ha probado como keyword para un producto —
    cosechadas, experimentales ganadas o perdidas — para que
    keyword_generator.py nunca proponga algo repetido.
    """
    return {
        e["keyword"]
        for e in _load_entries()
        if e.get("producto") == product_sku and "keyword" in e
    }


def count_experiments_created_today(today: str) -> int:
    """Cuántas keywords experimentales se han creado ya HOY (en cualquier
    producto/campaña) — para respetar MAX_NEW_EXPERIMENTS_PER_DAY como
    tope global del día, no por campaña.

    today: fecha en formato 'YYYY-MM-DD', igual que se guarda en el log.
    """
    return sum(
        1
        for e in _load_entries()
        if e.get("fecha") == today and e.get("tipo_cambio") == "añadir_keyword_experimental"
    )


def _rewrite_all(entries: list[dict]) -> None:
    """Reescribe el log entero. Se usa SOLO desde update_pending_results
    para rellenar 'resultado_siguiente' de decisiones pasadas — nunca para
    borrar ni reordenar histórico real.
    """
    LOG_FILE.parent.mkdir(exist_ok=True)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def update_pending_results(keyword_rows, min_days: int = 3, min_new_clicks: int = 10) -> int:
    """Esto es lo que de verdad cierra el ciclo de aprendizaje: revisa las
    decisiones de subida/bajada de puja que llevan pendientes de evaluar
    (resultado_siguiente todavía None) al menos min_days días, calcula qué
    pasó DESDE ese cambio en concreto (no el acumulado histórico completo,
    que mezclaría el antes y el después) y escribe el veredicto.

    Sin esta función, get_keyword_history() nunca tiene subidas_con_mejora
    que contar, y toda la cuenta se queda para siempre en la agresividad
    neutra por defecto (0.5) — el sistema nunca aprendería nada.

    keyword_rows: la lectura ACTUAL del subagente (lifetime desde el
    inicio de la campaña). Se le resta la "foto" (clics_base/coste_base/
    ventas_base) que se guardó en el momento de la decisión para aislar
    el efecto de ESE cambio concreto.

    Se exige un mínimo de min_new_clicks clics nuevos desde la decisión
    para evaluar — igual que analyzer.MIN_CLICKS_FOR_DECISION, evaluar
    con poco ruido daría un veredicto poco fiable. Si no hay clics
    suficientes todavía, se deja pendiente para el próximo día.

    Devuelve cuántas decisiones se resolvieron en esta pasada.
    """
    from datetime import datetime

    by_key = {(r.product_sku, r.keyword_text): r for r in keyword_rows}
    entries = _load_entries()
    now = datetime.now()
    resolved = 0

    for e in entries:
        if e.get("resultado_siguiente") is not None:
            continue
        if e.get("tipo_cambio") not in ("subida_puja", "bajada_puja"):
            continue
        if e.get("coste_base") is None or e.get("ventas_base") is None:
            continue  # decisión antigua de antes de tener esta foto — no se puede evaluar bien

        fecha = e.get("fecha")
        try:
            dias_pasados = (now - datetime.strptime(fecha, "%Y-%m-%d")).days
        except (TypeError, ValueError):
            continue
        if dias_pasados < min_days:
            continue

        row = by_key.get((e.get("producto"), e.get("keyword")))
        if row is None:
            continue  # la keyword ya no aparece (pausada, eliminada...) — no se puede medir

        delta_clicks = row.clicks - (e.get("clics_base") or 0)
        if delta_clicks < min_new_clicks:
            continue  # todavía sin señal suficiente, se reintenta otro día

        delta_cost = row.cost - e["coste_base"]
        delta_sales = row.sales - e["ventas_base"]
        delta_acos = round(delta_cost / delta_sales, 3) if delta_sales > 0 else None

        if delta_sales > 0 and delta_acos is not None and delta_acos <= 0.35:
            evaluacion = "mejora"
        else:
            evaluacion = "empeora"

        e["resultado_siguiente"] = {
            "clics": delta_clicks,
            "ventas": round(delta_sales, 2),
            "acos_real": delta_acos,
            "evaluacion": evaluacion,
        }
        resolved += 1

    if resolved:
        _rewrite_all(entries)
    return resolved
