"""entradas/ y salidas/ con una carpeta por día; la memoria parte de la del día anterior."""

import shutil
import sys
from datetime import date
from pathlib import Path

import pytest
from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agente
import carpetas
import config
import investigacion
from documento import Documento

RAIZ = Path(__file__).resolve().parent.parent
DIA = RAIZ / "entradas" / "2026-09-28"


@pytest.fixture
def carpetas_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ENTRADAS", tmp_path / "entradas")
    monkeypatch.setattr(config, "SALIDAS", tmp_path / "salidas")
    for v in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "ANTHROPIC_API_KEY", "AMAZON_ADS_CLIENT_ID"):
        monkeypatch.delenv(v, raising=False)
    return tmp_path


def test_entrada_mas_reciente_con_hoja_masiva(carpetas_tmp):
    for d in ("2026-09-20", "2026-09-28", "2026-10-02"):
        (config.ENTRADAS / d).mkdir(parents=True)
    shutil.copy(DIA / "hoja_masiva_2026-09-28.xlsx", config.ENTRADAS / "2026-09-20")
    shutil.copy(DIA / "hoja_masiva_2026-09-28.xlsx", config.ENTRADAS / "2026-09-28")
    (config.ENTRADAS / "no-es-un-dia").mkdir()
    assert carpetas.entrada(date(2026, 10, 5)).name == "2026-09-28"     # la del 02/10 no trae hoja masiva
    assert carpetas.entrada(date(2026, 9, 25)).name == "2026-09-20"     # nunca una carpeta del futuro


def test_memoria_parte_de_la_anterior_y_conserva_hojas_ajenas(carpetas_tmp):
    ayer = config.SALIDAS / "2026-09-28"
    ayer.mkdir(parents=True)
    shutil.copy(RAIZ / "salidas" / "2026-09-28" / config.NOMBRE_MEMORIA, ayer)
    origen = carpetas.memoria_anterior(date(2026, 9, 30))
    assert origen == ayer / config.NOMBRE_MEMORIA
    doc = Documento(carpetas.salida(date(2026, 9, 30)) / config.NOMBRE_MEMORIA, origen=origen)
    tickets = len(doc.hojas["Tickets"])
    assert tickets >= 31 and "Productos" in doc.otras
    doc.guardar()
    wb = load_workbook(config.SALIDAS / "2026-09-30" / config.NOMBRE_MEMORIA, read_only=True)
    assert {"Productos", "Anuncios (histórico)", "Tickets"} <= set(wb.sheetnames)
    assert len(Documento(config.SALIDAS / "2026-09-30" / config.NOMBRE_MEMORIA).hojas["Tickets"]) == tickets
    assert (ayer / config.NOMBRE_MEMORIA).exists()                        # la del día anterior no se toca


def test_importa_el_documento_de_investigacion(tmp_path):
    doc = Documento(tmp_path / "m.xlsx")
    n = investigacion.importar_documento(doc, DIA / "Documento_investigacion_keywords.xlsx", date(2026, 9, 28))
    assert n["B0DCZS1NR6"] > 10 and n["B0DHYBY6MS"] > 10
    assert not [f for f in doc.hojas["Investigación"] if f["Motivo"].startswith("Recomendada ML")]
    # volver a importar el mismo día no duplica
    investigacion.importar_documento(doc, DIA / "Documento_investigacion_keywords.xlsx", date(2026, 9, 28))
    assert sum(1 for f in doc.hojas["Investigación"] if f["Producto (ASIN)"] == "B0DCZS1NR6") == n["B0DCZS1NR6"]
    fecha, filas = doc.investigacion("B0DCZS1NR6")
    assert fecha == date(2026, 9, 28) and filas[0]["Rank"] == 1


def test_ejecucion_completa_escribe_en_salidas_del_dia(carpetas_tmp):
    (config.ENTRADAS / "2026-09-28").mkdir(parents=True)
    for f in DIA.glob("*.xlsx"):
        shutil.copy(f, config.ENTRADAS / "2026-09-28")
    (config.SALIDAS / "2026-09-28").mkdir(parents=True)
    shutil.copy(RAIZ / "salidas" / "2026-09-28" / config.NOMBRE_MEMORIA, config.SALIDAS / "2026-09-28")
    with pytest.raises(SystemExit) as fin:                                # descarga real: todo terminado -> para
        agente.main(["--simular", "--sin-investigacion", "--hoy", "2026-09-29"])
    assert fin.value.code == 2
    hoy = config.SALIDAS / "2026-09-29"
    doc = Documento(hoy / config.NOMBRE_MEMORIA)
    resumen = {f["Concepto"]: f["Valor"] for f in doc.hojas["Resumen"]}
    assert resumen["Memoria de partida"].endswith("2026-09-28/memoria_agente.xlsx")
    assert any(k.startswith("Investigación importada") for k in resumen)
    assert len(doc.hojas["Tickets"]) >= 31 and "Productos" in doc.otras
    assert list((hoy / "correos_pendientes").glob("*.eml"))
