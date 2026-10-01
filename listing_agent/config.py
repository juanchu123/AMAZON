"""
config.py
---------
Carga config.json (lo que Juan decide) y las credenciales del entorno o
de un archivo .env (lo que NUNCA va en git). Todas las rutas relativas se
resuelven desde la carpeta donde está config.json, así Juan puede mover la
carpeta del agente donde quiera sin tocar el código.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent

# Valores por defecto de reglas. Todos salen de AGENTE_PAGINA_PRODUCTO.md y
# de la guía; ninguno se relaja solo — solo Juan los cambia en config.json.
DEFAULT_RULES = {
    # "Un cambio mayor cada vez ... esperar 7–14 días antes de evaluar".
    "dias_espera_sin_evaluacion": 14,   # sin veredicto del otro agente: esperar 14 días
    "dias_minimos_con_evaluacion": 7,   # con veredicto ya recibido: mínimo 7 días
    # "No tocar el título más de una vez cada 4–6 semanas salvo error" -> se usa el extremo conservador.
    "dias_minimos_entre_cambios_titulo": 42,
    # "Contar bytes ... y dejar margen" (backend de 249 bytes).
    "margen_bytes_backend": 5,
    # Ventana de métricas que se guarda como línea base / estado actual.
    "ventana_metricas_dias": 14,
}

DEFAULT_INDEXATION = {
    "max_keywords_por_ejecucion": 15,
    "paginas_por_busqueda": 2,
}


@dataclass
class AsinConfig:
    asin: str
    sku: str | None = None
    keywords_semilla: list[str] = field(default_factory=list)
    keyword_principal: str | None = None
    tiene_campanas_activas: bool = True


@dataclass
class Config:
    base_dir: Path
    marketplace_id: str
    endpoint: str
    idioma: str
    marca_propia: str
    asins: list[AsinConfig]
    marcas_competidoras: list[str]
    marcas_de_dispositivos: list[str]
    claims_confirmados_por_legal: list[str]
    reglas: dict
    indexacion: dict
    csv_ads: list[str]
    historico_json: str | None
    logs_dir: Path
    informes_dir: Path
    trabajo_dir: Path
    redaccion_modo: str
    redaccion_modelo: str

    def asin_cfg(self, asin: str) -> AsinConfig:
        for a in self.asins:
            if a.asin == asin:
                return a
        raise KeyError(f"El ASIN {asin} no está en config.json")


def load_dotenv(path: Path) -> None:
    """Lector mínimo de .env (CLAVE=valor por línea). No pisa variables que
    ya estén definidas en el entorno real."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def load_config(path: str | Path | None = None) -> Config:
    cfg_path = Path(path) if path else AGENT_DIR / "config.json"
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"No existe {cfg_path}. Copia config.example.json a config.json y rellénalo."
        )
    base = cfg_path.resolve().parent
    load_dotenv(base / ".env")
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))

    rutas = raw.get("rutas", {})
    fuentes = raw.get("fuentes_keywords", {})
    redaccion = raw.get("redaccion", {})

    def _p(rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else (base / p)

    cfg = Config(
        base_dir=base,
        marketplace_id=raw.get("marketplace_id", "A1RKKUPIHCS9HS"),
        endpoint=raw.get("endpoint", "https://sellingpartnerapi-eu.amazon.com"),
        idioma=raw.get("idioma", "es_ES"),
        marca_propia=raw.get("marca_propia", ""),
        asins=[AsinConfig(**a) for a in raw.get("asins", [])],
        marcas_competidoras=raw.get("marcas_competidoras", []),
        marcas_de_dispositivos=raw.get("marcas_de_dispositivos", []),
        claims_confirmados_por_legal=raw.get("claims_confirmados_por_legal", []),
        reglas={**DEFAULT_RULES, **raw.get("reglas", {})},
        indexacion={**DEFAULT_INDEXATION, **raw.get("indexacion", {})},
        csv_ads=[str(_p(g)) for g in fuentes.get("csv_ads", [])],
        historico_json=str(_p(fuentes["historico_json"])) if fuentes.get("historico_json") else None,
        logs_dir=_p(rutas.get("logs", "logs")),
        informes_dir=_p(rutas.get("informes", "informes")),
        trabajo_dir=_p(rutas.get("trabajo", "trabajo")),
        redaccion_modo=redaccion.get("modo", "auto"),
        redaccion_modelo=redaccion.get("modelo", "claude-opus-5-5"),
    )
    for d in (cfg.logs_dir, cfg.informes_dir, cfg.trabajo_dir):
        d.mkdir(parents=True, exist_ok=True)
    return cfg


def sp_api_credentials() -> dict:
    """Credenciales de la SP-API desde el entorno. Falla con un mensaje
    claro si falta alguna, en vez de intentar seguir a ciegas."""
    keys = {
        "client_id": "SP_API_CLIENT_ID",
        "client_secret": "SP_API_CLIENT_SECRET",
        "refresh_token": "SP_API_REFRESH_TOKEN",
        "seller_id": "SP_API_SELLER_ID",
    }
    missing = [env for env in keys.values() if not os.environ.get(env)]
    if missing:
        raise RuntimeError(
            "Faltan credenciales de SP-API en el entorno o en .env: " + ", ".join(missing)
        )
    return {k: os.environ[env] for k, env in keys.items()}
