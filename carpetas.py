"""
carpetas.py — entradas/ y salidas/, con una carpeta por día (AAAA-MM-DD).

  entradas/AAAA-MM-DD/  lo que deja Juan (o Cowork): la hoja masiva descargada de Amazon Ads y la
                        investigación del día (investigacion_<día>.csv).
  salidas/AAAA-MM-DD/   lo que deja el agente: memoria_agente.xlsx actualizada, bulk_cambios_*.xlsx
                        para subir a Amazon, Documento_investigacion_keywords.xlsx y los correos
                        que no se pudieron enviar.

La memoria de un día parte de la del día anterior más reciente (o de la del mismo día, si se vuelve
a ejecutar): nunca se empieza de cero ni se pierde el histórico.
"""

from datetime import date
from pathlib import Path

import config


def dia(p):
    try:
        return date.fromisoformat(p.name)
    except ValueError:
        return None


def dias(raiz, hasta=None):
    """Carpetas de día de raiz, de la más reciente a la más antigua (hasta la fecha dada, incluida)."""
    raiz = Path(raiz)
    if not raiz.is_dir():
        return []
    out = [(d, p) for p in raiz.iterdir() if p.is_dir() and (d := dia(p)) and (hasta is None or d <= hasta)]
    return [p for d, p in sorted(out, reverse=True)]


def entrada(hoy):
    """La carpeta de entrada más reciente hasta hoy que trae una hoja masiva, o None."""
    import fuente_bulk
    return next((p for p in dias(config.ENTRADAS, hoy) if fuente_bulk.buscar_descarga(p)), None)


def salida(hoy):
    return config.SALIDAS / hoy.isoformat()


def memoria_anterior(hoy):
    """La memoria más reciente hasta hoy (la de hoy incluida), o None si aún no hay ninguna."""
    return next((m for p in dias(config.SALIDAS, hoy) if (m := p / config.NOMBRE_MEMORIA).exists()), None)
