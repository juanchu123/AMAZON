"""
memory.py
---------
La memoria del agente: qué se ha cambiado en cada página de producto y cómo
ha ido. Es lo que consulta ANTES de proponer nada.

Tres archivos JSON Lines en la carpeta de logs (ligeros, legibles, sin base
de datos, igual que el agente de Ads):

  listing_changes.jsonl   — lo escribe ESTE agente. Un cambio por línea:
                            antes, después, motivo, métricas de partida y
                            estado (propuesto / aplicado / descartado).
  listing_outcomes.jsonl  — lo escribe EL OTRO AGENTE (el que mide). Una
                            evaluación por línea, enlazada por change_id:
                            métricas después y veredicto
                            ("mejora" / "empeora" / "neutro").
  listing_events_for_ads.jsonl — avisos para el agente de Ads (cambios
                            previstos o aplicados en un ASIN con campañas).

Igual que en Ads: el modelo no "recuerda" nada entre ejecuciones. Lo que
hace que el sistema aprenda es que este resumen se le pasa cada vez en el
brief. Si dejara de pasarse, lo aprendido desaparecería.
"""

import json
import os
import secrets
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

VEREDICTOS = ("mejora", "empeora", "neutro")
ESTADOS = ("propuesto", "aplicado", "descartado")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"{path.name} línea {n} no es JSON válido: {e}") from e
    return out


def _append_jsonl(path: Path, entry: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _write_jsonl_atomic(path: Path, entries: list[dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def _d(iso: str | None) -> date | None:
    return date.fromisoformat(iso[:10]) if iso else None


@dataclass
class Memory:
    logs_dir: Path

    @property
    def changes_file(self) -> Path:
        return self.logs_dir / "listing_changes.jsonl"

    @property
    def outcomes_file(self) -> Path:
        return self.logs_dir / "listing_outcomes.jsonl"

    @property
    def ads_events_file(self) -> Path:
        return self.logs_dir / "listing_events_for_ads.jsonl"

    @property
    def indexation_file(self) -> Path:
        return self.logs_dir / "listing_indexation.jsonl"

    # --------------------------------------------------------------- lectura
    def changes(self, asin: str | None = None) -> list[dict]:
        out = _read_jsonl(self.changes_file)
        if asin:
            out = [c for c in out if c.get("asin") == asin]
        return sorted(out, key=lambda c: c.get("fecha_propuesta", ""))

    def get_change(self, change_id: str) -> dict:
        for c in self.changes():
            if c["id"] == change_id:
                return c
        raise KeyError(f"No existe el cambio {change_id}")

    def outcomes(self, change_id: str | None = None) -> list[dict]:
        out = _read_jsonl(self.outcomes_file)
        if change_id:
            out = [o for o in out if o.get("change_id") == change_id]
        return sorted(out, key=lambda o: o.get("fecha_evaluacion", ""))

    def latest_outcome(self, change_id: str) -> dict | None:
        outs = self.outcomes(change_id)
        return outs[-1] if outs else None

    def pending_proposals(self, asin: str) -> list[dict]:
        return [c for c in self.changes(asin) if c.get("estado") == "propuesto"]

    def applied(self, asin: str, campo: str | None = None) -> list[dict]:
        out = [c for c in self.changes(asin) if c.get("estado") == "aplicado"]
        if campo:
            out = [c for c in out if c.get("campo") == campo]
        return sorted(out, key=lambda c: c.get("fecha_aplicado", ""))

    # ------------------------------------------------------------- escritura
    def record_proposal(self, *, asin: str, sku: str, marketplace_id: str, campo: str,
                        valor_antes, valor_despues, antes_completo: dict, motivo: str,
                        riesgo: str, metrica_a_vigilar: str, keywords_objetivo: list[str],
                        es_correccion: bool, metricas_base: dict | None,
                        indexacion_base: dict | None, redactado_por: str,
                        revierte_a: str | None = None, hoy: date | None = None) -> dict:
        hoy = hoy or date.today()
        entry = {
            "id": f"LST-{hoy:%Y%m%d}-{asin}-{campo}-{secrets.token_hex(2)}",
            "asin": asin,
            "sku": sku,
            "marketplace_id": marketplace_id,
            "campo": campo,
            "estado": "propuesto",
            "es_correccion": es_correccion,
            "revierte_a": revierte_a,
            "fecha_propuesta": hoy.isoformat(),
            "fecha_aplicado": None,
            "valor_antes": valor_antes,
            "valor_despues": valor_despues,
            "antes_completo": antes_completo,
            "motivo": motivo,
            "riesgo": riesgo,
            "metrica_a_vigilar": metrica_a_vigilar,
            "keywords_objetivo": keywords_objetivo,
            "metricas_base": metricas_base,
            "indexacion_base": indexacion_base,
            "redactado_por": redactado_por,
        }
        _append_jsonl(self.changes_file, entry)
        return entry

    def _update_change(self, change_id: str, **fields) -> dict:
        entries = _read_jsonl(self.changes_file)
        for e in entries:
            if e["id"] == change_id:
                e.update(fields)
                _write_jsonl_atomic(self.changes_file, entries)
                return e
        raise KeyError(f"No existe el cambio {change_id}")

    def mark_applied(self, change_id: str, fecha: date | None = None,
                     detectado_automaticamente: bool = False, metricas_base: dict | None = None) -> dict:
        c = self.get_change(change_id)
        if c["estado"] != "propuesto":
            raise ValueError(f"{change_id} está '{c['estado']}', no 'propuesto'")
        fields = {
            "estado": "aplicado",
            "fecha_aplicado": (fecha or date.today()).isoformat(),
            "aplicado_detectado_automaticamente": detectado_automaticamente,
        }
        if metricas_base is not None:
            fields["metricas_base"] = metricas_base
        return self._update_change(change_id, **fields)

    def mark_discarded(self, change_id: str, motivo: str = "") -> dict:
        c = self.get_change(change_id)
        if c["estado"] != "propuesto":
            raise ValueError(f"{change_id} está '{c['estado']}', solo se descarta lo 'propuesto'")
        return self._update_change(change_id, estado="descartado", motivo_descarte=motivo)

    def record_outcome(self, change_id: str, veredicto: str, *, ventana: str = "",
                       metricas_despues: dict | None = None, notas: str = "",
                       agente: str = "", fecha: date | None = None) -> dict:
        """Lo usa el OTRO agente (o Juan) para decir cómo fue un cambio."""
        if veredicto not in VEREDICTOS:
            raise ValueError(f"veredicto debe ser uno de {VEREDICTOS}")
        c = self.get_change(change_id)  # falla si el id no existe: nada de veredictos huérfanos
        if c["estado"] != "aplicado":
            raise ValueError(f"{change_id} no está aplicado; no se puede evaluar")
        entry = {
            "change_id": change_id,
            "asin": c["asin"],
            "campo": c["campo"],
            "fecha_evaluacion": (fecha or date.today()).isoformat(),
            "ventana": ventana,
            "metricas_despues": metricas_despues or {},
            "veredicto": veredicto,
            "notas": notas,
            "agente": agente,
        }
        _append_jsonl(self.outcomes_file, entry)
        return entry

    def notify_ads(self, asin: str, tipo: str, detalle: str, campo: str | None = None,
                   change_id: str | None = None) -> dict:
        entry = {
            "fecha": datetime.now().isoformat(timespec="seconds"),
            "asin": asin,
            "tipo": tipo,
            "campo": campo,
            "change_id": change_id,
            "detalle": detalle,
        }
        _append_jsonl(self.ads_events_file, entry)
        return entry

    def record_indexation(self, rows: list[dict]) -> None:
        for r in rows:
            _append_jsonl(self.indexation_file, r)

    def indexation_history(self, asin: str) -> list[dict]:
        return [r for r in _read_jsonl(self.indexation_file) if r.get("asin") == asin]

    # ------------------------------------------------------------ resumen
    def summary(self, asin: str) -> dict:
        """Lo que se le enseña al redactor (Cowork / Claude) antes de proponer."""
        historial = []
        por_campo: dict[str, dict[str, int]] = {}
        no_repetir = []
        funciono = []
        for c in self.changes(asin):
            if c["estado"] == "descartado":
                continue
            out = self.latest_outcome(c["id"])
            ver = out["veredicto"] if out else None
            historial.append({
                "id": c["id"],
                "campo": c["campo"],
                "estado": c["estado"],
                "fecha_aplicado": c.get("fecha_aplicado"),
                "antes": c["valor_antes"],
                "despues": c["valor_despues"],
                "motivo": c["motivo"],
                "veredicto": ver or "sin evaluar",
                "notas_evaluacion": out.get("notas") if out else None,
            })
            if c["estado"] == "aplicado" and ver:
                stats = por_campo.setdefault(c["campo"], {v: 0 for v in VEREDICTOS})
                stats[ver] += 1
                if ver == "empeora":
                    no_repetir.append({"campo": c["campo"], "valor": c["valor_despues"]})
                elif ver == "mejora":
                    funciono.append({"campo": c["campo"], "valor": c["valor_despues"],
                                     "keywords": c.get("keywords_objetivo", [])})
        return {
            "historial": historial,
            "aciertos_por_campo": por_campo,
            "no_repetir": no_repetir,
            "funciono": funciono,
        }

    def check_change_allowed(self, asin: str, campo: str, es_correccion: bool, reglas: dict,
                             hoy: date | None = None) -> list[str]:
        """Reglas de cadencia (regla 4). Devuelve los motivos de bloqueo; vacío = permitido."""
        hoy = hoy or date.today()
        bloqueos = []
        pend = self.pending_proposals(asin)
        if pend:
            bloqueos.append(
                f"Ya hay un cambio propuesto sin publicar ({pend[-1]['id']}, campo {pend[-1]['campo']}). "
                "Un cambio cada vez: publícalo o descártalo primero."
            )
        if es_correccion:
            return bloqueos  # "salvo error": una corrección no espera a la cadencia

        aplicados = self.applied(asin)
        if aplicados:
            ult = aplicados[-1]
            dias = (hoy - _d(ult["fecha_aplicado"])).days
            evaluado = self.latest_outcome(ult["id"]) is not None
            minimo = reglas["dias_minimos_con_evaluacion"] if evaluado else reglas["dias_espera_sin_evaluacion"]
            if dias < minimo:
                bloqueos.append(
                    f"El último cambio ({ult['id']}, {ult['campo']}) se aplicó hace {dias} días; "
                    f"hay que esperar {minimo} días{' (aún sin evaluar)' if not evaluado else ''} "
                    "para poder atribuir el efecto."
                )
        if campo == "titulo":
            titulos = self.applied(asin, "titulo")
            if titulos:
                dias = (hoy - _d(titulos[-1]["fecha_aplicado"])).days
                if dias < reglas["dias_minimos_entre_cambios_titulo"]:
                    bloqueos.append(
                        f"El título se cambió hace {dias} días; mínimo "
                        f"{reglas['dias_minimos_entre_cambios_titulo']} días entre cambios de título salvo error."
                    )
        return bloqueos
