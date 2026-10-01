"""
sp_api.py
---------
Cliente mínimo de la Selling Partner API (Amazon Seller). Es la ÚNICA pieza
del agente que habla con Amazon.

Regla de seguridad del documento: "Nada se publica sin aprobación explícita
de Juan" y Juan publica a mano. Por eso este cliente es de SOLO LECTURA y lo
impone en código (_guard), no por convención:
  - GET: siempre permitido (leer listing, catálogo, inventario, informes...).
  - POST: solo para PEDIR un informe (/reports/...), que no toca el catálogo.
  - PATCH: solo con mode=VALIDATION_PREVIEW, que valida un cambio contra las
    reglas de Amazon SIN enviarlo. Cualquier otro PATCH/PUT/DELETE se rechaza
    antes de salir de este proceso.
"""

import gzip
import json
import time
from datetime import datetime, timezone
from urllib.parse import quote

import requests

LWA_URL = "https://api.amazon.com/auth/o2/token"
USER_AGENT = "FreshFinderListingAgent/1.0 (Language=Python)"


class SPAPIError(RuntimeError):
    pass


class WriteBlockedError(RuntimeError):
    """Se ha intentado una escritura real en Amazon. Nunca debería pasar."""


class SPAPIClient:
    def __init__(self, client_id, client_secret, refresh_token, seller_id,
                 endpoint, marketplace_id, idioma="es_ES", session=None, sleep=time.sleep):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.seller_id = seller_id
        self.endpoint = endpoint.rstrip("/")
        self.marketplace_id = marketplace_id
        self.idioma = idioma
        self.http = session or requests.Session()
        self._sleep = sleep
        self._token = None
        self._token_exp = 0.0

    # ------------------------------------------------------------------ base
    def _access_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        r = self.http.post(LWA_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }, timeout=30)
        if r.status_code != 200:
            raise SPAPIError(
                f"No se pudo obtener el token de acceso (HTTP {r.status_code}). "
                "Revisa SP_API_CLIENT_ID / SECRET / REFRESH_TOKEN o si la autorización de la app ha caducado."
            )
        data = r.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + int(data.get("expires_in", 3600))
        return self._token

    @staticmethod
    def _guard(method: str, path: str, params: dict | None) -> None:
        method = method.upper()
        if method == "GET":
            return
        if method == "POST" and path.startswith("/reports/2021-06-30/reports"):
            return
        if method == "PATCH" and (params or {}).get("mode") == "VALIDATION_PREVIEW":
            return
        raise WriteBlockedError(
            f"{method} {path} bloqueado: este agente no publica cambios en Amazon. "
            "Juan los sube a mano tras aprobarlos."
        )

    def _request(self, method: str, path: str, params=None, json_body=None, retries: int = 5):
        self._guard(method, path, params)
        url = self.endpoint + path
        for attempt in range(retries):
            r = self.http.request(
                method, url, params=params, json=json_body, timeout=60,
                headers={
                    "x-amz-access-token": self._access_token(),
                    "user-agent": USER_AGENT,
                    "content-type": "application/json",
                },
            )
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                self._sleep(min(2 ** attempt * 2, 60))
                continue
            if r.status_code == 403:
                raise SPAPIError(
                    f"HTTP 403 en {path}: la app no tiene el rol necesario o la autorización ha caducado. "
                    f"Detalle: {r.text[:300]}"
                )
            if r.status_code >= 400:
                raise SPAPIError(f"HTTP {r.status_code} en {method} {path}: {r.text[:500]}")
            return r.json() if r.content else {}
        raise SPAPIError(f"Demasiados reintentos en {method} {path}")

    # ------------------------------------------------------------ listings
    def find_sku_for_asin(self, asin: str) -> str | None:
        data = self._request("GET", f"/listings/2021-08-01/items/{self.seller_id}", params={
            "marketplaceIds": self.marketplace_id,
            "identifiers": asin,
            "identifiersType": "ASIN",
            "includedData": "summaries",
        })
        items = data.get("items") or []
        return items[0].get("sku") if items else None

    def get_listing(self, sku: str) -> dict:
        return self._request(
            "GET", f"/listings/2021-08-01/items/{self.seller_id}/{quote(sku, safe='')}",
            params={
                "marketplaceIds": self.marketplace_id,
                "includedData": "summaries,attributes,issues,offers,fulfillmentAvailability",
                "issueLocale": self.idioma,
            },
        )

    def validate_patch_preview(self, sku: str, product_type: str, patches: list[dict]) -> dict:
        """Pide a Amazon que VALIDE un cambio sin aplicarlo (mode=VALIDATION_PREVIEW)."""
        return self._request(
            "PATCH", f"/listings/2021-08-01/items/{self.seller_id}/{quote(sku, safe='')}",
            params={
                "marketplaceIds": self.marketplace_id,
                "mode": "VALIDATION_PREVIEW",
                "includedData": "issues",
                "issueLocale": self.idioma,
            },
            json_body={"productType": product_type, "patches": patches},
        )

    # ------------------------------------------------------------- catalog
    def get_catalog_item(self, asin: str) -> dict:
        return self._request("GET", f"/catalog/2022-04-01/items/{asin}", params={
            "marketplaceIds": self.marketplace_id,
            "includedData": "attributes,images,summaries,salesRanks,productTypes,classifications",
            "locale": self.idioma,
        })

    def search_catalog(self, keywords: str, page_token: str | None = None, page_size: int = 20) -> dict:
        params = {
            "marketplaceIds": self.marketplace_id,
            "keywords": keywords,
            "includedData": "summaries",
            "pageSize": page_size,
            "locale": self.idioma,
        }
        if page_token:
            params["pageToken"] = page_token
        return self._request("GET", "/catalog/2022-04-01/items", params=params)

    # ---------------------------------------------------------- definitions
    def get_product_type_schema(self, product_type: str) -> dict:
        """Esquema JSON del tipo de producto en Amazon.es: de aquí salen los
        límites REALES de cada campo (en vez de fiarse de blogs)."""
        meta = self._request("GET", f"/definitions/2020-09-01/productTypes/{product_type}", params={
            "marketplaceIds": self.marketplace_id,
            "sellerId": self.seller_id,
            "requirements": "LISTING",
            "locale": self.idioma,
        })
        link = (meta.get("schema") or {}).get("link", {}).get("resource")
        if not link:
            raise SPAPIError(f"La definición de {product_type} no trae enlace al esquema")
        r = self.http.get(link, timeout=60)  # URL prefirmada: sin cabeceras de auth
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------ inventory
    def fba_inventory(self, sku: str) -> dict | None:
        data = self._request("GET", "/fba/inventory/v1/summaries", params={
            "details": "true",
            "granularityType": "Marketplace",
            "granularityId": self.marketplace_id,
            "marketplaceIds": self.marketplace_id,
            "sellerSkus": sku,
        })
        summaries = (data.get("payload") or {}).get("inventorySummaries") or []
        return summaries[0] if summaries else None

    # -------------------------------------------------------------- reports
    def sales_and_traffic(self, start: datetime, end: datetime, max_wait_s: int = 900) -> dict:
        """Informe de negocio (sesiones, conversión, Buy Box por ASIN)."""
        created = self._request("POST", "/reports/2021-06-30/reports", json_body={
            "reportType": "GET_SALES_AND_TRAFFIC_REPORT",
            "marketplaceIds": [self.marketplace_id],
            "dataStartTime": start.astimezone(timezone.utc).strftime("%Y-%m-%dT00:00:00Z"),
            "dataEndTime": end.astimezone(timezone.utc).strftime("%Y-%m-%dT23:59:59Z"),
            "reportOptions": {"dateGranularity": "DAY", "asinGranularity": "CHILD"},
        })
        report_id = created["reportId"]
        waited = 0
        while True:
            rep = self._request("GET", f"/reports/2021-06-30/reports/{report_id}")
            status = rep.get("processingStatus")
            if status == "DONE":
                break
            if status in ("CANCELLED", "FATAL"):
                raise SPAPIError(f"El informe de negocio terminó en estado {status}")
            if waited >= max_wait_s:
                raise SPAPIError("El informe de negocio tarda demasiado; se reintentará en la próxima ejecución")
            self._sleep(15)
            waited += 15
        doc = self._request("GET", f"/reports/2021-06-30/documents/{rep['reportDocumentId']}")
        r = self.http.get(doc["url"], timeout=120)
        r.raise_for_status()
        content = r.content
        if doc.get("compressionAlgorithm") == "GZIP":
            content = gzip.decompress(content)
        return json.loads(content.decode("utf-8"))


def asin_metrics_from_report(report: dict, asin: str) -> dict | None:
    """Extrae las métricas de un ASIN del informe de ventas y tráfico."""
    for row in report.get("salesAndTrafficByAsin", []):
        if row.get("childAsin") == asin or (row.get("parentAsin") == asin and not row.get("childAsin")):
            t = row.get("trafficByAsin", {}) or {}
            s = row.get("salesByAsin", {}) or {}
            return {
                "sesiones": t.get("sessions"),
                "paginas_vistas": t.get("pageViews"),
                "conversion_pct": t.get("unitSessionPercentage"),
                "buy_box_pct": t.get("buyBoxPercentage"),
                "unidades": s.get("unitsOrdered"),
                "ventas_eur": (s.get("orderedProductSales") or {}).get("amount"),
            }
    return None
