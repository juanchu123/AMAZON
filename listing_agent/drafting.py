"""
drafting.py
-----------
Redacción de la propuesta. Dos caminos, mismo contrato:

  - Cowork (por ahora, Juan no tiene ANTHROPIC_API_KEY): el agente escribe un
    "brief" en Markdown con TODO lo que hace falta saber (listing actual,
    límites, keywords, indexación, memoria de cambios anteriores, reglas) y
    el formato JSON exacto de la respuesta. Cowork lo lee, redacta y guarda
    propuesta_*.json; después se valida con `python main.py validar`.
  - API de Claude (cuando haya key): el mismo brief se manda a la API y la
    respuesta se guarda igual.

En los dos casos la propuesta pasa por safety.validate_proposal() antes de
convertirse en nada publicable. El redactor no puede saltarse esa barrera.
"""

import json
import os
import re
from datetime import date
from pathlib import Path

from audit import AuditResult
from limits import Limits
from listing_state import ListingState

FORMATO = {
    "titulo": "un texto",
    "item_highlights": "un texto",
    "bullets": "una lista de exactamente N textos",
    "descripcion": "un texto plano (sin HTML)",
    "backend": "un texto en minúsculas, palabras separadas solo por espacios",
}


def build_brief(state: ListingState, limits: Limits, audit: AuditResult, research_rows: list[dict],
                indexation_rows: list[dict], memory_summary: dict, backend_candidate: str,
                marca_propia: str, keyword_principal: str | None, policy_lists: dict,
                hoy: date | None = None) -> str:
    hoy = hoy or date.today()
    campo = audit.siguiente_campo
    lim = limits.for_field(campo)
    formato = FORMATO[campo].replace("N", str(limits.bullets_num))
    top_kw = research_rows[:25]

    def kw_line(k):
        estado = "cubierta" if k["cubierta"] else f"FALTA ({' '.join(k['faltan'])})"
        return f"| {k['keyword']} | {k['clics']} | {k['compras']} | {estado} |"

    def idx_line(r):
        return f"| {r['keyword']} | {r['estado']} | {r['detalle']} |"

    bullets_actuales = "\n".join(f"{i}. {b}" for i, b in enumerate(state.bullets, 1)) or "(ninguno)"
    plantilla = {
        "asin": state.asin,
        "campo": campo,
        "valor_nuevo": ["…"] * limits.bullets_num if campo == "bullets" else "…",
        "es_correccion": audit.es_correccion,
        "motivo": "por qué este cambio, con datos",
        "riesgo": "qué puede salir mal (CTR, conversión, indexación de algún término)",
        "metrica_a_vigilar": "p. ej. conversión (unidades/sesión) y sesiones a 7–14 días",
        "keywords_objetivo": ["keywords que este cambio quiere indexar o reforzar"],
    }

    return f"""# Brief de redacción — {state.asin} — {hoy.isoformat()}

Eres el redactor del agente de página de producto de FreshFinder (Amazon.es, FBA, sin Brand Registry).
Tu tarea: redactar UNA propuesta para el campo **{campo}**. Un cambio cada vez; no toques otros campos.

**Por qué este campo:** {audit.motivo_siguiente}
{"**Es una corrección de error** (se salta la espera entre cambios)." if audit.es_correccion else ""}

## Cómo entregar
Guarda un archivo JSON (solo JSON, sin texto alrededor) en la carpeta `trabajo/` llamado
`propuesta_{state.asin}_{hoy:%Y%m%d}.json` con esta forma. `valor_nuevo` es {formato}:

```json
{json.dumps(plantilla, ensure_ascii=False, indent=2)}
```

Después ejecuta `python main.py validar trabajo/propuesta_{state.asin}_{hoy:%Y%m%d}.json`.
Si el validador rechaza la propuesta, corrige lo que diga y vuelve a validar. No intentes saltarte el validador.

## Límite del campo
- {campo}: {lim.describe()}
- Si un límite no está confirmado, quédate cómodamente por debajo.

## Reglas obligatorias
- Prohibido: marcas ajenas ({", ".join(policy_lists["competidoras"]) or "ninguna configurada"}), ASIN, URLs, emails,
  teléfonos, lenguaje promocional ("oferta", "mejor", "nº1", "gratis", "barato"…), emojis y símbolos decorativos.
- Marcas de dispositivos ({", ".join(policy_lists["dispositivos"]) or "ninguna"}) solo como compatibilidad real en
  texto visible ("compatible con…"); NUNCA en backend.
- Nada de afirmaciones médicas, de seguridad o de conformidad (certificado, homologado, seguro para niños, CE…)
  salvo estas, confirmadas por legal: {", ".join(policy_lists["claims"]) or "ninguna"}.
- Título: Marca + tipo de producto con la keyword principal + atributo diferenciador + formato/cantidad.
  Keyword principal{f" ('{keyword_principal}')" if keyword_principal else ""} en las primeras palabras (móvil). Sin mayúsculas completas,
  sin repetir la marca, ninguna palabra más de dos veces.
- Item Highlights: material, uso, compatibilidad, contenido. Sin repetir el título.
- Bullets: {limits.bullets_num}, cada uno empieza con el BENEFICIO en mayúsculas y sigue con la prueba o el dato.
  Orden: beneficio principal → objeción habitual → diferenciador → para quién/caso de uso → contenido del pack/garantía.
  Escribe como respuestas a preguntas reales (Rufus/COSMO): para quién, qué problema, cuándo, compatibilidad.
- Backend: sinónimos, variantes y términos de cola larga que NO estén ya en el texto visible. Sin comas,
  sin palabras vacías, sin repetir, sin tu marca. Un término basta una vez.
- No inventes datos del producto (medidas, materiales, compatibilidades). Si no están en el listing actual, no los pongas.

## Listing actual
- **Título** ({len(state.titulo)} car.): {state.titulo}
- **Item Highlights**: {state.item_highlights if state.item_highlights is not None else "(campo no disponible en el esquema)"}
- **Marca**: {state.marca or marca_propia}
- **Bullets**:
{bullets_actuales}
- **Descripción**: {state.descripcion or "(vacía)"}
- **Backend** ({len(state.backend.encode("utf-8"))} bytes): {state.backend or "(vacío)"}

## Métricas (últimos días, informe de negocio)
{json.dumps(state.metricas, ensure_ascii=False) if state.metricas else "No disponibles en esta ejecución."}

## Keywords (Ads + histórico + semillas), ordenadas por relevancia
| Keyword | Clics | Compras | En el listing |
|---|---|---|---|
{chr(10).join(kw_line(k) for k in top_kw) or "| (sin datos) | | | |"}

Backend candidato calculado sin IA (palabras de keywords que convierten y que no están en el texto visible):
`{backend_candidate or "(vacío)"}`

## Indexación (aproximada, catálogo SP-API)
| Keyword | Estado | Detalle |
|---|---|---|
{chr(10).join(idx_line(r) for r in indexation_rows) or "| (no comprobada) | | |"}

## Memoria: cambios anteriores en este ASIN y cómo fueron
Trátalo como señal fuerte. No repitas lo que empeoró; apóyate en lo que funcionó.

```json
{json.dumps(memory_summary, ensure_ascii=False, indent=2)}
```
"""


def write_brief(trabajo_dir: Path, asin: str, text: str, hoy: date | None = None) -> Path:
    hoy = hoy or date.today()
    path = trabajo_dir / f"brief_{asin}_{hoy:%Y%m%d}.md"
    path.write_text(text, encoding="utf-8")
    return path


def api_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def draft_with_api(brief: str, model: str) -> dict:
    """Manda el brief a la API de Claude y devuelve la propuesta como dict.
    Solo se usa si hay ANTHROPIC_API_KEY; si no, el brief lo redacta Cowork."""
    import anthropic

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        output_config={"effort": "high"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=(
            "Eres un redactor experto en listings de Amazon.es. Respondes ÚNICAMENTE con el objeto JSON "
            "que pide el brief, sin texto antes ni después y sin bloque de código."
        ),
        messages=[{"role": "user", "content": brief}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("La API rechazó la petición; redacta con Cowork usando el brief.")
    text = "".join(b.text for b in response.content if b.type == "text")
    return parse_proposal_text(text)


def parse_proposal_text(text: str) -> dict:
    """Extrae el primer objeto JSON de un texto (tolera ```json ... ```)."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("La respuesta no contiene un objeto JSON")
    return json.loads(m.group(0))
