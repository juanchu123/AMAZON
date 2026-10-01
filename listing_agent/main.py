"""
main.py
-------
Agente de página de producto (listing) de FreshFinder.

    python main.py auditar                 # semanal (cron): diagnóstico + brief/paquete + email
    python main.py validar trabajo/propuesta_X.json [--preview-amazon]
    python main.py aplicado <change_id> [--fecha AAAA-MM-DD]
    python main.py descartar <change_id> [--motivo "..."]
    python main.py revertir <change_id>
    python main.py resultado <change_id> --veredicto mejora|empeora|neutro [...]   # lo usa el agente evaluador
    python main.py memoria [--asin B0...]

Flujo (sección 6 del documento): diagnóstico → propuesta → vista previa
(antes/después) → "sí" de Juan → Juan publica → verificación → medición.
Este agente NUNCA publica en Amazon: la SP-API se usa solo para leer
(y para validar sin publicar con --preview-amazon).
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from audit import run_audit
from config import Config, load_config, sp_api_credentials
from drafting import api_available, build_brief, draft_with_api, write_brief
from emailer import send_report
from indexation import check_keywords, indexation_rate
from keywords import build_backend_candidate, research
from limits import ATTR, limits_from_schema
from listing_state import ListingState, _canon, build_state, diff_states
from memory import Memory
from report import render_package, render_weekly
from safety import ContentPolicy, validate_proposal
from sp_api import SPAPIClient, SPAPIError, asin_metrics_from_report
from textutil import tokens


def make_client(cfg: Config) -> SPAPIClient:
    return SPAPIClient(**sp_api_credentials(), endpoint=cfg.endpoint,
                       marketplace_id=cfg.marketplace_id, idioma=cfg.idioma)


def make_policy(cfg: Config) -> ContentPolicy:
    return ContentPolicy(
        marca_propia=cfg.marca_propia,
        marcas_competidoras=cfg.marcas_competidoras,
        marcas_de_dispositivos=cfg.marcas_de_dispositivos,
        claims_confirmados=cfg.claims_confirmados_por_legal,
        margen_bytes_backend=cfg.reglas["margen_bytes_backend"],
    )


# ------------------------------------------------------------------ snapshots
def _snap_dir(cfg: Config, asin: str) -> Path:
    d = cfg.logs_dir / "snapshots" / asin
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_snapshot(cfg: Config, state: ListingState, hoy: date) -> None:
    (_snap_dir(cfg, state.asin) / f"{hoy.isoformat()}.json").write_text(
        json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def last_snapshot(cfg: Config, asin: str, before: date | None = None) -> ListingState | None:
    files = sorted(_snap_dir(cfg, asin).glob("*.json"))
    if before:
        files = [f for f in files if f.stem < before.isoformat()]
    if not files:
        return None
    return ListingState.from_dict(json.loads(files[-1].read_text(encoding="utf-8")))


# -------------------------------------------------------------- leer listing
def read_listing(cfg: Config, client, asin: str, avisos: list[str]):
    acfg = cfg.asin_cfg(asin)
    sku = acfg.sku or client.find_sku_for_asin(asin)
    if not sku:
        raise SPAPIError(f"No se encuentra ningún SKU de este vendedor para {asin}")
    listing = client.get_listing(sku)
    catalog = inventory = schema = None
    try:
        catalog = client.get_catalog_item(asin)
    except SPAPIError as e:
        avisos.append(f"{asin}: no se pudo leer el catálogo (imágenes): {e}")
    product_type = next((s.get("productType") for s in listing.get("summaries") or []
                         if s.get("marketplaceId") == cfg.marketplace_id), None)
    if product_type:
        try:
            schema = client.get_product_type_schema(product_type)
        except (SPAPIError, Exception) as e:  # noqa: BLE001 — el esquema es opcional
            avisos.append(f"{asin}: sin esquema de {product_type}; se usan los límites por defecto ({e})")
    limits = limits_from_schema(schema)
    try:
        inventory = client.fba_inventory(sku)
    except SPAPIError as e:
        avisos.append(f"{asin}: no se pudo leer el inventario FBA: {e}")
    state = build_state(asin, sku, cfg.marketplace_id, cfg.idioma, listing, catalog, inventory,
                        limits.highlights_attr)
    return state, limits


def fetch_metrics(cfg: Config, client, hoy: date, avisos: list[str]) -> dict:
    dias = cfg.reglas["ventana_metricas_dias"]
    end = datetime.combine(hoy - timedelta(days=2), datetime.min.time())  # los datos llegan con retraso
    start = end - timedelta(days=dias - 1)
    try:
        rep = client.sales_and_traffic(start, end)
    except SPAPIError as e:
        avisos.append(f"No se pudo descargar el informe de negocio (sesiones/conversión): {e}")
        return {}
    out = {}
    for a in cfg.asins:
        m = asin_metrics_from_report(rep, a.asin)
        if m:
            m["periodo"] = f"{start:%Y-%m-%d} a {end:%Y-%m-%d}"
            out[a.asin] = m
    return out


# -------------------------------------------------------------------- auditar
def audit_asin(cfg: Config, client, mem: Memory, asin: str, metrics: dict, hoy: date,
               comprobar_indexacion: bool, avisos: list[str], adjuntos: list[Path]) -> dict:
    acfg = cfg.asin_cfg(asin)
    state, limits = read_listing(cfg, client, asin, avisos)
    state.metricas = metrics.get(asin)
    prev = last_snapshot(cfg, asin, before=hoy)
    save_snapshot(cfg, state, hoy)

    # 1) ¿Juan ya ha publicado algo que estaba propuesto?
    aplicados_detectados = []
    for c in mem.pending_proposals(asin):
        if _canon(getattr(state, c["campo"])) == _canon(c["valor_despues"]):
            base = (prev.metricas if prev and prev.metricas else state.metricas)
            mem.mark_applied(c["id"], hoy, detectado_automaticamente=True, metricas_base=base)
            aplicados_detectados.append(c["id"])
            if acfg.tiene_campanas_activas:
                mem.notify_ads(asin, "cambio_aplicado", f"{c['campo']} publicado (detectado {hoy})",
                               c["campo"], c["id"])

    # 2) ¿Ha cambiado algo que no ha hecho este agente? (p. ej. la IA de Amazon reescribiendo el título)
    no_registrados = {}
    if prev:
        explicados = {_json(_canon(c["valor_despues"])) for c in mem.applied(asin)}
        for campo, (a, b) in diff_states(prev, state).items():
            if _json(_canon(b)) not in explicados:
                no_registrados[campo] = (a, b)
                if campo == "titulo" and acfg.tiene_campanas_activas:
                    mem.notify_ads(asin, "titulo_cambiado_fuera_del_agente",
                                   f"El título ha cambiado sin registro: «{b}»", campo)

    # 3) Keywords e indexación
    rows = research(state, cfg.csv_ads, cfg.historico_json, acfg.keywords_semilla)
    idx_rows = []
    if comprobar_indexacion:
        objetivo = []
        for c in mem.applied(asin):  # tras un cambio: comprobar sus keywords a las 24–72 h y hasta 14 días
            if (hoy - date.fromisoformat(c["fecha_aplicado"])).days <= 14:
                objetivo += c.get("keywords_objetivo") or []
        objetivo += [r["keyword"] for r in rows]
        seen, kws = set(), []
        for k in objetivo:
            if k.lower() not in seen:
                seen.add(k.lower())
                kws.append(k)
        kws = kws[: cfg.indexacion["max_keywords_por_ejecucion"]]
        idx_rows = check_keywords(client, asin, kws, cfg.indexacion["paginas_por_busqueda"], hoy)
        mem.record_indexation(idx_rows)
    rate = indexation_rate(idx_rows)

    audit = run_audit(state, limits, acfg.keyword_principal, rows, rate, brand_registry=False)
    resumen = mem.summary(asin)

    # 4) Siguiente paso
    siguiente = _next_step(cfg, client, mem, state, limits, audit, rows, idx_rows, resumen, hoy, adjuntos)
    return {
        "state": state, "audit": audit, "indexacion": idx_rows, "memoria": resumen,
        "cambios_no_registrados": no_registrados, "aplicados_detectados": aplicados_detectados,
        "siguiente_paso": siguiente,
    }


def _json(v) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def _next_step(cfg, client, mem: Memory, state, limits, audit, rows, idx_rows, resumen, hoy, adjuntos) -> str:
    aplicados = mem.applied(state.asin)
    if aplicados:
        ult = aplicados[-1]
        out = mem.latest_outcome(ult["id"])
        if out and out["veredicto"] == "empeora":
            return (f"El último cambio (`{ult['id']}`, {ult['campo']}) ha EMPEORADO según el evaluador. "
                    f"Recomendación: `python main.py revertir {ult['id']}` (genera el paquete para volver a lo anterior).")
    if audit.siguiente_campo is None:
        if audit.alertas:
            return "Hay alertas que resolver antes de tocar contenido (ver arriba)."
        return "Nada prioritario que cambiar esta semana. Mantener y seguir midiendo."
    bloqueos = mem.check_change_allowed(state.asin, audit.siguiente_campo, audit.es_correccion, cfg.reglas, hoy)
    if bloqueos:
        return (f"Próximo campo a trabajar: **{audit.siguiente_campo}** ({audit.motivo_siguiente}), "
                "pero todavía no toca:\n" + "\n".join(f"- {b}" for b in bloqueos))

    excluir = {t for b in cfg.marcas_competidoras + cfg.marcas_de_dispositivos + [cfg.marca_propia]
               for t in tokens(b, drop_stopwords=False)}
    tope = (limits.backend.max_bytes or 249) - cfg.reglas["margen_bytes_backend"]
    candidato = build_backend_candidate([r for r in rows if r["compras"] > 0 or r["semilla"]] or rows,
                                        state, tope, excluir)
    brief = build_brief(
        state, limits, audit, rows, idx_rows, resumen, candidato, cfg.marca_propia,
        cfg.asin_cfg(state.asin).keyword_principal,
        {"competidoras": cfg.marcas_competidoras, "dispositivos": cfg.marcas_de_dispositivos,
         "claims": cfg.claims_confirmados_por_legal},
        hoy,
    )
    brief_path = write_brief(cfg.trabajo_dir, state.asin, brief, hoy)
    adjuntos.append(brief_path)

    usar_api = cfg.redaccion_modo == "api" or (cfg.redaccion_modo == "auto" and api_available())
    if usar_api:
        try:
            propuesta = draft_with_api(brief, cfg.redaccion_modelo)
            p_path = cfg.trabajo_dir / f"propuesta_{state.asin}_{hoy:%Y%m%d}.json"
            p_path.write_text(json.dumps(propuesta, ensure_ascii=False, indent=2), encoding="utf-8")
            code, msg, pkg = validate_and_package(cfg, client, mem, propuesta, "api-claude",
                                                  preview_amazon=True, hoy=hoy)
            if pkg:
                adjuntos.append(pkg)
            return msg
        except Exception as e:  # noqa: BLE001 — si la API falla, se cae al camino de Cowork
            return (f"Brief listo en `{brief_path.name}`, pero la redacción por API falló ({e}). "
                    "Redáctalo con Cowork (ver COWORK.md).")
    return (f"Campo a trabajar: **{audit.siguiente_campo}** — {audit.motivo_siguiente}\n\n"
            f"Brief listo en `trabajo/{brief_path.name}` (adjunto). Ábrelo con Cowork siguiendo COWORK.md; "
            "Cowork guardará la propuesta y la validará con `python main.py validar ...`.")


def cmd_auditar(cfg: Config, client, asins: list[str] | None, enviar_email: bool,
                comprobar_indexacion: bool, hoy: date | None = None) -> Path:
    hoy = hoy or date.today()
    mem = Memory(cfg.logs_dir)
    avisos, secciones, adjuntos = [], [], []
    metrics = fetch_metrics(cfg, client, hoy, avisos)
    for a in (asins or [x.asin for x in cfg.asins]):
        try:
            secciones.append(audit_asin(cfg, client, mem, a, metrics, hoy, comprobar_indexacion, avisos, adjuntos))
        except SPAPIError as e:
            avisos.append(f"{a}: no se pudo auditar: {e}")
    md = render_weekly(hoy, secciones, avisos)
    path = cfg.informes_dir / f"informe_{hoy:%Y%m%d}.md"
    path.write_text(md, encoding="utf-8")
    print(md)
    if enviar_email:
        n_alertas = sum(len(s["audit"].alertas) for s in secciones) + len(avisos)
        send_report(f"[FreshFinder] Página de producto — {hoy:%d/%m/%Y}"
                    + (f" — {n_alertas} alertas" if n_alertas else ""), md, adjuntos)
    return path


# -------------------------------------------------------------------- validar
def build_patches(campo: str, valor, limits, cfg: Config) -> list[dict] | None:
    attr = limits.highlights_attr if campo == "item_highlights" else ATTR.get(campo)
    if not attr:
        return None
    vals = valor if isinstance(valor, list) else [valor]
    return [{
        "op": "replace",
        "path": f"/attributes/{attr}",
        "value": [{"value": v, "language_tag": cfg.idioma, "marketplace_id": cfg.marketplace_id} for v in vals],
    }]


def validate_and_package(cfg: Config, client, mem: Memory, proposal: dict, redactado_por: str,
                         preview_amazon: bool, hoy: date | None = None, enviar_email: bool = False):
    """Devuelve (código, mensaje, ruta_paquete|None). Código 0 = paquete listo."""
    hoy = hoy or date.today()
    asin = proposal.get("asin")
    try:
        acfg = cfg.asin_cfg(asin)
    except KeyError as e:
        return 1, str(e), None
    avisos: list[str] = []
    state, limits = read_listing(cfg, client, asin, avisos)  # siempre contra el listing EN VIVO
    snap = last_snapshot(cfg, asin)
    state.metricas = snap.metricas if snap else None

    bloqueos = mem.check_change_allowed(
        asin, proposal.get("campo"),
        bool(proposal.get("es_correccion") or proposal.get("revierte_a")), cfg.reglas, hoy)
    if bloqueos:
        return 1, "No se puede proponer ahora:\n" + "\n".join(f"- {b}" for b in bloqueos), None

    result = validate_proposal(proposal, state, limits, make_policy(cfg))
    if not result.ok:
        return 1, ("Propuesta RECHAZADA por el validador:\n" + "\n".join(f"- {e}" for e in result.errores)
                   + ("\nAvisos:\n" + "\n".join(f"- {a}" for a in result.avisos) if result.avisos else "")), None

    preview_issues = None
    if preview_amazon:
        patches = build_patches(result.campo, result.valor_final, limits, cfg)
        if patches is None or not state.product_type:
            avisos.append("No se pudo pedir VALIDATION_PREVIEW (campo sin atributo conocido o sin tipo de producto).")
        else:
            try:
                resp = client.validate_patch_preview(state.sku, state.product_type, patches)
                preview_issues = resp.get("issues") or []
                errores = [i for i in preview_issues if i.get("severity") == "ERROR"]
                if errores:
                    return 1, "Amazon rechaza la propuesta en la validación previa:\n" + "\n".join(
                        f"- {i.get('message')}" for i in errores), None
            except SPAPIError as e:
                avisos.append(f"VALIDATION_PREVIEW no disponible: {e}")

    ult_idx = mem.indexation_history(asin)
    if ult_idx:
        ult_fecha = ult_idx[-1]["fecha"]
        ult_idx = {r["keyword"]: r["estado"] for r in ult_idx if r["fecha"] == ult_fecha}
    change = mem.record_proposal(
        asin=asin, sku=state.sku, marketplace_id=cfg.marketplace_id, campo=result.campo,
        valor_antes=getattr(state, result.campo), valor_despues=result.valor_final,
        antes_completo=state.text_fields(), motivo=proposal.get("motivo", ""),
        riesgo=proposal.get("riesgo", ""), metrica_a_vigilar=proposal.get("metrica_a_vigilar", ""),
        keywords_objetivo=proposal.get("keywords_objetivo") or [],
        es_correccion=bool(proposal.get("es_correccion")), metricas_base=state.metricas,
        indexacion_base=ult_idx or None, redactado_por=redactado_por,
        revierte_a=proposal.get("revierte_a"), hoy=hoy,
    )
    if acfg.tiene_campanas_activas:
        mem.notify_ads(asin, "cambio_previsto",
                       f"Juan va a publicar un cambio de {result.campo}. Puede mover CTR/conversión.",
                       result.campo, change["id"])
    result.avisos.extend(avisos)
    pkg = cfg.trabajo_dir / f"paquete_{change['id']}.md"
    pkg.write_text(render_package(change, result, limits, preview_issues, acfg.tiene_campanas_activas),
                   encoding="utf-8")
    msg = f"Paquete listo para publicar: `trabajo/{pkg.name}` (cambio `{change['id']}`)."
    if enviar_email:
        send_report(f"[FreshFinder] Listo para publicar — {asin} — {result.campo}",
                    pkg.read_text(encoding="utf-8"), [pkg])
    return 0, msg, pkg


# ------------------------------------------------------------------------ CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Agente de página de producto — FreshFinder")
    ap.add_argument("--config", help="ruta a config.json (por defecto, junto a main.py)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("auditar", help="diagnóstico semanal + brief/paquete + email")
    a.add_argument("--asin", action="append")
    a.add_argument("--sin-email", action="store_true")
    a.add_argument("--sin-indexacion", action="store_true")

    v = sub.add_parser("validar", help="valida una propuesta y genera el paquete listo para publicar")
    v.add_argument("propuesta")
    v.add_argument("--preview-amazon", action="store_true", help="validar también con Amazon sin publicar")
    v.add_argument("--redactado-por", default="cowork")
    v.add_argument("--sin-email", action="store_true")

    p = sub.add_parser("aplicado", help="marca un cambio como publicado")
    p.add_argument("change_id")
    p.add_argument("--fecha")

    d = sub.add_parser("descartar", help="descarta un cambio propuesto")
    d.add_argument("change_id")
    d.add_argument("--motivo", default="")

    r = sub.add_parser("revertir", help="genera el paquete para volver al estado anterior a un cambio")
    r.add_argument("change_id")
    r.add_argument("--sin-email", action="store_true")

    o = sub.add_parser("resultado", help="registra cómo fue un cambio (lo usa el agente evaluador)")
    o.add_argument("change_id")
    o.add_argument("--veredicto", required=True, choices=["mejora", "empeora", "neutro"])
    o.add_argument("--ventana", default="", help="p. ej. 7-14d o 4-6sem")
    o.add_argument("--metricas", default="{}", help="JSON con las métricas después del cambio")
    o.add_argument("--notas", default="")
    o.add_argument("--agente", default="")

    m = sub.add_parser("memoria", help="muestra la memoria de cambios")
    m.add_argument("--asin")

    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    mem = Memory(cfg.logs_dir)

    if args.cmd == "auditar":
        cmd_auditar(cfg, make_client(cfg), args.asin, not args.sin_email, not args.sin_indexacion)
        return 0
    if args.cmd == "validar":
        proposal = json.loads(Path(args.propuesta).read_text(encoding="utf-8"))
        code, msg, _ = validate_and_package(cfg, make_client(cfg), mem, proposal, args.redactado_por,
                                            args.preview_amazon, enviar_email=not args.sin_email)
        print(msg)
        return code
    if args.cmd == "aplicado":
        c = mem.get_change(args.change_id)
        snap = last_snapshot(cfg, c["asin"])
        base = c.get("metricas_base") or (snap.metricas if snap else None)
        fecha = date.fromisoformat(args.fecha) if args.fecha else None
        mem.mark_applied(args.change_id, fecha, metricas_base=base)
        if cfg.asin_cfg(c["asin"]).tiene_campanas_activas:
            mem.notify_ads(c["asin"], "cambio_aplicado", f"{c['campo']} publicado", c["campo"], c["id"])
        print(f"{args.change_id} marcado como aplicado.")
        return 0
    if args.cmd == "descartar":
        mem.mark_discarded(args.change_id, args.motivo)
        print(f"{args.change_id} descartado.")
        return 0
    if args.cmd == "revertir":
        c = mem.get_change(args.change_id)
        if c["estado"] != "aplicado":
            print(f"{args.change_id} no está aplicado; no hay nada que revertir.")
            return 1
        out = mem.latest_outcome(c["id"])
        proposal = {
            "asin": c["asin"], "campo": c["campo"], "valor_nuevo": c["valor_antes"],
            "revierte_a": c["id"], "es_correccion": False,
            "motivo": f"Revertir {c['id']} (veredicto: {out['veredicto'] if out else 'sin evaluar'}).",
            "riesgo": "Volver al texto anterior; se pierde lo que el cambio pudiera haber aportado.",
            "metrica_a_vigilar": c.get("metrica_a_vigilar") or "conversión y sesiones",
            "keywords_objetivo": [],
        }
        code, msg, _ = validate_and_package(cfg, make_client(cfg), mem, proposal, "reversion",
                                            preview_amazon=False, enviar_email=not args.sin_email)
        print(msg)
        return code
    if args.cmd == "resultado":
        e = mem.record_outcome(args.change_id, args.veredicto, ventana=args.ventana,
                               metricas_despues=json.loads(args.metricas), notas=args.notas, agente=args.agente)
        print(json.dumps(e, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "memoria":
        asins = [args.asin] if args.asin else [x.asin for x in cfg.asins]
        print(json.dumps({x: mem.summary(x) for x in asins}, ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyError, ValueError, FileNotFoundError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
