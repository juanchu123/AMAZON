"""Bloque A (Amazon Ads Academy + decisiones de Juan del 30/09/2026): validación, escalonado por
coincidencia, términos de búsqueda (cosecha y negativas), reactivar, presupuesto en una sola bolsa."""

import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import presupuesto
import validacion
from documento import Documento
from modelo import (ACTIVO, KEYWORD, NEGATIVA, NUEVA_KEYWORD, PAUSADO, REACTIVAR, REACTIVAR_CAMPANA, Anuncio, Campana,
                    Grupo, Metricas, Negativa, Termino)
from test_agente import HOY, PINZA, SKU, APIFalsa, correr, cuenta_pinza, filas_diarias

REJILLA = "B0DHYBY6MS"


class APIMas(APIFalsa):
    def crear_negativa(self, id_c, id_g, texto, coinc):
        self.llamadas.append(("negativa", id_g, texto, coinc))
        self.cuenta.negativas.append(Negativa("N1", id_c, id_g, texto, coinc, ACTIVO))
        return True, "N1", "Creado y releído en Amazon"

    def reactivar(self, el, puja):
        self.llamadas.append(("reactivar", el.clave, puja))
        self.cuenta.elementos[el.clave].estado, self.cuenta.elementos[el.clave].puja = ACTIVO, puja
        return True, "Releído en Amazon: coincide"

    def reactivar_campana(self, id_c, eur, grupos, anuncios):
        self.llamadas.append(("reactivar_campana", id_c, eur))
        self.cuenta.campanas[id_c].estado = ACTIVO
        return True, "ok"


@pytest.fixture(scope="module")
def catalogo():
    from prediccion import Catalogo
    return Catalogo()


def _correr(tmp_path, cuenta, diario, catalogo):
    import agente
    from datetime import datetime
    doc = Documento(tmp_path / "doc.xlsx")
    api = APIMas(cuenta, diario)
    res = agente.ejecutar(agente.FuenteAPI(api, doc), doc, catalogo, HOY, datetime(2026, 10, 20, 9), investigar="no",
                          log=lambda *_: None)
    return res, api, Documento(tmp_path / "doc.xlsx")


# ---------------------------------------------------------------- validación (errores 1018, 1021, 1025)
def test_validacion_de_amazon():
    assert validacion.keyword("soporte movil coche pinza")[0]
    assert not validacion.keyword("x" * 81)[0]
    for malo in ("soporte/movil", "100% pinza", "pinza, coche", "a^b", "a..b", "a:b"):
        assert not validacion.keyword(malo)[0], malo
    assert not validacion.keyword(" ".join(["palabra"] * 11))[0]
    assert validacion.coincidencia("Exacta") and not validacion.coincidencia("Coincidencia exacta")
    assert validacion.coincidencia("Exacta negativa", negativa=True)
    assert validacion.estrategia("Pujas dinámicas: solo a la baja") and not validacion.estrategia("solo reducir")


def test_candidata_invalida_no_pasa(catalogo):
    ev = catalogo.evaluar(PINZA, "soporte movil, pinza")
    assert not ev["pasa"] and "Amazon" in ev["motivo"]


# ---------------------------------------------------------------- escalonado amplia ≤ frase ≤ exacta
def test_escalonado_por_coincidencia(catalogo):
    for asin in (PINZA, REJILLA, "B0CPHXXHRQ", "B0DSV986XY"):
        for texto in ("soporte movil coche pinza", "soporte movil coche", "rejilla ventilacion coche"):
            a, f, e = (catalogo.p_modelo(asin, texto, m) for m in ("Amplia", "Frase", "Exacta"))
            assert a <= f + 1e-12 <= e + 2e-12, (asin, texto, a, f, e)
    # sin modelo fiable (Pou) la amplia convierte menos que la frase, como en el histórico de la cuenta
    assert catalogo.p_modelo("B0CPHXXHRQ", "x y", "Amplia") < catalogo.p_modelo("B0CPHXXHRQ", "x y", "Frase")


# ---------------------------------------------------------------- términos de búsqueda
def _termino(texto, clics, coste, compras=0, ventas=0.0, origen="soporte movil coche pinza"):
    return Termino("C1", "G1", "K0", origen, "Frase", texto, Metricas(clics, coste, compras, ventas))


def test_negativa_por_cpa_y_cosecha_a_exacta(tmp_path, catalogo):
    cuenta = cuenta_pinza(n_keywords=11)
    cuenta.terminos_maduros = True
    cpa = catalogo.producto(PINZA).ticket * config.ACOS_OBJETIVO_MAX            # ≈ 3,93 €
    cuenta.terminos = [
        _termino("funda movil barata", 6, cpa + 0.5),                           # gasta > CPA sin vender -> negativa
        _termino("soporte pinza movil negro", 3, 1.0),                        # por debajo del CPA -> vigilar
        _termino("pinza movil salpicadero coche", 20, 3.0, compras=2, ventas=22.48),  # vende con ACOS 13 % -> Exacta
        _termino("soporte movil coche pinza", 30, 9.0),                         # es la propia keyword: stop-loss
    ]
    res, api, doc = _correr(tmp_path, cuenta, [], catalogo)
    negs = [l for l in api.llamadas if l[0] == "negativa"]
    assert negs == [("negativa", "G1", "funda movil barata", "Exacta negativa")]
    cosecha = [c for c in res["cambios"] if c.tipo == NUEVA_KEYWORD and c.extra.get("fuente") == "términos de búsqueda"]
    assert len(cosecha) == 1 and cosecha[0].texto == "pinza movil salpicadero coche"
    assert cosecha[0].coincidencia == "Exacta" and cosecha[0].estado == "confirmado"
    # entra antes que cualquier candidata: solo quedaba un hueco (11/12)
    assert not [c for c in res["cambios"] if c.tipo == NUEVA_KEYWORD and c.id_grupo == "G1"
                and c.extra.get("fuente") != "términos de búsqueda"]
    t = next(t for t in doc.hojas["Tickets"] if t["Tipo"] == NEGATIVA)
    assert t["Estado"] == "confirmado"
    decisiones = {f["Término de búsqueda"]: f["Decisión"] for f in doc.hojas["Términos"]}
    assert decisiones["soporte pinza movil negro"].startswith("Vigilar")
    assert decisiones["soporte movil coche pinza"].startswith("Es la propia keyword")


def test_negativa_de_traslado_cuando_ya_es_exacta(tmp_path, catalogo):
    cuenta = cuenta_pinza()
    cuenta.campanas["C2"] = Campana("C2", "Pinza - Exactas", ACTIVO, 3.0)
    cuenta.grupos["G2"] = Grupo("G2", "C2", "Exactas", ACTIVO, 0.4)
    cuenta.anuncios.append(Anuncio("A2", "C2", "G2", PINZA, SKU, ACTIVO))
    from modelo import Elemento
    cuenta.elementos["KX"] = Elemento("KX", KEYWORD, "C2", "G2", "pinza movil salpicadero coche", "Exacta", ACTIVO, 0.4)
    cuenta.terminos_maduros = True
    cuenta.terminos = [_termino("pinza movil salpicadero coche", 20, 3.0, compras=2, ventas=22.48)]
    res, api, _ = _correr(tmp_path, cuenta, [], catalogo)
    assert ("negativa", "G1", "pinza movil salpicadero coche", "Exacta negativa") in api.llamadas


def test_hoja_masiva_negativa_sin_foto_antigua_espera(tmp_path, catalogo):
    import terminos
    cuenta = cuenta_pinza()
    cuenta.terminos = [_termino("funda movil barata", 6, 10.0)]         # hoja masiva: sin foto de hace 7 días
    doc = Documento(tmp_path / "d.xlsx")
    terminos.guardar_fotos(doc, cuenta, HOY)
    r = terminos.decidir(cuenta, doc, catalogo, HOY)
    assert not r.negativas and "foto" in list(r.notas.values())[0]
    # con una foto de hace 8 días que ya tenía el gasto -> negativa
    doc.hojas["Términos"].append({"Fecha": (HOY - timedelta(days=8)).isoformat(), "Clave": cuenta.terminos[0].clave,
                                  "Clics": 6, "Coste (€)": 10.0, "Compras": 0, "Ventas (€)": 0})
    assert terminos.decidir(cuenta, doc, catalogo, HOY).negativas


# ---------------------------------------------------------------- reactivar (Juan, 30/09/2026)
def test_reactiva_keyword_en_pausa_si_sus_datos_lo_justifican(tmp_path, catalogo):
    cuenta = cuenta_pinza(n_keywords=11)
    cuenta.elementos["K3"].estado = PAUSADO               # 'pinza movil coche' en pausa, pero vendía bien
    compras = {i: 1 for i in range(8, 20, 2)}
    diario = filas_diarias("K3", 20, 2, 0.3, compras_por_dia=compras)   # 26 clics maduros, 6 compras, 0,30 €/clic
    res, api, doc = _correr(tmp_path, cuenta, diario, catalogo)
    assert any(l[0] == "reactivar" and l[1] == "K3" for l in api.llamadas)
    t = next(t for t in doc.hojas["Tickets"] if t["Tipo"] == REACTIVAR)
    assert t["Estado"] == "confirmado"


def test_no_reactiva_lo_que_no_vende_ni_lo_pausado_dos_veces(tmp_path, catalogo):
    cuenta = cuenta_pinza(n_keywords=11)
    cuenta.elementos["K3"].estado = PAUSADO
    diario = filas_diarias("K3", 20, 2, 0.3)             # 26 clics maduros sin ninguna venta
    res, api, _ = _correr(tmp_path, cuenta, diario, catalogo)
    assert not any(l[0] == "reactivar" for l in api.llamadas)


def test_stop_loss_cuenta_desde_la_reactivacion(tmp_path, catalogo):
    cuenta = cuenta_pinza()
    diario = filas_diarias("K0", 20, 2, 0.1)             # historia vieja sin ventas
    doc = Documento(tmp_path / "doc.xlsx")
    doc.hojas["Tickets"].append({"Ticket": "T-0001", "Fecha": (HOY - timedelta(days=2)).isoformat(), "Tipo": REACTIVAR,
                                 "Clave": "K0", "Producto (ASIN)": PINZA, "Palabra clave / segmentación": "x",
                                 "Coincidencia": "Frase", "Antes": 0.3, "Después": 0.4, "Estado": "confirmado",
                                 "Base: clics": 36, "Base: coste": 1.8})
    doc.guardar()
    res, api, _ = _correr(tmp_path, cuenta, diario, catalogo)
    assert ("pausar", "K0") not in api.llamadas           # lo de antes de reactivarla no cuenta


def test_reactiva_campana_en_pausa_con_keywords_buenas(tmp_path, catalogo):
    cuenta = cuenta_pinza()
    cuenta.campanas["CR"] = Campana("CR", "Rejilla - Principal V2", PAUSADO, 5.0)
    cuenta.grupos["GR"] = Grupo("GR", "CR", "Rejilla", ACTIVO, 0.3)
    cuenta.anuncios.append(Anuncio("AR", "CR", "GR", REJILLA, "5E-I8NY-S191", ACTIVO))
    from modelo import Elemento
    cuenta.elementos["KR"] = Elemento("KR", KEYWORD, "CR", "GR", "rejilla ventilacion soporte movil", "Exacta", ACTIVO, 0.3)
    diario = [f | {"ID campaña": "CR"} for f in filas_diarias("KR", 20, 2, 0.3, compras_por_dia={i: 1 for i in range(8, 20, 2)})]
    res, api, doc = _correr(tmp_path, cuenta, diario, catalogo)
    assert any(l[0] == "reactivar_campana" and l[1] == "CR" and l[2] >= config.PRESUPUESTO_MIN_CAMPANA_NUEVA
               for l in api.llamadas)
    assert not any(l[0] == "campana" for l in api.llamadas)          # no abre otra: reactiva la que había
    assert next(t for t in doc.hojas["Tickets"] if t["Tipo"] == REACTIVAR_CAMPANA)["Estado"] == "confirmado"


# ---------------------------------------------------------------- presupuesto (una bolsa, limitadas)
def test_presupuesto_a_la_limitada_y_no_a_la_que_no_gasta(catalogo):
    from modelo import Cuenta, Elemento
    c = Cuenta(fecha=HOY)
    doc = Documento("/nonexistent/doc.xlsx")
    for i, gasto in enumerate((5.0, 1.0)):              # C0 agota sus 5 €; C1 gasta 1 € de 5 €
        c.campanas[f"C{i}"] = Campana(f"C{i}", f"Pinza {i}", ACTIVO, 5.0)
        c.grupos[f"G{i}"] = Grupo(f"G{i}", f"C{i}", "g", ACTIVO, 0.3)
        c.anuncios.append(Anuncio(f"A{i}", f"C{i}", f"G{i}", PINZA, SKU, ACTIVO))
        c.elementos[f"K{i}"] = Elemento(f"K{i}", KEYWORD, f"C{i}", f"G{i}", "x", "Frase", ACTIVO, 0.3)
        doc.guardar_diario([f | {"ID campaña": f"C{i}"} for f in filas_diarias(f"K{i}", 20, 5, gasto)])
    cambios, filas, _, tope = presupuesto.planificar(c, doc, doc.series(), catalogo, HOY, gasto_mes=None)
    obj = {f["Campaña"]: f for f in filas}
    assert obj["Pinza 0"]["Limitada por presupuesto"] == "Sí"
    assert obj["Pinza 1"]["Presupuesto objetivo (€)"] == pytest.approx(1.5)       # 1,5 × lo que gasta
    assert obj["Pinza 0"]["Presupuesto objetivo (€)"] > 20                        # el resto del tope va a la buena
    assert sum(f["Presupuesto objetivo (€)"] for f in filas) <= tope + 0.01


# ---------------------------------------------------------------- hoja masiva: escribe lo nuevo con los valores de Amazon
def test_hoja_masiva_escribe_negativa_y_reactivacion(tmp_path):
    from openpyxl import load_workbook
    import fuente_bulk
    from modelo import Cambio
    cuenta = cuenta_pinza()
    cuenta.elementos["K1"].estado = PAUSADO
    f = fuente_bulk.FuenteBulk(tmp_path / "x.xlsx", tmp_path)
    f.producto_txt, f.activada = "Sponsored\xa0Products", "activada"
    comun = dict(producto=PINZA, id_campana="C1", id_grupo="G1", campana="Pinza", motivo="m")
    f.aplicar(Cambio(tipo=NEGATIVA, clave="neg", texto="funda movil", coincidencia="Exacta negativa", antes=None,
                     despues="Exacta negativa", **comun), cuenta)
    f.aplicar(Cambio(tipo=REACTIVAR, clave="K1", texto="soporte movil pinza", coincidencia="Frase", antes=0.3,
                     despues=0.45, **comun), cuenta)
    ws = load_workbook(f.cerrar(HOY))[fuente_bulk.HOJA]
    cab = [c.value for c in ws[1]]
    filas = [dict(zip(cab, r)) for r in ws.iter_rows(min_row=2, values_only=True)]
    neg = next(r for r in filas if r["Entidad"] == "Palabra clave negativa")
    assert neg["Operación"] == "Crear" and neg["Tipo de coincidencia"] == "Exacta negativa" and neg["Estado"] == "activada"
    assert neg["Producto"] == "Sponsored\xa0Products"
    rea = next(r for r in filas if r["Entidad"] == "Palabra clave")
    assert rea["Operación"] == "Actualizar" and rea["Estado"] == "activada" and rea["Puja"] == 0.45


def test_hoja_masiva_una_fila_por_campana(tmp_path):
    """Amazon rechazó una subida real (01/10/2026, 'ID duplicada'): estrategia y presupuesto de la misma
    campaña iban en dos filas. Deben ir en una."""
    from openpyxl import load_workbook
    import fuente_bulk
    from modelo import ESTRATEGIA, PRESUPUESTO, SOLO_BAJA, Cambio
    cuenta = cuenta_pinza()
    f = fuente_bulk.FuenteBulk(tmp_path / "x.xlsx", tmp_path)
    comun = dict(producto=PINZA, id_campana="C1", id_grupo=None, campana="Pinza", motivo="m", coincidencia="")
    f.aplicar(Cambio(tipo=ESTRATEGIA, clave="camp:C1", texto="", antes="x", despues=SOLO_BAJA, **comun), cuenta)
    f.aplicar(Cambio(tipo=PRESUPUESTO, clave="camp:C1", texto="", antes=7.0, despues=4.46, **comun), cuenta)
    ws = load_workbook(f.cerrar(HOY))[fuente_bulk.HOJA]
    cab = [c.value for c in ws[1]]
    filas = [dict(zip(cab, r)) for r in ws.iter_rows(min_row=2, values_only=True)]
    camp = [r for r in filas if r["Entidad"] == "Campaña"]
    assert len(camp) == 1
    assert camp[0]["Estrategia de pujas"] == SOLO_BAJA and camp[0]["Presupuesto diario"] == 4.46


def test_vocabulario_ajeno_negativa_de_frase(tmp_path, catalogo):
    """Juan (09/10): que pruebe negativas. Una búsqueda de algo que el producto no es se corta de golpe."""
    cuenta = cuenta_pinza()
    cuenta.terminos_maduros = True
    cuenta.terminos = [_termino("soporte movil coche magnetico iman", 1, 0.45),     # gasto muy por debajo del CPA
                       _termino("soporte movil coche magnetico", 1, 0.40),
                       _termino("soporte movil camion", 1, 0.40),
                       _termino("pinza camion fuerte", 1, 0.40, compras=1, ventas=11.24)]   # vende: 'camion' no se niega
    cuenta.negativas.append(Negativa("N0", "C1", "G1", "imán", "Frase negativa", ACTIVO))  # ya existe (con acento)
    res, api, _ = _correr(tmp_path, cuenta, [], catalogo)
    negs = [l for l in api.llamadas if l[0] == "negativa"]
    assert negs == [("negativa", "G1", "magnetico", "Frase negativa")]


def test_veto_del_agente_quita_un_cambio(tmp_path, catalogo, monkeypatch):
    import directivas
    monkeypatch.setattr(config, "VETOS", [{"tipo": NEGATIVA, "texto": "funda movil barata", "hasta": "2099-01-01",
                                           "motivo": "la vende un cliente de fundas"}])
    cuenta = cuenta_pinza()
    cuenta.terminos_maduros = True
    cuenta.terminos = [_termino("funda movil barata", 6, 10.0)]
    res, api, _ = _correr(tmp_path, cuenta, [], catalogo)
    assert not [l for l in api.llamadas if l[0] == "negativa"]
    assert any(m.startswith("vetado") for _, m in res["descartados"])
