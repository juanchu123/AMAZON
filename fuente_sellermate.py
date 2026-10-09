"""
fuente_sellermate.py — la cuenta de Amazon leída con SellerMate (conector MCP de Claude), sin API propia.

Python no puede llamar a SellerMate: lo hace el Agente ADS (Claude, ver agente_ads/AGENTE_ADS.md) y deja
las respuestas tal cual, en JSON, en entradas/<día>/sellermate/:

  campanas*.json        list_campaigns (ENABLED y PAUSED)                     -> {"campaigns": [...]}
  grupos*.json          list_ad_groups (state ALL)                            -> {"adGroups": [...]}
  targets*.json         list_targets (todas las páginas, todos los estados)   -> {"targets": [...]}
  negativas*.json       list_negative_targets                                 -> {"negativeTargets": [...]}
  productos*.json       get_advertised_product_performance, últimos 60 días,
                        group_by adAsin, adGroupId, campaignId                -> {"data": [...]}
  emplazamientos*.json  get_placement_performance, de hace 30 días a ayer       -> {"placements": [...]}
  terminos*.json        get_search_term_performance, de hace 60 días a ayer,
                        group_by searchTerm, targetingValue, matchType, adGroupId, campaignId -> {"data": [...]}
  diario/AAAA-MM-DD.json  get_targeting_performance de UN día (start = end = ese día), group_by
                        targetingValue, targetingType, adGroupId, campaignId  -> {"data": [...]}
                        (cada día se vuelven a pedir los 8 últimos: las ventas llegan hasta 7 días tarde)

Cada archivo puede ser una respuesta o una lista de respuestas (páginas); se juntan todas.

LEER: la misma Cuenta que dan ads_api.py y fuente_bulk.py, y las métricas por DÍA (hoja Diario), así que
los clics maduros (> 7 días) son exactos, como con la API.
APLICAR: como con la hoja masiva (hereda de FuenteBulk), en dos archivos de salidas/<día>/ que el Agente
ADS manda a Juan por correo (nivel intermedio, Juan 09/10/2026). Nada se cambia sin que Juan lo suba:
  bulk_cambios_<fecha>.xlsx  lo pequeño: pujas, pausas, negativas, keywords y pruebas, estrategia,
                             emplazamientos y bajadas de presupuesto. Juan lo sube tal cual.
  propuestas_<fecha>.xlsx    lo grande: subir presupuestos, crear o reactivar campañas. Juan lo sube solo
                             si está de acuerdo. Si a los 14 días Amazon no lo refleja, queda "no aprobado".
Una propuesta igual a otra de los últimos 7 días que aún espera no se repite.
"""

import json
import re
from datetime import date, timedelta
from pathlib import Path

import config
import pujas
from fuente_bulk import FuenteBulk
from documento import fecha, num
from modelo import (ACTIVO, ARCHIVADO, AUTO, CATEGORIA, CREAR_CAMPANA, FINALIZADA, KEYWORD, PAUSADO, PRESUPUESTO,
                    PRODUCTO, REACTIVAR_CAMPANA, Anuncio, Campana, Cuenta, Elemento, Grupo, Metricas, Negativa, Termino)

ESTADO = {"ENABLED": ACTIVO, "PAUSED": PAUSADO, "ARCHIVED": ARCHIVADO}
COINCIDENCIA = {"EXACT": "Exacta", "PHRASE": "Frase", "BROAD": "Amplia"}
COINCIDENCIA_NEG = {"NEGATIVE_EXACT": "Exacta negativa", "NEGATIVE_PHRASE": "Frase negativa",
                    "NEGATIVE_BROAD": "Amplia negativa"}
ASIN = re.compile(r"B0[A-Z0-9]{8}", re.I)


def _leer(carpeta, patron, clave):
    """Todas las filas bajo 'clave' de los archivos que casan con el patrón (respuestas o listas de ellas)."""
    filas = []
    for ruta in sorted(Path(carpeta).glob(patron)):
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        for d in datos if isinstance(datos, list) else [datos]:
            if isinstance(d, dict):
                filas += d.get(clave) or []
    return filas


def _m(f):
    return Metricas(float(f.get("clicks") or 0), float(f.get("spend") or 0), float(f.get("orders") or 0),
                    float(f.get("sales") or 0), float(f.get("impressions") or 0))


def _norm(valor):
    """Valor de segmentación comparable: un ASIN (con o sin asin="…") en mayúsculas; lo demás en minúsculas
    y con guiones ("Loose match" = "loose-match")."""
    s = str(valor or "").strip()
    a = re.fullmatch(r'(?:asin=)?"?(B0[A-Z0-9]{8})"?', s, re.I)
    if a:
        return a.group(1).upper()
    return re.sub(r"[\s_]+", "-", s.lower())


def carpeta_de(entrada):
    return Path(entrada) / "sellermate"


def hay_datos(entrada):
    c = carpeta_de(entrada)
    return c.is_dir() and any(c.glob("campanas*.json"))


class FuenteSellerMate(FuenteBulk):
    nombre = "SellerMate (lectura) + hoja masiva para Juan"
    verifica_al_momento = False

    def __init__(self, entrada, salida_dir, doc, directivas=None):
        super().__init__(Path(entrada), salida_dir)
        self.carpeta = carpeta_de(entrada)
        self.doc = doc
        self.directivas = directivas or {}
        self.producto_txt = "Sponsored\xa0Products"
        self.propuestas = []
        self.archivo_propuestas = None

    @staticmethod
    def necesita_aprobacion(c):
        if c.extra.get("ordenada"):          # Juan ya lo pidió por correo
            return False
        return c.tipo in (CREAR_CAMPANA, REACTIVAR_CAMPANA) or (c.tipo == PRESUPUESTO and num(c.despues) > num(c.antes))

    def aplicar(self, cambio, cuenta):
        if not self.necesita_aprobacion(cambio):
            return super().aplicar(cambio, cuenta)
        for t in reversed(self.doc.hojas["Tickets"]):
            if (t.get("Estado") == "enviado_bulk" and t.get("Tipo") == cambio.tipo and str(t.get("Clave")) == str(cambio.clave)
                    and (cuenta.fecha - fecha(t["Fecha"])).days < 7
                    and (cambio.tipo != PRESUPUESTO or abs(num(t.get("Después")) - num(cambio.despues)) < 0.5)):
                cambio.estado, cambio.detalle = "omitido", f"Ya propuesto el {t['Fecha']} ({t['Ticket']}): espera a Juan"
                return cambio
        self.propuestas.append((cambio, cuenta))
        cambio.extra["aprobacion"] = True
        cambio.estado = "enviado_bulk"
        cambio.detalle = "PROPUESTA: en propuestas_<fecha>.xlsx; se aplica solo si Juan la sube"
        return cambio

    def cerrar(self, hoy):
        self.archivo_propuestas = self._escribir(self.propuestas, "propuestas", hoy)
        return self._escribir(self.pendientes, "bulk_cambios", hoy)

    # ------------------------------------------------------------ lectura
    def leer_cuenta(self, hoy=None):
        hoy = hoy or date.today()
        c = self.carpeta
        cuenta = Cuenta(fecha=hoy)
        excluir = {str(x) for x in self.directivas.get("campanas_terminadas", [])}
        for f in _leer(c, "campanas*.json", "campaigns"):
            if f.get("type") not in (None, "Product"):
                continue
            id_ = str(f["campaignId"])
            estado = ESTADO.get(f.get("state"), PAUSADO)
            cuenta.campanas[id_] = Campana(
                id=id_, nombre=f.get("name") or id_,
                estado=FINALIZADA if id_ in excluir and estado == ACTIVO else estado,
                presupuesto=float((f.get("budget") or {}).get("budget") or 0),
                segmentacion=f.get("targetingType") or "MANUAL", id_cartera=f.get("portfolioId"))
        for f in _leer(c, "grupos*.json", "adGroups"):
            cuenta.grupos[str(f["adGroupId"])] = Grupo(
                id=str(f["adGroupId"]), id_campana=str(f["campaignId"]), nombre=f.get("name") or "",
                estado=ESTADO.get(f.get("state"), PAUSADO), puja_defecto=f.get("defaultBid"))
        vistos = set()
        for f in _leer(c, "productos*.json", "data"):
            g, asin = str(f.get("adGroupId") or ""), str(f.get("adAsin") or "").upper()
            if not g or not asin or (g, asin) in vistos:
                continue
            vistos.add((g, asin))
            grupo = cuenta.grupos.get(g)
            cuenta.anuncios.append(Anuncio(
                id=f"{g}:{asin}", id_campana=str(f.get("campaignId") or (grupo.id_campana if grupo else "")),
                id_grupo=g, asin=asin, sku=config.SKUS.get(asin, ""), estado=ACTIVO))
        for f in _leer(c, "targets*.json", "targets"):
            tipo, texto, coinc = self._tipo(f)
            cuenta.elementos[str(f["id"])] = Elemento(
                clave=str(f["id"]), tipo=tipo, id_campana=str(f["campaignId"]), id_grupo=str(f["adGroupId"]),
                texto=texto, coincidencia=coinc, estado=ESTADO.get(f.get("state"), PAUSADO), puja=f.get("bid"))
        for f in _leer(c, "negativas*.json", "negativeTargets"):
            if f.get("type") != "NegativeKeyword":
                continue
            cuenta.negativas.append(Negativa(
                clave=str(f["id"]), id_campana=str(f.get("campaignId") or ""), id_grupo=str(f.get("adGroupId") or ""),
                texto=f.get("keywordText") or "", coincidencia=COINCIDENCIA_NEG.get(f.get("matchType"), ""),
                estado=ESTADO.get(f.get("state"), PAUSADO)))
        self._emplazamientos(cuenta)
        self._terminos(cuenta)
        for e in cuenta.elementos.values():
            if e.puja is None and e.id_grupo in cuenta.grupos:
                e.puja = cuenta.grupos[e.id_grupo].puja_defecto
        self.doc.guardar_diario(self.filas_diarias(cuenta))
        return cuenta

    @staticmethod
    def _tipo(f):
        if f.get("type") == "Keyword":
            return KEYWORD, f.get("keywordText") or f.get("targetingValue") or "", COINCIDENCIA.get(f.get("matchType"), "")
        expr = str(f.get("expressionType") or "")
        valor = f.get("expressionValue") or f.get("targetingValue") or ""
        if "ASIN" in expr.upper() and ASIN.search(str(valor)):
            return PRODUCTO, ASIN.search(str(valor)).group(0).upper(), "ASIN"
        if "CATEGORY" in expr.upper():
            return CATEGORIA, str(valor), "Categoría"
        return AUTO, _norm(expr) or "automática", "Automática"

    def _emplazamientos(self, cuenta):
        for f in _leer(self.carpeta, "emplazamientos*.json", "placements"):
            camp = cuenta.campanas.get(str(f.get("campaignId")))
            if camp is None:
                continue
            camp.estrategia_pujas = pujas.normalizar_estrategia(f.get("biddingStrategy"))
            for a in f.get("bidAdjustments") or []:
                lugar = pujas.normalizar_emplazamiento(a.get("placement"))
                if lugar:
                    camp.ajustes_emplazamiento[lugar] = float(a.get("bidAdjustmentPercent") or 0)
            lugar = pujas.normalizar_emplazamiento(f.get("placement"))
            if lugar:
                camp.metricas_emplazamiento[lugar] = camp.metricas_emplazamiento.get(lugar, Metricas()) + _m(f)

    def _indice(self, cuenta):
        """(grupo, valor normalizado, coincidencia) -> clave del elemento."""
        idx = {}
        for e in cuenta.elementos.values():
            idx[(e.id_grupo, _norm(e.texto), e.coincidencia if e.tipo == KEYWORD else "")] = e.clave
        return idx

    def _clave(self, idx, f):
        tipo = str(f.get("targetingType") or f.get("matchType") or "").upper()
        coinc = COINCIDENCIA.get(tipo, "")
        g, v = str(f.get("adGroupId") or ""), _norm(f.get("targetingValue"))
        return idx.get((g, v, coinc)) or f"{g}|{v}|{coinc or tipo.lower()}"

    def _terminos(self, cuenta):
        idx, out = self._indice(cuenta), {}
        for f in _leer(self.carpeta, "terminos*.json", "data"):
            termino = str(f.get("searchTerm") or "").strip()
            if not termino or not f.get("adGroupId"):
                continue
            clave = self._clave(idx, f)
            el = cuenta.elementos.get(clave)
            t = Termino(id_campana=str(f.get("campaignId") or ""), id_grupo=str(f["adGroupId"]), clave_origen=clave,
                        origen=el.texto if el else str(f.get("targetingValue") or ""),
                        coincidencia=el.coincidencia if el else COINCIDENCIA.get(str(f.get("matchType")).upper(), "Automática"),
                        termino=termino, metricas=_m(f))
            if t.clave in out:
                out[t.clave].metricas = out[t.clave].metricas + t.metricas
            else:
                out[t.clave] = t
        cuenta.terminos = list(out.values())
        cuenta.terminos_maduros = False       # ventana hasta ayer: el gasto maduro sale de la foto de hace ≥ 7 días

    def filas_diarias(self, cuenta):
        """Filas de la hoja Diario: una por día y elemento, de los archivos diario/AAAA-MM-DD.json."""
        idx, filas = self._indice(cuenta), {}
        for ruta in sorted((self.carpeta / "diario").glob("*.json")):
            dia = re.search(r"(20\d\d-\d\d-\d\d)", ruta.name)
            if not dia:
                continue
            for f in _leer(ruta.parent, ruta.name, "data"):
                clave = self._clave(idx, f)
                k = (dia.group(1), clave)
                m = _m(f) + (filas[k]["_m"] if k in filas else Metricas())
                filas[k] = {"_m": m, "Fecha": dia.group(1), "Clave": clave, "ID campaña": str(f.get("campaignId") or "")}
        out = []
        for f in filas.values():
            m = f.pop("_m")
            out.append(f | {"Impresiones": m.impresiones, "Clics": m.clics, "Coste (€)": round(m.coste, 2),
                            "Compras": m.compras, "Ventas (€)": round(m.ventas, 2)})
        return out

    def acumulados(self, cuenta, series, hoy):
        return {k: series.acumulado(k, hoy - timedelta(days=1)) for k in cuenta.elementos}
