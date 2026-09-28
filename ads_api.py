"""
ads_api.py — conexión con la Amazon Ads API oficial (Sponsored Products v3).

Hace dos cosas y ninguna más (no decide nada):
  1. LEER: campañas, grupos, keywords, ASIN/categorías, anuncios (con su elegibilidad) y
     las métricas por día (informe "spTargeting" de la Reporting API v3).
  2. ESCRIBIR Y VERIFICAR (§2.8): cada cambio se pide, se vuelve a leer de Amazon y solo se
     da por CONFIRMADO si el valor real coincide. Si no, se reintenta una vez y si sigue sin
     coincidir queda FALLIDO. Cada cambio es independiente: un fallo no para los demás.

Credenciales (variables de entorno, NUNCA en el código ni en git):
  AMAZON_ADS_CLIENT_ID, AMAZON_ADS_CLIENT_SECRET, AMAZON_ADS_REFRESH_TOKEN
  AMAZON_ADS_PROFILE_ID   (opcional: si falta, se usa el perfil de España)
  AMAZON_ADS_REGION       (opcional: EU por defecto)

Sobre las fechas: los listados de la API (campañas, keywords…) NO traen métricas. Las métricas
salen de un informe por día: cada fila lleva su fecha. El agente guarda esas filas en la hoja
"Diario" del documento único; con ellas sabe qué clics tienen más de 7 días (maduros).
"""

import gzip
import json
import os
import time
from datetime import date, timedelta

import requests

import config
import pujas
from modelo import (ACTIVO, ALZA_BAJA, AMAZON_BUSINESS, ARCHIVADO, AUTO, CATEGORIA, FINALIZADA, KEYWORD, PAGINA_PRODUCTO, PAUSADO,
                    PRODUCTO, PUJA_FIJA, RESTO_BUSQUEDA, SOLO_BAJA, SUPERIOR, Anuncio, Campana, Cuenta, Elemento, Grupo)

REGIONES = {
    "EU": ("https://advertising-api-eu.amazon.com", "https://api.amazon.co.uk/auth/o2/token"),
    "NA": ("https://advertising-api.amazon.com", "https://api.amazon.com/auth/o2/token"),
    "FE": ("https://advertising-api-fe.amazon.com", "https://api.amazon.co.jp/auth/o2/token"),
}
MEDIA = {
    "campaigns": "application/vnd.spCampaign.v3+json",
    "adGroups": "application/vnd.spAdGroup.v3+json",
    "keywords": "application/vnd.spKeyword.v3+json",
    "targetingClauses": "application/vnd.spTargetingClause.v3+json",
    "productAds": "application/vnd.spProductAd.v3+json",
}
RUTA = {"campaigns": "/sp/campaigns", "adGroups": "/sp/adGroups", "keywords": "/sp/keywords",
        "targetingClauses": "/sp/targets", "productAds": "/sp/productAds"}
ID = {"campaigns": "campaignId", "adGroups": "adGroupId", "keywords": "keywordId",
      "targetingClauses": "targetId", "productAds": "adId"}

ESTADO = {"ENABLED": ACTIVO, "PAUSED": PAUSADO, "ARCHIVED": ARCHIVADO}
ESTADO_API = {v: k for k, v in ESTADO.items()}
COINCIDENCIA = {"BROAD": "Amplia", "PHRASE": "Frase", "EXACT": "Exacta"}
COINCIDENCIA_API = {v: k for k, v in COINCIDENCIA.items()}
EMPLAZAMIENTO = {"PLACEMENT_TOP": SUPERIOR, "PLACEMENT_REST_OF_SEARCH": RESTO_BUSQUEDA,
                 "PLACEMENT_PRODUCT_PAGE": PAGINA_PRODUCTO, "SITE_AMAZON_BUSINESS": AMAZON_BUSINESS}
EMPLAZAMIENTO_API = {v: k for k, v in EMPLAZAMIENTO.items()}
ESTRATEGIA_API = {SOLO_BAJA: config.ESTRATEGIA_PUJAS, ALZA_BAJA: "AUTO_FOR_SALES", PUJA_FIJA: "MANUAL"}

COLUMNAS_INFORME = ["date", "campaignId", "adGroupId", "keywordId", "impressions", "clicks", "cost",
                    "purchases7d", "sales7d"]
MAX_DIAS_INFORME = 31          # límite de Amazon por informe
MAX_ANTIGUEDAD_INFORME = 95    # Amazon guarda ~95 días para estos informes


class ErrorAPI(Exception):
    pass


class AmazonAdsAPI:
    def __init__(self, client_id, client_secret, refresh_token, profile_id=None, region="EU",
                 espera_informe_seg=30, max_espera_informe_seg=1800, sesion=None):
        if region not in REGIONES:
            raise ValueError(f"Región desconocida: {region}")
        self.base, self.url_token = REGIONES[region]
        self.client_id, self.client_secret, self.refresh_token = client_id, client_secret, refresh_token
        self.profile_id = profile_id
        self.espera_informe_seg, self.max_espera_informe_seg = espera_informe_seg, max_espera_informe_seg
        self.http = sesion or requests.Session()
        self._token, self._token_caduca = None, 0.0

    @classmethod
    def desde_entorno(cls):
        faltan = [v for v in ("AMAZON_ADS_CLIENT_ID", "AMAZON_ADS_CLIENT_SECRET", "AMAZON_ADS_REFRESH_TOKEN")
                  if not os.environ.get(v)]
        if faltan:
            raise SystemExit("Faltan credenciales de la Amazon Ads API (variables de entorno): " + ", ".join(faltan)
                             + "\nConfigúralas en tu ordenador; nunca las pegues en el chat ni las subas a git.")
        return cls(os.environ["AMAZON_ADS_CLIENT_ID"], os.environ["AMAZON_ADS_CLIENT_SECRET"],
                   os.environ["AMAZON_ADS_REFRESH_TOKEN"], os.environ.get("AMAZON_ADS_PROFILE_ID"),
                   os.environ.get("AMAZON_ADS_REGION", "EU"))

    # ------------------------------------------------------------ HTTP
    def _access_token(self):
        if self._token and time.time() < self._token_caduca - 60:
            return self._token
        r = self.http.post(self.url_token, data={
            "grant_type": "refresh_token", "refresh_token": self.refresh_token,
            "client_id": self.client_id, "client_secret": self.client_secret}, timeout=30)
        if r.status_code != 200:
            raise ErrorAPI(f"Login with Amazon rechazó el refresh token ({r.status_code}): {r.text[:300]}")
        d = r.json()
        self._token, self._token_caduca = d["access_token"], time.time() + int(d.get("expires_in", 3600))
        return self._token

    def _cabeceras(self, media=None, perfil=True):
        h = {"Authorization": f"Bearer {self._access_token()}", "Amazon-Advertising-API-ClientId": self.client_id}
        if perfil:
            h["Amazon-Advertising-API-Scope"] = str(self.perfil())
        if media:
            h["Content-Type"] = h["Accept"] = media
        return h

    def _pedir(self, metodo, ruta, cuerpo=None, media=None, perfil=True, reintentos=5):
        for intento in range(reintentos):
            r = self.http.request(metodo, self.base + ruta, headers=self._cabeceras(media, perfil),
                                  data=json.dumps(cuerpo) if cuerpo is not None else None, timeout=60)
            if r.status_code == 401 and intento == 0:
                self._token = None           # token caducado: renovar y repetir
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                espera = float(r.headers.get("Retry-After") or 2 ** (intento + 1))
                time.sleep(min(espera, 60))
                continue
            return r
        return r

    def _ok(self, r, que):
        if r.status_code >= 300:
            raise ErrorAPI(f"{que}: HTTP {r.status_code} {r.text[:500]}")
        return r.json() if r.text else {}

    # ------------------------------------------------------------ perfil
    def perfil(self):
        if self.profile_id:
            return self.profile_id
        r = self._pedir("GET", "/v2/profiles", perfil=False)
        perfiles = self._ok(r, "Listar perfiles")
        es = [p for p in perfiles if p.get("countryCode") == "ES"]
        if not es:
            raise ErrorAPI("No hay ningún perfil de Amazon.es en esta cuenta. Pon AMAZON_ADS_PROFILE_ID.")
        self.profile_id = str(es[0]["profileId"])
        return self.profile_id

    # ------------------------------------------------------------ lectura
    def _listar(self, entidad, filtro=None):
        cuerpo = {"maxResults": 500, **(filtro or {})}
        if entidad in ("campaigns", "productAds"):
            cuerpo["includeExtendedDataFields"] = True
        out = []
        while True:
            d = self._ok(self._pedir("POST", RUTA[entidad] + "/list", cuerpo, MEDIA[entidad]), f"Listar {entidad}")
            out += d.get(entidad, [])
            if not d.get("nextToken"):
                return out
            cuerpo["nextToken"] = d["nextToken"]

    def leer_cuenta(self, hoy=None):
        cuenta = Cuenta(fecha=hoy or date.today())
        estados = {"stateFilter": {"include": ["ENABLED", "PAUSED"]}}
        for c in self._listar("campaigns", estados):
            ext = c.get("extendedData") or {}
            puj = c.get("dynamicBidding") or {}
            fin = date.fromisoformat(c["endDate"][:10]) if c.get("endDate") else None
            estado = ESTADO.get(c.get("state"), PAUSADO)
            cuenta.campanas[str(c["campaignId"])] = Campana(
                id=str(c["campaignId"]), nombre=c.get("name", ""),
                estado=FINALIZADA if estado == ACTIVO and fin and fin < cuenta.fecha else estado,
                presupuesto=float((c.get("budget") or {}).get("budget") or 0),
                segmentacion=c.get("targetingType", "MANUAL"),
                id_cartera=str(c["portfolioId"]) if c.get("portfolioId") else None,
                estado_servicio=ext.get("servingStatus", ""),
                estrategia_pujas=pujas.normalizar_estrategia(puj.get("strategy")),
                ajustes_emplazamiento={EMPLAZAMIENTO[x["placement"]]: float(x.get("percentage") or 0)
                                       for x in puj.get("placementBidding") or [] if x.get("placement") in EMPLAZAMIENTO},
                fecha_fin=fin)
        for g in self._listar("adGroups", estados):
            cuenta.grupos[str(g["adGroupId"])] = Grupo(
                id=str(g["adGroupId"]), id_campana=str(g["campaignId"]), nombre=g.get("name", ""),
                estado=ESTADO.get(g.get("state"), PAUSADO), puja_defecto=g.get("defaultBid"))
        for a in self._listar("productAds", estados):
            ext = a.get("extendedData") or {}
            cuenta.anuncios.append(Anuncio(
                id=str(a["adId"]), id_campana=str(a["campaignId"]), id_grupo=str(a["adGroupId"]),
                asin=a.get("asin", ""), sku=a.get("sku", ""), estado=ESTADO.get(a.get("state"), PAUSADO),
                estado_servicio=ext.get("servingStatus", "")))
        for k in self._listar("keywords", estados):
            cuenta.elementos[str(k["keywordId"])] = Elemento(
                clave=str(k["keywordId"]), tipo=KEYWORD, id_campana=str(k["campaignId"]),
                id_grupo=str(k["adGroupId"]), texto=k.get("keywordText", ""),
                coincidencia=COINCIDENCIA.get(k.get("matchType"), k.get("matchType", "")),
                estado=ESTADO.get(k.get("state"), PAUSADO), puja=_puja(k.get("bid"), cuenta, k))
        for t in self._listar("targetingClauses", estados):
            tipo, texto, coinc = _expresion(t)
            cuenta.elementos[str(t["targetId"])] = Elemento(
                clave=str(t["targetId"]), tipo=tipo, id_campana=str(t["campaignId"]), id_grupo=str(t["adGroupId"]),
                texto=texto, coincidencia=coinc, estado=ESTADO.get(t.get("state"), PAUSADO),
                puja=_puja(t.get("bid"), cuenta, t))
        return cuenta

    def metricas_diarias(self, desde, hasta):
        """Filas por día y elemento: [{"Fecha", "Clave", "ID campaña", "Clics", ...}]."""
        limite = date.today() - timedelta(days=MAX_ANTIGUEDAD_INFORME)
        desde = max(desde, limite)
        filas, ini = [], desde
        while ini <= hasta:
            fin = min(hasta, ini + timedelta(days=MAX_DIAS_INFORME - 1))
            filas += self._informe(ini, fin)
            ini = fin + timedelta(days=1)
        return filas

    def _informe(self, desde, hasta):
        cuerpo = {
            "name": f"agente {desde} {hasta}", "startDate": desde.isoformat(), "endDate": hasta.isoformat(),
            "configuration": {"adProduct": "SPONSORED_PRODUCTS", "groupBy": ["targeting"],
                              "columns": COLUMNAS_INFORME, "reportTypeId": "spTargeting",
                              "timeUnit": "DAILY", "format": "GZIP_JSON"}}
        r = self._pedir("POST", "/reporting/reports", cuerpo, "application/vnd.createasyncreportrequest.v3+json")
        if r.status_code == 425:  # ya pedido antes: Amazon devuelve el id del informe existente
            detalle = (r.json() if r.text.startswith("{") else {}).get("detail", r.text)
            report_id = str(detalle).rsplit(":", 1)[-1].strip().strip('"}').strip()
        else:
            report_id = self._ok(r, "Pedir informe")["reportId"]
        esperado = 0
        while True:
            d = self._ok(self._pedir("GET", f"/reporting/reports/{report_id}"), "Estado del informe")
            if d.get("status") == "COMPLETED":
                break
            if d.get("status") == "FAILED":
                raise ErrorAPI(f"El informe {report_id} falló: {d.get('failureReason')}")
            if esperado >= self.max_espera_informe_seg:
                raise ErrorAPI(f"El informe {report_id} no terminó en {esperado} s")
            time.sleep(self.espera_informe_seg)
            esperado += self.espera_informe_seg
        crudo = self.http.get(d["url"], timeout=120)   # URL firmada: sin cabeceras de la API
        crudo.raise_for_status()
        datos = json.loads(gzip.decompress(crudo.content))
        return [{"Fecha": f["date"], "Clave": str(f["keywordId"]), "ID campaña": str(f["campaignId"]),
                 "Impresiones": f.get("impressions") or 0, "Clics": f.get("clicks") or 0,
                 "Coste (€)": float(f.get("cost") or 0), "Compras": f.get("purchases7d") or 0,
                 "Ventas (€)": float(f.get("sales7d") or 0)} for f in datos if f.get("keywordId")]

    # ------------------------------------------------------------ escritura + verificación
    def _releer(self, entidad, id_):
        filtro = {f"{ID[entidad]}Filter": {"include": [str(id_)]}}
        filas = self._listar(entidad, filtro)
        return filas[0] if filas else None

    def _actualizar(self, entidad, id_, campos, comprobar):
        """PUT + relectura. comprobar(fila_releída) -> True si el valor real coincide."""
        ultimo = None
        for _ in range(2):   # intento + 1 reintento
            try:
                cuerpo = {entidad: [{ID[entidad]: str(id_), **campos}]}
                d = self._ok(self._pedir("PUT", RUTA[entidad], cuerpo, MEDIA[entidad]), f"Actualizar {entidad}")
                errores = (d.get(entidad) or {}).get("error") or []
                if errores:
                    ultimo = f"Amazon rechazó el cambio: {json.dumps(errores, ensure_ascii=False)[:300]}"
                    continue
                fila = self._releer(entidad, id_)
                if fila is not None and comprobar(fila):
                    return True, "Releído en Amazon: coincide"
                ultimo = f"Releído en Amazon: no coincide ({json.dumps(fila, ensure_ascii=False)[:200]})"
            except (ErrorAPI, requests.RequestException) as e:
                ultimo = str(e)[:300]
        return False, ultimo

    def cambiar_puja(self, el, puja):
        entidad = "keywords" if el.tipo == KEYWORD else "targetingClauses"
        return self._actualizar(entidad, el.clave, {"bid": round(puja, 2)},
                                lambda f: abs(float(f.get("bid") or 0) - round(puja, 2)) < 0.005)

    def pausar(self, el):
        entidad = "keywords" if el.tipo == KEYWORD else "targetingClauses"
        return self._actualizar(entidad, el.clave, {"state": "PAUSED"}, lambda f: f.get("state") == "PAUSED")

    def pausar_campana(self, id_campana):
        return self._actualizar("campaigns", id_campana, {"state": "PAUSED"}, lambda f: f.get("state") == "PAUSED")

    def cambiar_presupuesto(self, id_campana, euros):
        return self._actualizar("campaigns", id_campana, {"budget": {"budget": round(euros, 2), "budgetType": "DAILY"}},
                                lambda f: abs(float((f.get("budget") or {}).get("budget") or 0) - round(euros, 2)) < 0.005)

    def cambiar_estrategia(self, campana, estrategia):
        """Cambia la estrategia de pujas conservando los ajustes de emplazamiento que tenga."""
        valor = ESTRATEGIA_API[estrategia]
        ajustes = [{"placement": EMPLAZAMIENTO_API[e], "percentage": int(round(v))}
                   for e, v in (campana.ajustes_emplazamiento or {}).items() if e in EMPLAZAMIENTO_API]
        return self._actualizar("campaigns", campana.id,
                                {"dynamicBidding": {"strategy": valor, "placementBidding": ajustes}},
                                lambda f: (f.get("dynamicBidding") or {}).get("strategy") == valor)

    def _crear(self, entidad, fila, comprobar):
        """POST + relectura. Devuelve (id | None, detalle)."""
        try:
            d = self._ok(self._pedir("POST", RUTA[entidad], {entidad: [fila]}, MEDIA[entidad]), f"Crear {entidad}")
            res = d.get(entidad) or {}
            if res.get("error"):
                return None, f"Amazon rechazó la creación: {json.dumps(res['error'], ensure_ascii=False)[:300]}"
            exito = (res.get("success") or [{}])[0]
            id_ = exito.get(ID[entidad]) or (exito.get(entidad[:-1]) or {}).get(ID[entidad])
            if not id_:
                return None, f"Respuesta sin id: {json.dumps(d, ensure_ascii=False)[:300]}"
            leida = self._releer(entidad, id_)
            if leida is None or not comprobar(leida):
                return str(id_), f"Creado pero la relectura no coincide ({json.dumps(leida, ensure_ascii=False)[:200]})"
            return str(id_), "Creado y releído en Amazon"
        except (ErrorAPI, requests.RequestException) as e:
            return None, str(e)[:300]

    def crear_keyword(self, id_campana, id_grupo, texto, coincidencia, puja):
        id_, det = self._crear("keywords", {
            "campaignId": id_campana, "adGroupId": id_grupo, "keywordText": texto, "state": "ENABLED",
            "matchType": COINCIDENCIA_API[coincidencia], "bid": round(puja, 2)},
            lambda f: f.get("state") == "ENABLED" and abs(float(f.get("bid") or 0) - round(puja, 2)) < 0.005)
        return id_ is not None and det.startswith("Creado y"), id_, det

    def crear_objetivo_asin(self, id_campana, id_grupo, asin, puja):
        id_, det = self._crear("targetingClauses", {
            "campaignId": id_campana, "adGroupId": id_grupo, "state": "ENABLED", "expressionType": "MANUAL",
            "expression": [{"type": "ASIN_SAME_AS", "value": asin}], "bid": round(puja, 2)},
            lambda f: f.get("state") == "ENABLED")
        return id_ is not None and det.startswith("Creado y"), id_, det

    def crear_campana(self, nombre, presupuesto, sku, nombre_grupo, puja_grupo, id_cartera, hoy):
        """Campaña manual + grupo + anuncio. Si algo falla a mitad, la campaña se PAUSA para no
        dejar nada sirviendo a medias. Devuelve (ok, ids, detalle)."""
        fila = {"name": nombre, "targetingType": "MANUAL", "state": "ENABLED", "startDate": hoy.isoformat(),
                "dynamicBidding": {"strategy": config.ESTRATEGIA_PUJAS},
                "budget": {"budget": round(presupuesto, 2), "budgetType": "DAILY"}}
        if id_cartera:
            fila["portfolioId"] = id_cartera
        ok = lambda id_, det: id_ is not None and det.startswith("Creado y")
        id_c, det = self._crear("campaigns", fila, lambda f: f.get("name") == nombre)
        if not id_c:
            return False, {}, det
        ids = {"id_campana": id_c}
        if ok(id_c, det):
            id_g, det = self._crear("adGroups", {"campaignId": id_c, "name": nombre_grupo, "state": "ENABLED",
                                                  "defaultBid": round(puja_grupo, 2)}, lambda f: str(f.get("campaignId")) == id_c)
            if ok(id_g, det):
                ids["id_grupo"] = id_g
                id_a, det = self._crear("productAds", {"campaignId": id_c, "adGroupId": id_g, "sku": sku,
                                                        "state": "ENABLED"}, lambda f: str(f.get("adGroupId")) == id_g)
                if ok(id_a, det):
                    ids["id_anuncio"] = id_a
                    return True, ids, "Campaña, grupo y anuncio creados y releídos"
        ok_p, det_p = self.pausar_campana(id_c)
        return False, ids, f"{det}. Campaña pausada para no dejarla a medias ({det_p})"


def _puja(bid, cuenta, fila):
    if bid is not None:
        return float(bid)
    g = cuenta.grupos.get(str(fila.get("adGroupId")))
    return float(g.puja_defecto) if g and g.puja_defecto is not None else None


def _expresion(t):
    """Traduce la expresión de segmentación a (tipo, texto, coincidencia)."""
    expr = t.get("expression") or t.get("resolvedExpression") or []
    tipos = {e.get("type") for e in expr}
    if "ASIN_SAME_AS" in tipos or "ASIN_EXPANDED_FROM" in tipos:
        return PRODUCTO, next(e["value"] for e in expr if e.get("type", "").startswith("ASIN")), "ASIN"
    if "ASIN_CATEGORY_SAME_AS" in tipos:
        return CATEGORIA, next(e["value"] for e in expr if e.get("type") == "ASIN_CATEGORY_SAME_AS"), "Categoría"
    texto = ", ".join(str(e.get("type", "")) + (f"={e['value']}" if e.get("value") else "") for e in expr)
    return AUTO, texto or "automática", "Automática"
