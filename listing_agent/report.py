"""
report.py
---------
Lo que lee Juan: el informe semanal y el "paquete" listo para publicar
(antes/después con recuentos, dónde pegarlo y qué vigilar).
"""

from datetime import date

from audit import AuditResult
from limits import Limits
from listing_state import ListingState
from safety import ValidationResult
from textutil import utf8_len

ICON = {"ok": "✅", "fallo": "❌", "desconocido": "❓", "no aplica": "—"}

DONDE_PEGAR = {
    "titulo": "Seller Central → Inventario → Administrar todo el inventario → Editar → «Nombre del producto».",
    "item_highlights": "Seller Central → Inventario → Administrar todo el inventario → Editar → «Item Highlights» "
                       "(o desde «Ver mejoras»).",
    "bullets": "Seller Central → Inventario → Editar → pestaña Descripción → «Viñetas» (una por casilla, en este orden).",
    "descripcion": "Seller Central → Inventario → Editar → pestaña Descripción → «Descripción del producto».",
    "backend": "Seller Central → Inventario → Editar → pestaña Palabras clave → «Términos de búsqueda genéricos». "
               "Pega el texto tal cual, sin comas.",
}


def _fmt_val(v) -> str:
    if isinstance(v, list):
        return "\n".join(f"{i}. {x}" for i, x in enumerate(v, 1)) or "(vacío)"
    return v if v else "(vacío)"


def render_package(change: dict, result: ValidationResult, limits: Limits,
                   preview_issues: list[dict] | None, tiene_campanas: bool) -> str:
    campo = change["campo"]
    lim = limits.for_field(campo)
    rec = "\n".join(f"- {k}: {v}" for k, v in result.recuento.items())
    avisos = "\n".join(f"- {a}" for a in result.avisos) or "- Ninguno"
    if preview_issues is None:
        preview = "No se ha pedido validación a Amazon (usa `--preview-amazon`)."
    elif not preview_issues:
        preview = "Amazon (VALIDATION_PREVIEW) no devuelve ningún problema. **Nada se ha publicado.**"
    else:
        preview = "Amazon (VALIDATION_PREVIEW) devuelve:\n" + "\n".join(
            f"- [{i.get('severity')}] {i.get('message')}" for i in preview_issues)
    despues = change["valor_despues"]
    copiar = "\n\n".join(despues) if isinstance(despues, list) else despues
    ads = (
        "⚠️ Este ASIN tiene campañas activas: se ha dejado un aviso para el agente de Ads "
        "(`listing_events_for_ads.jsonl`). Un cambio de título puede mover CTR y conversión."
        if tiene_campanas else "Este ASIN no tiene campañas activas según config.json."
    )
    return f"""# Paquete listo para publicar — {change['asin']} — {campo}

**ID del cambio:** `{change['id']}`  ·  **Propuesto:** {change['fecha_propuesta']}  ·  **Redactado por:** {change['redactado_por']}
{"**Corrección de error**" if change.get("es_correccion") else ""}{" · **Revierte** " + change["revierte_a"] if change.get("revierte_a") else ""}

## Antes
{_fmt_val(change['valor_antes'])}

## Después (copiar y pegar)
```
{copiar}
```

## Recuento
{rec}
- Límite aplicado: {lim.describe()}

## Avisos del validador
{avisos}

## Validación en Amazon
{preview}

## Por qué
- **Motivo:** {change['motivo']}
- **Riesgo:** {change['riesgo']}
- **Métrica a vigilar:** {change['metrica_a_vigilar']}
- **Keywords objetivo:** {", ".join(change.get('keywords_objetivo') or []) or "—"}

## Dónde pegarlo
{DONDE_PEGAR[campo]}

## Agente de Ads
{ads}

## Después de publicarlo
1. Ejecuta `python main.py aplicado {change['id']}` (o el agente lo detectará solo en la próxima auditoría).
2. A las 24–72 h el agente comprobará la indexación de las keywords objetivo.
3. A los 7–14 días el agente evaluador registra el resultado:
   `python main.py resultado {change['id']} --veredicto mejora|empeora|neutro`.
4. Si hay que deshacerlo: `python main.py revertir {change['id']}` (el estado anterior está guardado).
"""


def render_weekly(hoy: date, secciones: list[dict], errores_globales: list[str]) -> str:
    out = [f"# Informe semanal de página de producto — {hoy.isoformat()}\n"]
    if errores_globales:
        out.append("## ⚠️ Problemas de ejecución\n" + "\n".join(f"- {e}" for e in errores_globales) + "\n")
    for s in secciones:
        out.append(_render_asin(s))
    return "\n".join(out)


def _render_asin(s: dict) -> str:
    state: ListingState = s["state"]
    audit: AuditResult = s["audit"]
    lines = [f"## {state.asin} (SKU {state.sku})\n"]
    if audit.alertas:
        lines.append("### 🚨 Alertas\n" + "\n".join(f"- {a}" for a in audit.alertas) + "\n")
    if s.get("cambios_no_registrados"):
        lines.append("### 🔎 Cambios en el listing que no ha hecho este agente")
        for campo, (a, b) in s["cambios_no_registrados"].items():
            lines.append(f"- **{campo}**\n  - antes: {_short(a)}\n  - ahora: {_short(b)}")
        lines.append("Puede ser la IA de Amazon reescribiendo el título o una edición manual. Revísalo.\n")
    if s.get("aplicados_detectados"):
        lines.append("### ✔️ Cambios propuestos que ya están publicados")
        lines += [f"- `{c}`" for c in s["aplicados_detectados"]]
        lines.append("")
    m = state.metricas or {}
    lines.append(
        f"**Puntuación de calidad:** {audit.puntuacion if audit.puntuacion is not None else '—'} / 100  ·  "
        f"**Sesiones:** {m.get('sesiones', '—')}  ·  **Conversión:** {m.get('conversion_pct', '—')} %  ·  "
        f"**Buy Box:** {m.get('buy_box_pct', '—')} %  ·  **Stock:** {state.stock_disponible if state.stock_disponible is not None else '—'}\n"
    )
    lines.append("### Checklist\n| | Punto | Detalle |\n|---|---|---|")
    lines += [f"| {ICON[c.estado]} | {c.nombre} | {c.detalle} |" for c in audit.checks]
    lines.append("")
    if s.get("indexacion"):
        lines.append("### Indexación (aproximada vía catálogo; confirma a mano los «no encontrado»)")
        lines.append("| Keyword | Estado | Comprobar |\n|---|---|---|")
        lines += [f"| {r['keyword']} | {r['estado']} | {r['comprobar_a_mano']} |" for r in s["indexacion"]]
        lines.append("")
    lines.append("### Siguiente paso")
    lines.append(s["siguiente_paso"])
    lines.append("")
    mem = s.get("memoria") or {}
    if mem.get("historial"):
        lines.append("### Memoria de cambios")
        lines.append("| Cambio | Campo | Estado | Aplicado | Veredicto |\n|---|---|---|---|---|")
        lines += [f"| `{h['id']}` | {h['campo']} | {h['estado']} | {h['fecha_aplicado'] or '—'} | {h['veredicto']} |"
                  for h in mem["historial"]]
        lines.append("")
    return "\n".join(lines)


def _short(v, n: int = 160) -> str:
    t = " | ".join(v) if isinstance(v, list) else (v or "(vacío)")
    return t if len(t) <= n else t[: n - 1] + "…"


def bytes_of(v) -> int:
    return utf8_len(" ".join(v) if isinstance(v, list) else (v or ""))
