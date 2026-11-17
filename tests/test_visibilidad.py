"""Plan de visibilidad de Juan (directivas.visibilidad): pujas fijadas con tope de pérdida semanal."""
from datetime import date
from types import SimpleNamespace

import config
import directivas
from modelo import ACTIVO, PUJA, Metricas


class Series:
    def __init__(self, por_dia):
        self.por_dia = por_dia            # {clave: [(fecha, Metricas acumuladas)]}

    def acumulado(self, clave, hasta):
        m = Metricas()
        for d, x in self.por_dia.get(clave, []):
            if d <= hasta:
                m = x
        return m


def _cuenta():
    el = SimpleNamespace(clave="t1", id_grupo="g1", id_campana="c1", estado=ACTIVO, puja=0.23, texto="substitutes",
                         coincidencia="")
    return SimpleNamespace(elementos={"t1": el}, campanas={"c1": SimpleNamespace(nombre="Auto")},
                           producto_de_grupo=lambda g: "A1")


def _plan(monkeypatch):
    monkeypatch.setattr(config, "VISIBILIDAD", {"desde": "2026-10-18", "hasta": "2026-12-02",
                                                "tope_perdida_semana_eur": 10, "pujas": {"t1": 0.40}})
    monkeypatch.setattr(config, "MARGEN_UNITARIO", {"A1": 3.0})


def test_plan_activo_fija_la_puja(monkeypatch):
    _plan(monkeypatch)
    cuenta = _cuenta()
    serie = Series({"t1": [(date(2026, 10, 18), Metricas(clics=10, coste=4.0, compras=1))]})
    pujas, aviso = directivas.visibilidad(cuenta, serie, date(2026, 10, 21))
    assert pujas == {"t1": 0.40} and aviso[0] == "visibilidad_estado"
    (c,) = directivas.cambios_visibilidad(cuenta, pujas)
    assert c.tipo == PUJA and c.antes == 0.23 and c.despues == 0.40 and c.extra["visibilidad"]


def test_plan_se_para_al_llegar_al_tope_y_vuelve_el_lunes(monkeypatch):
    _plan(monkeypatch)
    cuenta = _cuenta()
    serie = Series({"t1": [(date(2026, 10, 20), Metricas(clics=40, coste=14.0, compras=1))]})   # pérdida 11 €
    pujas, aviso = directivas.visibilidad(cuenta, serie, date(2026, 10, 22))
    assert pujas == {} and "PARADO" in aviso[2]
    pujas, _ = directivas.visibilidad(cuenta, serie, date(2026, 10, 26))       # lunes: semana nueva
    assert pujas == {"t1": 0.40}


def test_plan_terminado(monkeypatch):
    _plan(monkeypatch)
    pujas, aviso = directivas.visibilidad(_cuenta(), Series({}), date(2026, 12, 3))
    assert pujas == {} and "terminado" in aviso[2]
