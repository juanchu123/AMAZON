"""Bloque B: pruebas autónomas (Juan, 30/09/2026)."""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import pruebas
from documento import Documento
from modelo import NUEVA_KEYWORD
from test_agente import HOY, PINZA, correr, cuenta_pinza, filas_diarias


@pytest.fixture(scope="module")
def catalogo():
    from prediccion import Catalogo
    return Catalogo()


def test_potencial_es_optimista_pero_acotado():
    for p in (0.01, 0.03, 0.08):
        assert p < pruebas.p_potencial(p) < 2 * p


def test_sin_pruebas_en_black_friday_y_navidad(tmp_path):
    doc = Documento(tmp_path / "d.xlsx")
    for dia in (date(2026, 11, 27), date(2026, 12, 24), date(2027, 1, 5)):
        assert pruebas.cupo(doc, cuenta_pinza(), doc.series(), dia, 100.0)[0] == 0
    assert pruebas.cupo(doc, cuenta_pinza(), doc.series(), date(2026, 10, 11), 100.0)[0] == config.MAX_PRUEBAS_NUEVAS_POR_RONDA


def test_cupo_segun_lo_que_queda_del_tope(tmp_path):
    doc = Documento(tmp_path / "d.xlsx")
    # día 11 con 270 € gastados: al ritmo de 27 €/día se llega a ~837 €: no cabe ninguna prueba de 8 €
    assert pruebas.cupo(doc, cuenta_pinza(), doc.series(), date(2026, 10, 11), 270.0)[0] == 0
    # con 200 € el ritmo deja ~220 € libres: caben (hasta 3 por ronda)
    assert pruebas.cupo(doc, cuenta_pinza(), doc.series(), date(2026, 10, 11), 200.0)[0] == 3


def test_prueba_entra_marcada_y_con_potencial(tmp_path, catalogo):
    res, api, doc = correr(tmp_path, cuenta_pinza(n_keywords=6), [], catalogo)
    pr = [c for c in res["cambios"] if c.tipo == NUEVA_KEYWORD and c.extra.get("prueba")]
    assert 1 <= len(pr) <= 1          # gasto del mes desconocido: como mucho 1 prueba
    c = pr[0]
    assert c.extra["acos_media"] > config.ACOS_MAX_KEYWORD_NUEVA >= c.extra["acos_pred"]
    assert c.motivo.startswith("PRUEBA")
    t = next(t for t in doc.hojas["Tickets"] if t["Tipo"] == NUEVA_KEYWORD and json.loads(t["Datos extra"]).get("prueba"))
    assert t["Estado"] == "confirmado"


def test_aprende_que_tipo_de_frase_no_vende(tmp_path, catalogo):
    doc = Documento(tmp_path / "d.xlsx")
    for i in range(3):   # tres genéricas en frase añadidas por el agente: 60 clics maduros, 0 ventas
        doc.hojas["Tickets"].append({"Ticket": f"T-{i}", "Fecha": (HOY - timedelta(days=25)).isoformat(),
                                     "Tipo": NUEVA_KEYWORD, "Clave": f"G{i}", "Producto (ASIN)": PINZA,
                                     "Palabra clave / segmentación": f"soporte movil coche {i}", "Coincidencia": "Frase",
                                     "Estado": "confirmado", "Datos extra": json.dumps({"p_modelo": 0.05})})
        doc.guardar_diario(filas_diarias(f"G{i}", 20, 3, 0.3))
    ap = pruebas.Aprendizaje(doc, doc.series(), catalogo, HOY)
    f = ap.factor(PINZA, "soporte movil coche barato", "Frase")
    assert f < 0.5                                               # esperaba ~2 ventas y hubo 0
    assert ap.factor(PINZA, "soporte movil coche pinza", "Frase") == 1.0   # las específicas no se tocan
    assert ap.filas()[0]["Tipo de frase"] == "genérica"
