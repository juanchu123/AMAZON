"""Tests del agente autónomo con una API de Amazon FALSA (nunca toca la cuenta real).

    python -m pytest tests/ -q
"""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agente
import config
import learner
import presupuesto
import safety
from documento import Documento
from modelo import (ACTIVO, KEYWORD, NUEVA_KEYWORD, PAUSADO, PAUSAR, PUJA, Anuncio, Campana, Cuenta,
                    Elemento, Grupo, Metricas)
from prediccion import Catalogo

PINZA, SKU = "B0DCZS1NR6", "O8-5W7J-DSK1"
HOY = date(2026, 10, 20)


@pytest.fixture(scope="module")
def catalogo():
    return Catalogo()


class APIFalsa:
    """Imita ads_api.AmazonAdsAPI: guarda el estado en memoria y 'relee' de ahí."""

    def __init__(self, cuenta, diario, romper_pujas=False):
        self.cuenta, self.diario, self.romper_pujas = cuenta, diario, romper_pujas
        self.llamadas = []
        self.siguiente_id = 9000

    def leer_cuenta(self, hoy):
        self.cuenta.fecha = hoy
        return self.cuenta

    def metricas_diarias(self, desde, hasta):
        return [f for f in self.diario if desde <= date.fromisoformat(f["Fecha"]) <= hasta]

    def cambiar_puja(self, el, puja):
        self.llamadas.append(("puja", el.clave, puja))
        if self.romper_pujas:
            return False, "Releído en Amazon: no coincide"
        self.cuenta.elementos[el.clave].puja = puja
        return True, "Releído en Amazon: coincide"

    def pausar(self, el):
        self.llamadas.append(("pausar", el.clave))
        self.cuenta.elementos[el.clave].estado = PAUSADO
        return True, "Releído en Amazon: coincide"

    def cambiar_presupuesto(self, id_c, eur):
        self.llamadas.append(("presupuesto", id_c, eur))
        self.cuenta.campanas[id_c].presupuesto = eur
        return True, "Releído en Amazon: coincide"

    def cambiar_estrategia(self, campana, estrategia):
        self.llamadas.append(("estrategia", campana.id, estrategia))
        self.cuenta.campanas[campana.id].estrategia_pujas = estrategia
        return True, "Releído en Amazon: coincide"

    def crear_keyword(self, id_c, id_g, texto, coinc, puja):
        self.llamadas.append(("keyword", id_g, texto, puja))
        self.siguiente_id += 1
        k = str(self.siguiente_id)
        self.cuenta.elementos[k] = Elemento(k, KEYWORD, id_c, id_g, texto, coinc, ACTIVO, puja)
        return True, k, "Creado y releído en Amazon"

    def crear_objetivo_asin(self, *a):
        raise AssertionError("no esperado")

    def crear_campana(self, nombre, presupuesto, sku, nombre_grupo, puja_grupo, id_cartera, hoy):
        self.llamadas.append(("campana", nombre, presupuesto, sku))
        self.cuenta.campanas["CN"] = Campana("CN", nombre, ACTIVO, presupuesto)
        self.cuenta.grupos["GN"] = Grupo("GN", "CN", nombre_grupo, ACTIVO, puja_grupo)
        self.cuenta.anuncios.append(Anuncio("AN", "CN", "GN", "?", sku, ACTIVO))
        return True, {"id_campana": "CN", "id_grupo": "GN", "id_anuncio": "AN"}, "Campaña, grupo y anuncio creados"

    def pausar_campana(self, id_c):
        return True, "ok"


def cuenta_pinza(n_keywords=12, estado_campana=ACTIVO, servicio="AD_ELIGIBLE"):
    c = Cuenta(fecha=HOY)
    c.campanas["C1"] = Campana("C1", "Pinza - Principal V2", estado_campana, 7.0)
    c.grupos["G1"] = Grupo("G1", "C1", "Pinza - Principal V2", ACTIVO, 0.40)
    c.anuncios.append(Anuncio("A1", "C1", "G1", PINZA, SKU, ACTIVO, servicio))
    textos = ["soporte movil coche pinza", "soporte movil pinza", "pinza movil coche", "soporte coche pinza salpicadero",
              "soporte pinza parasol", "soporte movil coche con pinza ajustable", "pinza soporte telefono coche",
              "soporte movil retrovisor pinza", "soporte movil coche pinza 360", "soporte pinza antideslizante",
              "soporte movil pinza estable", "sujeta movil coche pinza"]
    for i in range(n_keywords):
        k = f"K{i}"
        c.elementos[k] = Elemento(k, KEYWORD, "C1", "G1", textos[i], "Frase", ACTIVO, 0.40)
    return c


def filas_diarias(clave, dias, clics_dia, coste_dia, compras_por_dia=None):
    """dias: fechas hacia atrás desde ayer."""
    out = []
    for i in range(1, dias + 1):
        d = HOY - timedelta(days=i)
        out.append({"Fecha": d.isoformat(), "Clave": clave, "ID campaña": "C1", "Impresiones": clics_dia * 30,
                    "Clics": clics_dia, "Coste (€)": coste_dia,
                    "Compras": (compras_por_dia or {}).get(i, 0), "Ventas (€)": 11.24 * (compras_por_dia or {}).get(i, 0)})
    return out


def correr(tmp_path, cuenta, diario, catalogo, simular=False, **kw):
    doc = Documento(tmp_path / "doc.xlsx")
    api = APIFalsa(cuenta, diario, **kw)
    res = agente.ejecutar(agente.FuenteAPI(api, doc), doc, catalogo, HOY, datetime(2026, 10, 20, 9, 0),
                          simular=simular, investigar="no", log=lambda *_: None)
    return res, api, Documento(tmp_path / "doc.xlsx")


# ---------------------------------------------------------------- madurez y series
def test_madurez_7_dias(tmp_path):
    doc = Documento(tmp_path / "d.xlsx")
    doc.guardar_diario(filas_diarias("K0", 20, 2, 0.5))
    s = doc.series()
    assert s.acumulado("K0", HOY).clics == 40
    # maduro: solo días con más de 7 días de antigüedad (HOY-8 y anteriores = 13 días)
    assert s.maduro("K0", HOY).clics == 26


def test_stop_loss_pausa_con_20_clics_maduros_sin_venta(tmp_path, catalogo):
    cuenta = cuenta_pinza()
    diario = filas_diarias("K0", 20, 2, 0.1)           # 26 clics maduros, 0 ventas, 2,60 €
    res, api, doc = correr(tmp_path, cuenta, diario, catalogo)
    assert ("pausar", "K0") in api.llamadas
    t = [t for t in doc.hojas["Tickets"] if t["Tipo"] == PAUSAR]
    assert t and t[0]["Estado"] == "confirmado"
    # el hueco se rellena con una candidata (≤ 30 % de ACOS predicho)
    nuevas = [c for c in res["cambios"] if c.tipo == NUEVA_KEYWORD and c.id_grupo == "G1"]
    assert len(nuevas) == 1 and nuevas[0].estado == "confirmado"
    for c in nuevas:
        assert c.extra["acos_pred"] <= config.ACOS_MAX_KEYWORD_NUEVA


def test_stop_loss_4_euros(tmp_path, catalogo):
    diario = filas_diarias("K0", 12, 1, 0.9)            # 5 clics maduros pero 4,50 € maduros
    res, api, _ = correr(tmp_path, cuenta_pinza(), diario, catalogo)
    assert ("pausar", "K0") in api.llamadas


def test_una_venta_libra_del_stop_loss(tmp_path, catalogo):
    diario = filas_diarias("K0", 20, 2, 0.1, compras_por_dia={2: 1})   # venta reciente (clic aún no maduro)
    res, api, _ = correr(tmp_path, cuenta_pinza(), diario, catalogo)
    assert ("pausar", "K0") not in api.llamadas


def test_ronda_espera_3_dias_y_10_clics(tmp_path, catalogo):
    diario = filas_diarias("K0", 2, 3, 0.1)             # solo 2 días de datos
    res, api, doc = correr(tmp_path, cuenta_pinza(), diario, catalogo)
    assert not [l for l in api.llamadas if l[1] == "K0"]
    fila = next(f for f in doc.hojas["Segmentación"] if f["Clave"] == "K0")
    assert fila["Decisión de esta ronda"].startswith("Esperar")


# ---------------------------------------------------------------- puja
def test_puja_formula_y_sin_techo(tmp_path, catalogo):
    # 60 clics maduros y 12 compras: conversión muy alta -> la puja SUBE (sin tope de ±20 %)
    compras = {i: 1 for i in range(8, 20)}
    diario = filas_diarias("K0", 20, 3, 0.4, compras_por_dia=compras)
    res, api, doc = correr(tmp_path, cuenta_pinza(), diario, catalogo)
    c = next(c for c in res["cambios"] if c.tipo == PUJA and c.clave == "K0")
    prod = catalogo.producto(PINZA)
    mad = Metricas(clics=39, compras=12)
    p = catalogo.p_compra(PINZA, "soporte movil coche pinza", "Frase", mad)
    esperado = round(p * prod.ticket * (0.30 + 0.05 * 0.5), 2)
    assert c.despues == esperado
    assert c.despues > 0.40 * 1.2                       # más del +20 %: no hay techo artificial
    assert c.estado == "confirmado"


def test_puja_nunca_por_debajo_de_002():
    assert safety.puja_valida(0.001, 12.0) == 0.02
    assert safety.puja_valida(50.0, 12.0) is None       # imposible que sea rentable: error de datos


def test_cambio_no_confirmado_queda_fallido(tmp_path, catalogo):
    compras = {i: 1 for i in range(8, 20)}
    diario = filas_diarias("K0", 20, 3, 0.4, compras_por_dia=compras)
    res, api, doc = correr(tmp_path, cuenta_pinza(), diario, catalogo, romper_pujas=True)
    t = [t for t in doc.hojas["Tickets"] if t["Tipo"] == PUJA and t["Clave"] == "K0"]
    assert t[0]["Estado"] == "fallido"
    # los demás cambios siguen adelante (independencia)
    assert any(t["Estado"] == "confirmado" for t in doc.hojas["Tickets"]) or len(doc.hojas["Tickets"]) == 1


# ---------------------------------------------------------------- huecos y 12 keywords
def test_rellena_hasta_12(tmp_path, catalogo):
    res, api, _ = correr(tmp_path, cuenta_pinza(n_keywords=9), [], catalogo)
    nuevas = [c for c in res["cambios"] if c.tipo == NUEVA_KEYWORD and c.id_grupo == "G1"]
    assert 1 <= len(nuevas) <= 3
    assert all(c.estado == "confirmado" and c.clave.isdigit() for c in nuevas)   # clave = id real creado
    assert all("pinza" in c.texto for c in nuevas)
    assert all(c.extra["acos_pred"] <= 0.30 for c in nuevas)
    textos = {c.texto for c in nuevas}
    assert len(textos) == len(nuevas)


# ---------------------------------------------------------------- cuenta parada (§2.9-bis)
def test_todo_en_pausa_para_y_avisa(tmp_path, catalogo):
    diario = filas_diarias("K0", 20, 2, 0.1)
    res, api, doc = correr(tmp_path, cuenta_pinza(estado_campana=PAUSADO), diario, catalogo)
    assert res["parado"]
    assert api.llamadas == []                           # no toca NADA
    assert any(a["Tipo"] == "cuenta_parada" for a in doc.hojas["Alertas"])
    assert list(config.CORREOS_PENDIENTES.glob("*.eml"))


def test_problema_de_pago_para(tmp_path, catalogo):
    cuenta = cuenta_pinza()
    cuenta.campanas["C1"].estado_servicio = "ADVERTISER_PAYMENT_FAILURE"
    res, api, _ = correr(tmp_path, cuenta, [], catalogo)
    assert res["parado"] and api.llamadas == []


def test_anuncio_no_elegible_no_se_toca(tmp_path, catalogo):
    diario = filas_diarias("K0", 20, 2, 0.1)
    res, api, doc = correr(tmp_path, cuenta_pinza(servicio="NOT_BUYABLE"), diario, catalogo)
    assert not [l for l in api.llamadas if l[0] in ("pausar", "puja") or (l[0] == "keyword" and l[1] == "G1")]
    assert any("no elegible" in m.lower() for _, _, m in res["decision"].alertas)


# ---------------------------------------------------------------- presupuesto (§2.5)
def test_presupuesto_nunca_pasa_del_tope(catalogo):
    c = Cuenta(fecha=HOY)
    for i, (nombre, asin) in enumerate([("Pinza - Principal V2", PINZA), ("Rejilla - Principal V2", "B0DHYBY6MS"),
                                        ("Pou - Principal V2", "B0CPHXXHRQ"), ("Pinza - Pruebas", PINZA)]):
        c.campanas[f"C{i}"] = Campana(f"C{i}", nombre, ACTIVO, 7.0)
        c.grupos[f"G{i}"] = Grupo(f"G{i}", f"C{i}", nombre, ACTIVO, 0.3)
        c.anuncios.append(Anuncio(f"A{i}", f"C{i}", f"G{i}", asin, "x", ACTIVO))
    doc = Documento("/nonexistent/doc.xlsx")
    cambios, filas, _, tope = presupuesto.planificar(c, doc, doc.series(), catalogo, HOY, gasto_mes=None)
    objetivo = {f["Campaña"]: f["Presupuesto objetivo (€)"] for f in filas}
    assert sum(objetivo.values()) <= config.TOPE_MENSUAL_EUR / 31 + 0.01
    # una sola bolsa: sin fondo fijo de experimentación, el reparto va por puntuación
    assert objetivo["Pinza - Principal V2"] > objetivo["Rejilla - Principal V2"]   # mejor ACOS histórico
    assert all(v >= 1.0 for v in objetivo.values())


def test_sin_subidas_si_el_mes_va_pasado():
    assert not safety.permite_subidas(date(2026, 10, 11), gasto_mes=400.0)   # 40 €/día -> 1240 €
    assert safety.permite_subidas(date(2026, 10, 11), gasto_mes=200.0)
    assert safety.presupuesto_diario_total(date(2026, 10, 30), gasto_mes=830.0) == 5.0   # quedan 10 € / 2 días


# ---------------------------------------------------------------- aprendizaje
def test_learner_veredicto_y_agresividad(tmp_path, catalogo):
    doc = Documento(tmp_path / "d.xlsx")
    doc.hojas["Tickets"].append({"Ticket": "T-0001", "Fecha": (HOY - timedelta(days=20)).isoformat(), "Tipo": PUJA,
                                 "Clave": "K0", "Producto (ASIN)": PINZA, "Palabra clave / segmentación": "soporte pinza",
                                 "Coincidencia": "Frase", "Antes": 0.3, "Después": 0.4, "Estado": "confirmado"})
    # después del cambio: 2 clics/día y 1 compra cada 2 días -> ACOS bajo -> mejora
    doc.guardar_diario(filas_diarias("K0", 19, 2, 0.4, compras_por_dia={i: 1 for i in range(8, 20, 2)}))
    assert learner.evaluar_pendientes(doc, doc.series(), HOY) == 1
    assert doc.hojas["Tickets"][0]["Veredicto"] == "mejora"
    assert learner.agresividad(doc, PINZA, "soporte pinza", "Frase") == 1.0
    assert learner.agresividad(doc, PINZA, "otra", "Frase") == 0.5


# ---------------------------------------------------------------- documento
def test_documento_atomico_conserva_competencia(tmp_path):
    doc = Documento(tmp_path / "d.xlsx")
    doc.sembrar(HOY)
    assert doc.hojas["Competencia"]
    doc.hojas["Competencia"][0]["Confirmado por Juan"] = "Sí"
    doc.guardar()
    doc2 = Documento(tmp_path / "d.xlsx")
    assert doc2.hojas["Competencia"][0]["Confirmado por Juan"] == "Sí"
    assert doc2.competidores(doc2.hojas["Competencia"][0]["Producto (ASIN)"])
    assert not list(tmp_path.glob(".tmp_*"))


def test_simulacion_no_toca_ni_registra(tmp_path, catalogo):
    diario = filas_diarias("K0", 20, 2, 0.1)
    res, api, doc = correr(tmp_path, cuenta_pinza(), diario, catalogo, simular=True)
    assert api.llamadas == []
    assert doc.hojas["Tickets"] == []
    assert any(c.estado == "simulado" for c in res["cambios"])


# ---------------------------------------------------------------- ads_api con HTTP falso
class Resp:
    def __init__(self, status, datos=None, headers=None, contenido=None):
        self.status_code, self._d, self.headers = status, datos, headers or {}
        self.text = json.dumps(datos) if datos is not None else ""
        self.content = contenido

    def json(self):
        return self._d

    def raise_for_status(self):
        pass


class SesionFalsa:
    def __init__(self, puja_real):
        self.puja_real, self.puts = puja_real, 0

    def post(self, url, data=None, timeout=None):
        return Resp(200, {"access_token": "tok", "expires_in": 3600})

    def request(self, metodo, url, headers=None, data=None, timeout=None):
        if metodo == "PUT":
            self.puts += 1
            return Resp(207, {"keywords": {"success": [{"index": 0, "keywordId": "K1"}], "error": []}})
        if url.endswith("/sp/keywords/list"):
            return Resp(200, {"keywords": [{"keywordId": "K1", "bid": self.puja_real, "state": "ENABLED"}]})
        raise AssertionError(url)

    def get(self, url, timeout=None):
        raise AssertionError(url)


def test_ads_api_verifica_releyendo():
    from ads_api import AmazonAdsAPI
    el = Elemento("K1", KEYWORD, "C1", "G1", "x", "Frase", ACTIVO, 0.3)
    api = AmazonAdsAPI("id", "secret", "refresh", profile_id="1", sesion=SesionFalsa(puja_real=0.45))
    assert api.cambiar_puja(el, 0.45)[0] is True
    api = AmazonAdsAPI("id", "secret", "refresh", profile_id="1", sesion=SesionFalsa(puja_real=0.30))
    ok, det = api.cambiar_puja(el, 0.45)
    assert ok is False and "no coincide" in det
    assert api.http.puts == 2                            # un reintento y se da por fallido


# ---------------------------------------------------------------- hoja masiva (sin API)
def _descarga(ruta, puja_k0=0.40, estado_k0="Activado", clics_k0=30):
    from openpyxl import load_workbook
    import fuente_bulk
    wb = load_workbook(fuente_bulk.PLANTILLA)
    ws = wb[fuente_bulk.HOJA]
    cols = [c.value for c in ws[1]] + ["Impresiones", "Clics", "Gasto", "Ventas", "Pedidos"]
    for i, c in enumerate(cols, 1):
        ws.cell(row=1, column=i, value=c)

    def fila(**kv):
        ws.append([kv.get(c) for c in cols])

    fila(Producto="Sponsored Products", Entidad="Campaña", **{"ID de la campaña": "C1", "Nombre de la campaña": "Pinza - Principal V2",
         "Estado": "Activado", "Presupuesto diario": 7, "Tipo de segmentación": "Manual"})
    fila(Entidad="Grupo de anuncios", **{"ID de la campaña": "C1", "ID del grupo de anuncios": "G1",
         "Nombre del grupo de anuncios": "Pinza", "Estado": "Activado", "Puja predeterminada del grupo de anuncios": 0.4})
    fila(Entidad="Anuncio de producto", **{"ID de la campaña": "C1", "ID del grupo de anuncios": "G1", "ID del anuncio": "A1",
         "SKU": SKU, "Estado": "Activado"})
    ws.cell(row=ws.max_row, column=len(cols) + 1, value="ASIN (Solo informativo)")
    ws.cell(row=1, column=len(cols) + 1, value="ASIN (Solo informativo)")
    ws.cell(row=ws.max_row, column=len(cols) + 1, value=PINZA)
    fila(Entidad="Palabra clave", **{"ID de la campaña": "C1", "ID del grupo de anuncios": "G1", "ID de palabra clave": "K0",
         "Texto de palabra clave": "soporte movil coche pinza", "Tipo de coincidencia": "Frase", "Estado": estado_k0,
         "Puja": puja_k0, "Clics": clics_k0, "Gasto": 6.0, "Pedidos": 0, "Ventas": 0})
    wb.save(ruta)


def test_hoja_masiva_ida_y_vuelta(tmp_path, catalogo, monkeypatch):
    import fuente_bulk
    doc = Documento(tmp_path / "doc.xlsx")
    # una foto de hace 10 días con los mismos 30 clics -> ya son maduros hoy
    doc.hojas["Seguimiento"].append({"Fecha": (HOY - timedelta(days=10)).isoformat(), "Clave": "K0", "ID campaña": "C1",
                                     "Clics": 30, "Coste (€)": 6.0, "Compras": 0, "Ventas (€)": 0})
    doc.guardar()
    _descarga(tmp_path / "descarga.xlsx")
    doc = Documento(tmp_path / "doc.xlsx")
    fuente = fuente_bulk.FuenteBulk(tmp_path / "descarga.xlsx", salida_dir=tmp_path)
    res = agente.ejecutar(fuente, doc, catalogo, HOY, datetime(2026, 10, 20, 9), investigar="no", log=lambda *_: None)
    pausa = [c for c in res["cambios"] if c.tipo == PAUSAR]
    assert pausa and pausa[0].estado == "enviado_bulk"
    assert res["bulk"] and res["bulk"].exists()
    # siguiente descarga: Juan subió la hoja -> la keyword aparece en pausa -> ticket confirmado
    _descarga(tmp_path / "descarga2.xlsx", estado_k0="En pausa")
    doc = Documento(tmp_path / "doc.xlsx")
    fuente = fuente_bulk.FuenteBulk(tmp_path / "descarga2.xlsx", salida_dir=tmp_path)
    agente.ejecutar(fuente, doc, catalogo, HOY + timedelta(days=1), datetime(2026, 10, 21, 9), investigar="no",
                    log=lambda *_: None)
    doc = Documento(tmp_path / "doc.xlsx")
    t = next(t for t in doc.hojas["Tickets"] if t["Tipo"] == PAUSAR)
    assert t["Estado"] == "confirmado"


# ---------------------------------------------------------------- campaña nueva (§2.6)
def test_abre_campana_para_producto_sin_campana(tmp_path, catalogo, monkeypatch):
    # solo existe la campaña de la pinza y la rejilla (en el catálogo, sin campaña en esta cuenta de
    # prueba) tiene candidatas ≤ 30 % (sin calibrar el CPC: aquí se prueba la apertura)
    monkeypatch.setattr(catalogo.producto("B0DHYBY6MS"), "factor_cpc", 1.0)
    res, api, doc = correr(tmp_path, cuenta_pinza(), [], catalogo)
    creadas = [l for l in api.llamadas if l[0] == "campana"]
    assert len(creadas) == 1                              # como mucho una por ronda
    _, nombre, eur, sku = creadas[0]
    assert "Rejilla" in nombre and sku == "5E-I8NY-S191"
    assert eur >= config.PRESUPUESTO_MIN_CAMPANA_NUEVA
    kws = [l for l in api.llamadas if l[0] == "keyword" and l[1] == "GN"]
    assert len(kws) >= config.MIN_KEYWORDS_CAMPANA_NUEVA and not any("pinza" in l[2] for l in kws)
    t = next(t for t in doc.hojas["Tickets"] if t["Tipo"] == "crear_campaña")
    assert t["Estado"] == "confirmado" and t["ID campaña"] == "CN"
    # la suma de presupuestos no pasa del tope del día
    total = sum(c.presupuesto for c in api.cuenta.campanas.values() if c.estado == ACTIVO)
    assert total <= safety.presupuesto_diario_total(HOY, None) + 0.01


def test_cpc_calibrado_con_lo_pagado_de_verdad(catalogo):
    rejilla, pinza = catalogo.producto("B0DHYBY6MS"), catalogo.producto(PINZA)
    assert rejilla.factor_cpc == pytest.approx(2.35, abs=0.01)             # pagado 2,35 × la puja rec. baja
    assert pinza.factor_cpc == pytest.approx(1.38, abs=0.01)
    assert catalogo.cpc_para(PINZA, "soporte pinza", rec_propia=0.30) == pytest.approx(0.30 * pinza.factor_cpc)
    # sin datos suficientes el factor es 1: nunca abarata la predicción
    assert catalogo.producto("B0F746MFPQ").factor_cpc == 1.0


def test_no_abre_campana_sin_dinero(tmp_path, catalogo, monkeypatch):
    # con un tope de 100 €/mes (3,2 €/día) y tres campañas, a una cuarta le tocaría < 2,50 €/día
    monkeypatch.setattr(config, "TOPE_MENSUAL_EUR", 100.0)
    cuenta = cuenta_pinza()
    for i in range(2):
        cuenta.campanas[f"P{i}"] = Campana(f"P{i}", f"Pinza - Pruebas {i}", ACTIVO, 3.0)
        cuenta.grupos[f"PG{i}"] = Grupo(f"PG{i}", f"P{i}", "Pruebas", ACTIVO, 0.3)
        cuenta.anuncios.append(Anuncio(f"PA{i}", f"P{i}", f"PG{i}", PINZA, SKU, ACTIVO))
    res, api, _ = correr(tmp_path, cuenta, [], catalogo)
    assert not [l for l in api.llamadas if l[0] == "campana"]


# ---------------------------------------------------------------- investigación (LLM falso)
class _Bloque:
    def __init__(self, texto):
        self.type, self.text = "text", texto


class _Respuesta:
    def __init__(self, texto, stop="end_turn"):
        self.content, self.stop_reason = [_Bloque(texto)], stop


class ClaudeFalso:
    def __init__(self):
        self.llamadas = []
        self.messages = self

    def create(self, **kw):
        self.llamadas.append(kw)
        if "tools" in kw:   # 1ª fase: investigación con búsqueda web (se pausa una vez)
            return _Respuesta("notas...", stop="pause_turn" if len(self.llamadas) == 1 else "end_turn")
        return _Respuesta(json.dumps({"candidatas": [
            {"palabra_clave": "Soporte Móvil Coche Pinza Salpicadero", "motivo": "muy buscada", "volumen_estimado": "alto"},
            {"palabra_clave": "soporte movil coche pinza", "motivo": "ya la tiene", "volumen_estimado": "alto"},
            {"palabra_clave": "soporte móvil coche pinza salpicadero", "motivo": "repetida", "volumen_estimado": "alto"},
        ]}))


def test_investigacion_solo_devuelve_datos_filtrados(tmp_path, catalogo):
    import investigacion
    cliente = ClaudeFalso()
    cands, _ = investigacion.investigar(catalogo.producto(PINZA), ["soporte movil coche pinza"], cliente=cliente)
    assert [c["palabra_clave"] for c in cands] == ["soporte móvil coche pinza salpicadero"]   # sin repetidas ni existentes
    assert len(cliente.llamadas) == 3                                       # pause_turn reanudado + fase JSON
    assert "output_config" in cliente.llamadas[-1] and "tools" not in cliente.llamadas[-1]
    doc = Documento(tmp_path / "d.xlsx")
    investigacion.guardar(doc, PINZA, HOY, cands, None)
    assert doc.investigacion(PINZA)[1][0]["Palabra clave"] == "soporte móvil coche pinza salpicadero"
