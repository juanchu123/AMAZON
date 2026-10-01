"""
Pruebas sin conexión: un cliente SP-API falso simula Amazon y se recorre el
ciclo completo (auditar → brief → validar → paquete → aplicado → resultado →
memoria), más las reglas de seguridad una a una.

    python -m unittest discover -s tests
"""

import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402
from config import load_config  # noqa: E402
from limits import limits_from_schema  # noqa: E402
from listing_state import ListingState  # noqa: E402
from memory import Memory  # noqa: E402
from safety import ContentPolicy, normalize_backend, validate_proposal  # noqa: E402
from sp_api import SPAPIClient, WriteBlockedError  # noqa: E402
from keywords import parse_number  # noqa: E402

ASIN, SKU, MP = "B0DHYBY6MS", "5E-I8NY-S191", "A1RKKUPIHCS9HS"
LONG_TITLE = ("Soporte Movil Coche Universal Ajustable 360° para Rejilla Ventilación | Clip(Gancho) "
              "Super Estable y Seguro | Sujeta Movil Coche Compatible con Smartphones: iPhone, Samsung, Xiaomi y Más")

SCHEMA = {"properties": {
    "item_name": {"items": {"properties": {"value": {"maxLength": 200}}}},
    "bullet_point": {"maxItems": 10, "items": {"properties": {"value": {"maxLength": 500}}}},
    "generic_keyword": {"items": {"properties": {"value": {"maxLength": 500, "maxUtf8ByteLength": 249}}}},
    "product_description": {"items": {"properties": {"value": {"maxLength": 2000}}}},
    "item_highlights": {"items": {"properties": {"value": {"maxLength": 125}}}},
    "brand": {}, "gpsr_safety_attestation": {},
}}


def _attr(v):
    return [{"value": v, "language_tag": "es_ES", "marketplace_id": MP}]


class FakeClient:
    def __init__(self):
        self.title = LONG_TITLE
        self.patches = []

    def find_sku_for_asin(self, asin):
        return SKU

    def get_listing(self, sku):
        return {
            "summaries": [{"marketplaceId": MP, "productType": "PHONE_ACCESSORY", "status": ["BUYABLE", "DISCOVERABLE"]}],
            "attributes": {
                "item_name": _attr(self.title),
                "brand": _attr("FreshFinder"),
                "bullet_point": [_attr(f"Bullet {i}")[0] for i in range(1, 6)],
                "generic_keyword": _attr("porta smartphone automovil"),
            },
            "issues": [],
        }

    def get_catalog_item(self, asin):
        return {"images": [{"marketplaceId": MP, "images": [
            {"variant": "MAIN", "width": 1500, "height": 1500},
            {"variant": "PT01", "width": 1500, "height": 1500},
        ]}]}

    def get_product_type_schema(self, pt):
        return SCHEMA

    def fba_inventory(self, sku):
        return {"inventoryDetails": {"fulfillableQuantity": 40}}

    def sales_and_traffic(self, start, end):
        return {"salesAndTrafficByAsin": [{"childAsin": ASIN, "trafficByAsin": {
            "sessions": 120, "unitSessionPercentage": 6.5, "buyBoxPercentage": 100},
            "salesByAsin": {"unitsOrdered": 8, "orderedProductSales": {"amount": 103.9}}}]}

    def search_catalog(self, kw, page_token=None):
        return {"items": [{"asin": ASIN}] if "rejilla" in kw else [{"asin": "B0OTHER0001"}]}

    def validate_patch_preview(self, sku, pt, patches):
        self.patches.append(patches)
        return {"status": "VALID", "issues": []}


class AgentFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        csv = self.tmp / "ads.csv"
        csv.write_text(
            "Palabra clave,Clics,Compras,Impresiones\n"
            "soporte movil coche rejilla,12,2,900\n"
            "soporte magnetico coche,6,1,400\n"
            "funda movil,3,0,100\n", encoding="utf-8")
        cfg = json.loads((Path(__file__).resolve().parent.parent / "config.example.json").read_text())
        cfg["fuentes_keywords"] = {"csv_ads": [str(csv)]}
        (self.tmp / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        self.cfg = load_config(self.tmp / "config.json")
        self.client = FakeClient()
        self.mem = Memory(self.cfg.logs_dir)

    def test_full_cycle(self):
        hoy = date(2026, 10, 1)
        report = main.cmd_auditar(self.cfg, self.client, None, enviar_email=False,
                                  comprobar_indexacion=True, hoy=hoy).read_text()
        self.assertIn("puede reescribirlo con IA", report)          # título > 75 sin Brand Registry
        self.assertIn("brief_B0DHYBY6MS_20261001.md", report)
        brief = (self.cfg.trabajo_dir / "brief_B0DHYBY6MS_20261001.md").read_text()
        self.assertIn("**titulo**", brief)
        self.assertIn("soporte movil coche rejilla", brief)

        # Cowork redacta una propuesta mala -> rechazada
        mala = {"asin": ASIN, "campo": "titulo", "es_correccion": True,
                "valor_nuevo": "FreshFinder Soporte Movil Coche ¡OFERTA! el mejor compatible Lamicall",
                "motivo": "m", "riesgo": "r", "metrica_a_vigilar": "conv"}
        code, msg, _ = main.validate_and_package(self.cfg, self.client, self.mem, mala, "cowork", False, hoy)
        self.assertEqual(code, 1)
        self.assertIn("oferta", msg)
        self.assertIn("Lamicall", msg)

        buena = dict(mala, valor_nuevo="FreshFinder Soporte Movil Coche Rejilla Ventilación 360° con Pinza Estable",
                     keywords_objetivo=["soporte movil coche rejilla"])
        code, msg, pkg = main.validate_and_package(self.cfg, self.client, self.mem, buena, "cowork", True, hoy)
        self.assertEqual(code, 0, msg)
        self.assertIn("VALIDATION_PREVIEW", pkg.read_text())
        self.assertEqual(self.client.patches[0][0]["path"], "/attributes/item_name")
        change = self.mem.pending_proposals(ASIN)[0]
        self.assertEqual(change["valor_antes"], LONG_TITLE)  # estado anterior guardado para revertir

        # Un segundo cambio mientras hay uno pendiente -> bloqueado
        otra = {"asin": ASIN, "campo": "backend", "valor_nuevo": "sujeta telefono", "motivo": "m",
                "riesgo": "r", "metrica_a_vigilar": "c"}
        code, msg, _ = main.validate_and_package(self.cfg, self.client, self.mem, otra, "cowork", False, hoy)
        self.assertEqual(code, 1)
        self.assertIn("Un cambio cada vez", msg)

        # Juan lo publica; la siguiente auditoría lo detecta sola
        self.client.title = buena["valor_nuevo"]
        main.cmd_auditar(self.cfg, self.client, None, False, True, hoy + timedelta(days=7))
        change = self.mem.get_change(change["id"])
        self.assertEqual(change["estado"], "aplicado")
        events = self.mem.ads_events_file.read_text()
        self.assertIn("cambio_previsto", events)
        self.assertIn("cambio_aplicado", events)

        # Cadencia: a los 7 días sin evaluación, no se puede tocar otro campo
        bloqueos = self.mem.check_change_allowed(ASIN, "backend", False, self.cfg.reglas, hoy + timedelta(days=7))
        self.assertTrue(any("esperar 14 días" in b for b in bloqueos))

        # El otro agente evalúa
        self.mem.record_outcome(change["id"], "empeora", ventana="7-14d",
                                metricas_despues={"conversion_pct": 4.1}, agente="evaluador")
        resumen = self.mem.summary(ASIN)
        self.assertEqual(resumen["no_repetir"][0]["valor"], buena["valor_nuevo"])
        self.assertEqual(resumen["aciertos_por_campo"]["titulo"]["empeora"], 1)
        report = main.cmd_auditar(self.cfg, self.client, None, False, False, hoy + timedelta(days=15)).read_text()
        self.assertIn(f"python main.py revertir {change['id']}", report)

    def test_unregistered_title_change_is_flagged(self):
        hoy = date(2026, 10, 1)
        main.cmd_auditar(self.cfg, self.client, None, False, False, hoy)
        self.client.title = "Soporte de móvil para coche universal"  # p. ej. la IA de Amazon
        report = main.cmd_auditar(self.cfg, self.client, None, False, False, hoy + timedelta(days=7)).read_text()
        self.assertIn("no ha hecho este agente", report)
        self.assertIn("titulo_cambiado_fuera_del_agente", self.mem.ads_events_file.read_text())


class SafetyTest(unittest.TestCase):
    def setUp(self):
        self.limits = limits_from_schema(SCHEMA)
        self.policy = ContentPolicy("FreshFinder", ["Lamicall"], ["iPhone", "Samsung"], [], 5)
        self.state = ListingState(asin=ASIN, sku=SKU, marketplace_id=MP, product_type="X",
                                  titulo="FreshFinder Soporte Movil Coche Rejilla", item_highlights="",
                                  bullets=["Agarre firme"] * 5, backend="")

    def _v(self, campo, valor, **kw):
        p = {"asin": ASIN, "campo": campo, "valor_nuevo": valor, "motivo": "m", "riesgo": "r",
             "metrica_a_vigilar": "c", **kw}
        return validate_proposal(p, self.state, self.limits, self.policy)

    def test_title_limit_uses_most_conservative(self):
        self.assertEqual(self.limits.titulo.max_chars, 75)  # el esquema dice 200, la norma 75
        self.assertIn("esquema SP-API", self.limits.titulo.fuente)
        r = self._v("titulo", "FreshFinder " + "soporte coche rejilla " * 5)
        self.assertFalse(r.ok)

    def test_backend_bytes_and_cleanup(self):
        r = self._v("backend", "Porta-móvil, de la sujeción coche coche iPhone")
        self.assertFalse(r.ok)  # marca de dispositivo en backend
        clean, avisos = normalize_backend("Porta, de soporte sujeción sujeción coche", "Soporte Movil Coche", self.policy)
        self.assertEqual(clean, "porta sujeción")
        r = self._v("backend", "ñ" * 130)  # 260 bytes aunque solo 130 caracteres
        self.assertFalse(r.ok)
        self.assertTrue(any("bytes" in e for e in r.errores))

    def test_claims_need_legal(self):
        r = self._v("item_highlights", "Plástico ABS homologado, compatible con iPhone y Samsung")
        self.assertFalse(r.ok)
        self.policy.claims_confirmados.append("homologado")
        r = self._v("item_highlights", "Plástico ABS homologado, compatible con iPhone y Samsung")
        self.assertTrue(r.ok, r.errores)

    def test_bullets_count(self):
        self.assertFalse(self._v("bullets", ["A", "B"]).ok)
        self.assertTrue(self._v("bullets", [f"VENTAJA {i}: dato real del producto" for i in range(5)]).ok)

    def test_fake_correction_rejected(self):
        r = self._v("titulo", "FreshFinder Soporte Movil Coche Rejilla Pinza", es_correccion=True)
        self.assertFalse(r.ok)
        self.assertTrue(any("corrección" in e for e in r.errores))


class ClientGuardTest(unittest.TestCase):
    def test_no_writes(self):
        for method, path, params in [("PATCH", "/listings/2021-08-01/items/S/K", {}),
                                     ("PUT", "/listings/2021-08-01/items/S/K", {}),
                                     ("DELETE", "/listings/2021-08-01/items/S/K", {}),
                                     ("POST", "/feeds/2021-06-30/feeds", {})]:
            with self.assertRaises(WriteBlockedError):
                SPAPIClient._guard(method, path, params)
        SPAPIClient._guard("PATCH", "/listings/2021-08-01/items/S/K", {"mode": "VALIDATION_PREVIEW"})
        SPAPIClient._guard("POST", "/reports/2021-06-30/reports", None)


class ParseTest(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(parse_number("1.47"), 1.47)
        self.assertEqual(parse_number("0,0227"), 0.0227)
        self.assertEqual(parse_number("1.234,56 €"), 1234.56)
        self.assertEqual(parse_number("—"), 0.0)


if __name__ == "__main__":
    unittest.main()
