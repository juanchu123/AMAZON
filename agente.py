"""
agente.py — el agente autónomo de Amazon Ads de FreshFinder (AGENTE_AUTONOMO.md).

Una ejecución = una ronda. Se puede lanzar tantas veces al día como se quiera: cada keyword y
cada campaña llevan su propio reloj (≥ 3 días y ≥ 10 clics nuevos), así que repetir no hace daño.

  1. Leer la cuenta (API de Amazon Ads, o la hoja masiva descargada si aún no hay API).
  2. Guardar los datos del día en el documento único (Diario / Seguimiento).
  3. Confirmar los cambios enviados en hoja masiva y evaluar los tickets maduros (learner.py).
  4. Seguridad de cuenta (§2.9-bis): si todo está en pausa sin que lo pausara el agente, o
     Amazon avisa de un problema de cuenta -> correo inmediato, y PARAR sin tocar nada.
  5. Investigación de mercado semanal (LLM, solo si hay ANTHROPIC_API_KEY): frases candidatas.
  6. Decidir: keywords (analyzer.py), campañas nuevas (campanas.py), presupuestos (presupuesto.py).
  7. Filtrar por safety.py, aplicar uno a uno (independientes) y VERIFICAR releyendo Amazon.
  8. Guardar todo en el documento (escritura atómica) y mandar UN correo con los cambios.

Uso:
  python agente.py                         # fuente automática: API si hay credenciales, si no la
                                           # hoja masiva más reciente de datos/
  python agente.py --simular               # decide y lo cuenta, pero no toca Amazon ni crea tickets
  python agente.py --fuente bulk --bulk datos/descarga.xlsx
  python agente.py --investigar            # fuerza la investigación de mercado de esta ronda

Variables de entorno: ver README.md (Amazon Ads API, SMTP para el correo, ANTHROPIC_API_KEY).
"""

import argparse
import os
import sys
import traceback
from collections import Counter
from datetime import date, datetime, timedelta

import alertas
import analyzer
import campanas
import config
import investigacion
import keyword_ml as kml
import learner
import presupuesto
import pujas
import safety
from documento import Documento, fecha, num
from modelo import (ACTIVO, CREAR_CAMPANA, ESTRATEGIA, NUEVA_KEYWORD, NUEVO_ASIN, PAUSADO, PAUSAR, PRESUPUESTO, PUJA,
                    Cambio, Metricas)
from prediccion import Catalogo


# ---------------------------------------------------------------- fuente: API oficial
class FuenteAPI:
    nombre = "API de Amazon Ads"
    verifica_al_momento = True

    def __init__(self, api, doc):
        self.api, self.doc = api, doc
        self.subcambios = []

    def leer_cuenta(self, hoy):
        cuenta = self.api.leer_cuenta(hoy)
        fechas = [fecha(f["Fecha"]) for f in self.doc.hojas["Diario"]]
        desde = (max(fechas) - timedelta(days=config.DIAS_REFRESCO_INFORME)) if fechas \
            else hoy - timedelta(days=config.DIAS_INICIALES_INFORME)
        self.doc.guardar_diario(self.api.metricas_diarias(desde, hoy - timedelta(days=1)))
        return cuenta

    def acumulados(self, cuenta, series, hoy):
        return {k: series.acumulado(k, hoy - timedelta(days=1)) for k in cuenta.elementos}

    def aplicar(self, c, cuenta):
        el = cuenta.elementos.get(c.clave)
        try:
            if c.tipo == PUJA:
                ok, det = self.api.cambiar_puja(el, c.despues)
            elif c.tipo == PAUSAR:
                ok, det = self.api.pausar(el)
            elif c.tipo == PRESUPUESTO:
                ok, det = self.api.cambiar_presupuesto(c.id_campana, c.despues)
            elif c.tipo == ESTRATEGIA:
                ok, det = self.api.cambiar_estrategia(cuenta.campanas[c.id_campana], c.despues)
            elif c.tipo == NUEVA_KEYWORD:
                ok, id_, det = self.api.crear_keyword(c.id_campana, c.id_grupo, c.texto, c.coincidencia, c.despues)
                c.clave = id_ or c.clave
            elif c.tipo == NUEVO_ASIN:
                ok, id_, det = self.api.crear_objetivo_asin(c.id_campana, c.id_grupo, c.texto, c.despues)
                c.clave = id_ or c.clave
            elif c.tipo == CREAR_CAMPANA:
                ok, det = self._crear_campana(c, cuenta)
            else:
                ok, det = False, f"tipo no soportado: {c.tipo}"
        except Exception as e:           # un fallo nunca para el resto de la ronda
            ok, det = False, f"{type(e).__name__}: {e}"[:300]
        c.estado, c.detalle = ("confirmado" if ok else "fallido"), det
        return c

    def _crear_campana(self, c, cuenta):
        x = c.extra
        ok, ids, det = self.api.crear_campana(x["nombre"], x["presupuesto"], x["sku"], x["nombre_grupo"],
                                              x["puja_grupo"], x.get("id_cartera"), cuenta.fecha)
        c.id_campana, c.id_grupo = ids.get("id_campana"), ids.get("id_grupo")
        if c.id_campana:
            c.clave = f"camp:{c.id_campana}"
        if not ok:
            return False, det
        creadas = 0
        for kw in x["keywords"]:
            sub = Cambio(tipo=NUEVA_KEYWORD, clave="", producto=c.producto, id_campana=c.id_campana, id_grupo=c.id_grupo,
                         campana=c.campana, texto=kw["texto"], coincidencia=kw["coincidencia"], antes=None,
                         despues=kw["puja"], motivo=f"Campaña nueva: {kw['motivo']}")
            self.aplicar(sub, cuenta)
            self.subcambios.append(sub)
            creadas += sub.estado == "confirmado"
        if not creadas:
            ok_p, det_p = self.api.pausar_campana(c.id_campana)
            return False, f"{det}, pero no se pudo crear ninguna keyword: campaña pausada ({det_p})"
        return True, f"{det}; {creadas}/{len(x['keywords'])} keywords creadas y releídas"

    def cerrar(self, hoy):
        return None


# ---------------------------------------------------------------- utilidades
def elegir_fuente(args, doc):
    hay_api = all(os.environ.get(v) for v in ("AMAZON_ADS_CLIENT_ID", "AMAZON_ADS_CLIENT_SECRET",
                                              "AMAZON_ADS_REFRESH_TOKEN"))
    if args.fuente == "api" or (args.fuente == "auto" and hay_api):
        from ads_api import AmazonAdsAPI
        return FuenteAPI(AmazonAdsAPI.desde_entorno(), doc)
    import fuente_bulk
    ruta = args.bulk or fuente_bulk.buscar_descarga()
    if not ruta:
        raise SystemExit("No hay credenciales de la Amazon Ads API ni ninguna hoja masiva descargada en datos/.\n"
                         "Configura AMAZON_ADS_CLIENT_ID / _CLIENT_SECRET / _REFRESH_TOKEN, o deja la descarga "
                         "de Operaciones en bloque en datos/.")
    return fuente_bulk.FuenteBulk(ruta)


def verificar_enviados(doc, cuenta, hoy):
    """Tickets enviados por hoja masiva: se confirman si la nueva descarga ya refleja el cambio."""
    n = 0
    for t in doc.hojas["Tickets"]:
        if t.get("Estado") != "enviado_bulk":
            continue
        tipo, ok = t["Tipo"], False
        el = cuenta.elementos.get(str(t["Clave"]))
        if tipo == PUJA and el is not None:
            ok = el.puja is not None and abs(el.puja - num(t["Después"])) < 0.005
        elif tipo == PAUSAR and el is not None:
            ok = el.estado == PAUSADO
        elif tipo == PRESUPUESTO:
            c = cuenta.campanas.get(str(t["ID campaña"]))
            ok = c is not None and abs(c.presupuesto - num(t["Después"])) < 0.005
        elif tipo == ESTRATEGIA:
            c = cuenta.campanas.get(str(t["ID campaña"]))
            ok = c is not None and c.estrategia_pujas == pujas.normalizar_estrategia(t["Después"])
        elif tipo in (NUEVA_KEYWORD, NUEVO_ASIN):
            texto = str(t["Palabra clave / segmentación"])
            match = next((e for e in cuenta.elementos.values() if e.id_grupo == str(t["ID grupo"]) and (
                e.texto.upper() == texto.upper() if tipo == NUEVO_ASIN else kml.firma(e.texto) == kml.firma(texto))), None)
            if match:
                t["Clave"], ok = match.clave, True
        elif tipo == CREAR_CAMPANA:
            c = next((c for c in cuenta.campanas.values() if c.nombre == t["Campaña"]), None)
            if c:
                t["ID campaña"], t["Clave"], ok = c.id, f"camp:{c.id}", True
        if ok:
            t["Estado"], t["Detalle"] = "confirmado", f"Confirmado en la descarga del {hoy:%d/%m/%Y}"
            n += 1
        elif (hoy - fecha(t["Fecha"])).days >= 14:
            t["Estado"], t["Detalle"] = "fallido", "14 días después la descarga sigue sin reflejarlo (¿no se subió la hoja?)"
    return n


def orden_de_aplicacion(c):
    """La estrategia primero (las pujas se calculan para ella); después lo que reduce gasto; al final
    lo que lo aumenta."""
    if c.tipo == ESTRATEGIA:
        return -1
    if c.tipo == PAUSAR:
        return 0
    if c.tipo in (PUJA, PRESUPUESTO) and num(c.despues) < num(c.antes):
        return 1
    if c.tipo in (PUJA, PRESUPUESTO):
        return 2
    if c.tipo in (NUEVA_KEYWORD, NUEVO_ASIN):
        return 3
    return 4


def _producto_de(cuenta):
    return lambda el: cuenta.producto_de_grupo(el.id_grupo)


def actualizar_segmentacion(doc, cuenta, series, hoy, decision):
    revision = {str(t["Clave"]) for t in doc.hojas["Tickets"] if t.get("Requiere revisión") == "Sí"}
    filas = []
    for el in sorted(cuenta.elementos.values(), key=lambda e: (cuenta.campanas.get(e.id_campana).nombre
                                                               if e.id_campana in cuenta.campanas else "", e.texto)):
        m = series.acumulado(el.clave, hoy)
        ult = doc.tickets(clave=el.clave)
        ult = ult[-1] if ult else None
        base = series.base_en(el.clave, fecha(ult["Fecha"]), learner._base(ult)) if ult else Metricas()
        c, g = cuenta.campanas.get(el.id_campana), cuenta.grupos.get(el.id_grupo)
        filas.append({
            "Clave": el.clave, "ID campaña": el.id_campana, "Campaña": c.nombre if c else "", "ID grupo": el.id_grupo,
            "Grupo": g.nombre if g else "", "Producto (ASIN)": cuenta.producto_de_grupo(el.id_grupo), "Tipo": el.tipo,
            "Palabra clave / segmentación": el.texto, "Coincidencia": el.coincidencia, "Estado": el.estado,
            "Puja (€)": el.puja, "Elegible": "No" if decision and decision.notas.get(el.clave, "").startswith("No elegible") else "Sí",
            "Clics": m.clics, "Coste (€)": round(m.coste, 2), "Compras": m.compras, "Ventas (€)": round(m.ventas, 2),
            "ACOS": None if m.acos in (None, float("inf")) else round(m.acos, 3),
            "Clics maduros": series.maduro(el.clave, hoy).clics,
            "Último cambio": ult["Fecha"] if ult else None, "Clics desde el cambio": m.clics - base.clics,
            "Decisión de esta ronda": (decision.notas.get(el.clave) if decision else None) or
                                      ("En pausa: el agente no la reactiva" if el.estado != ACTIVO else ""),
            "Requiere revisión de Juan": "Sí" if el.clave in revision or (decision and el.clave in decision.revision) else "",
            "Actualizado": hoy.isoformat()})
    doc.hojas["Segmentación"] = filas


def avisar(doc, ahora, tipo, clave, asunto, cuerpo, simular, inmediato=True):
    """Aviso inmediato, como mucho uno al día por tipo y clave."""
    if doc.alerta_ya_enviada(tipo, clave, ahora.date()):
        return None
    correo = alertas.enviar(asunto, cuerpo, ahora, simular=simular) if inmediato else "en el resumen de la ronda"
    doc.registrar_alerta(ahora, tipo, clave, cuerpo[:500], correo)
    return correo


# ---------------------------------------------------------------- la ronda
def ejecutar(fuente, doc, catalogo, hoy, ahora, simular=False, investigar="auto", log=print):
    if doc.nuevo:
        doc.sembrar(hoy)
    resumen = [("Fecha", f"{ahora:%d/%m/%Y %H:%M}"), ("Fuente de datos", fuente.nombre),
               ("Modo", "SIMULACIÓN (no se toca Amazon)" if simular else "real")]

    cuenta = fuente.leer_cuenta(hoy)
    series = doc.series()
    doc.guardar_foto(hoy, cuenta, fuente.acumulados(cuenta, series, hoy), _producto_de(cuenta))
    series = doc.series()
    confirmados = verificar_enviados(doc, cuenta, hoy)
    evaluados = learner.evaluar_pendientes(doc, series, hoy)
    resumen += [("Tickets confirmados de hojas masivas", confirmados), ("Tickets evaluados (veredicto)", evaluados)]

    # --- §2.9-bis: cuenta parada -> avisar y PARAR
    pausadas_agente = {str(t["ID campaña"]) for t in doc.hojas["Tickets"]
                       if t["Tipo"] == CREAR_CAMPANA and t["Estado"] == "fallido" and t.get("ID campaña")}
    problema = safety.problema_de_cuenta(cuenta, pausadas_agente)
    if problema:
        correo = avisar(doc, ahora, "cuenta_parada", "cuenta",
                        "⚠ Amazon Ads: el agente se ha parado (cuenta en pausa o con problemas)",
                        f"{problema}\n\nEl agente no ha cambiado nada y no reactivará nada por su cuenta: es decisión tuya.\n"
                        "Revisa Seller Central (saldo, método de pago, Oferta Destacada, stock) y la consola de Amazon Ads.\n"
                        "Cuando lo resuelvas y actives las campañas, la siguiente ejecución sigue sola.", simular)
        log(f"PARADO: {problema}" + (f" — aviso: {correo}" if correo else " — (aviso ya enviado hoy)"))
        actualizar_segmentacion(doc, cuenta, series, hoy, None)
        resumen += [("Resultado", "PARADO: " + problema)]
        doc.hojas["Resumen"] = [{"Concepto": a, "Valor": b} for a, b in resumen]
        doc.guardar()
        return {"parado": problema, "cambios": [], "descartados": []}

    gasto_mes = series.gasto_mes(hoy)
    proy = safety.gasto_proyectado(hoy, gasto_mes)
    resumen += [("Gasto del mes (€)", None if gasto_mes is None else round(gasto_mes, 2)),
                ("Gasto proyectado del mes (€)", None if proy is None else round(proy, 2)),
                ("Tope mensual (€)", config.TOPE_MENSUAL_EUR),
                ("Tope de presupuestos diarios hoy (€)", safety.presupuesto_diario_total(hoy, gasto_mes))]

    # --- §2.11: investigación de mercado (semanal, solo datos)
    if investigar != "no" and investigacion.disponible() and (not simular or investigar == "si"):
        asins = {cuenta.producto_de_campana(c.id) for c in cuenta.campanas.values() if c.estado == ACTIVO}
        asins |= {a for a, p in catalogo.productos.items() if p.compras > 0}
        for asin in sorted(a for a in asins if a):
            if investigar != "si" and not investigacion.toca_investigar(doc, asin, hoy):
                continue
            existentes = [e.texto for e in cuenta.elementos.values() if cuenta.producto_de_grupo(e.id_grupo) == asin]
            try:
                cands, archivo = investigacion.investigar(catalogo.producto(asin), existentes)
                investigacion.guardar(doc, asin, hoy, cands, archivo)
                resumen.append((f"Investigación {asin}", f"{len(cands)} frases candidatas"))
            except Exception as e:
                doc.registrar_alerta(ahora, "investigacion", asin, f"La investigación falló: {e}"[:500], "no (solo registro)")
                log(f"Investigación de {asin} falló: {e}")

    # --- decidir: primero la estrategia de pujas de cada campaña (las pujas se calculan para ella)
    pujas.decidir_estrategias(cuenta, lambda id_c: presupuesto.metricas_30d(series, id_c, hoy))
    decision = analyzer.decidir(cuenta, doc, series, catalogo, hoy)
    decision.alertas += pujas.avisos(cuenta)
    nuevas, nota_camp = campanas.proponer(cuenta, doc, series, catalogo, hoy, gasto_mes, decision.cambios)
    cambios_pres, filas_camp, por_nueva, tope = presupuesto.planificar(cuenta, doc, series, catalogo, hoy, gasto_mes, nuevas)
    for c, eur in zip(nuevas, por_nueva):
        c.extra["presupuesto"], c.despues = eur, eur
    cambios = pujas.proponer_estrategias(cuenta) + decision.cambios + nuevas + cambios_pres
    aprobados, descartados = safety.filtrar(cambios, cuenta, hoy, gasto_mes,
                                            lambda a: catalogo.producto(a).ticket if a else None)
    resumen.append(("Campañas nuevas", nota_camp))

    # --- aplicar (uno a uno, independientes) y registrar
    aprobados.sort(key=orden_de_aplicacion)
    for c in aprobados:
        if simular:
            c.estado, c.detalle = "simulado", "Simulación: no se ha enviado a Amazon"
            continue
        fuente.aplicar(c, cuenta)
        doc.registrar(c, hoy)
    for sub in getattr(fuente, "subcambios", []):
        doc.registrar(sub, hoy)
    todos = aprobados + list(getattr(fuente, "subcambios", []))
    try:
        archivo_bulk = None
        if not simular:
            try:
                archivo_bulk = fuente.cerrar(hoy)
            except Exception as e:     # sin hoja masiva, lo "enviado" no se ha enviado de verdad
                for c in todos:
                    if c.estado == "enviado_bulk":
                        c.estado, c.detalle = "fallido", f"No se pudo escribir la hoja masiva: {e}"[:300]
                for t in doc.hojas["Tickets"]:
                    if t["Estado"] == "enviado_bulk" and str(t["Fecha"])[:10] == hoy.isoformat():
                        t["Estado"], t["Detalle"] = "fallido", f"No se pudo escribir la hoja masiva: {e}"[:300]

        # --- documento
        actualizar_segmentacion(doc, cuenta, series, hoy, decision)
        doc.hojas["Campañas"] = filas_camp
        cuenta_tipos = Counter(f"{c.tipo} ({c.estado})" for c in todos)
        resumen += [(f"Cambios: {k}", v) for k, v in sorted(cuenta_tipos.items())]
        resumen += [("Descartados por seguridad", len(descartados))]
        if archivo_bulk:
            resumen.append(("Hoja masiva para subir a Amazon", str(archivo_bulk)))

        # --- correo: uno por ronda con los cambios + avisos nuevos
        nuevos_avisos = [a for a in decision.alertas if not doc.alerta_ya_enviada(a[0], a[1], hoy)]
        hechos = [c for c in todos if c.estado in ("confirmado", "enviado_bulk", "fallido", "simulado")]
        if hechos or nuevos_avisos:
            asunto = (f"Amazon Ads: {sum(c.estado in ('confirmado', 'enviado_bulk') for c in hechos)} cambios"
                      + (f", {sum(c.estado == 'fallido' for c in hechos)} fallidos" if any(c.estado == 'fallido' for c in hechos) else "")
                      + (" (simulación)" if simular else "") + f" — {hoy:%d/%m/%Y}")
            if archivo_bulk:
                asunto += " — hoja masiva para subir"
            cuerpo = alertas.resumen_cambios(hechos, descartados, nuevos_avisos, hoy, simular)
            if archivo_bulk:
                cuerpo += f"\n\nSube {archivo_bulk.name} en Amazon Ads -> Operaciones en bloque."
            correo = alertas.enviar(asunto, cuerpo, ahora, simular=simular)
            doc.registrar_alerta(ahora, "resumen", hoy.isoformat(), asunto, correo)
            for tipo, clave, msg in nuevos_avisos:
                doc.registrar_alerta(ahora, tipo, clave, msg[:500], "en el resumen de la ronda")
            resumen.append(("Correo", correo))
        doc.hojas["Resumen"] = [{"Concepto": a, "Valor": b} for a, b in resumen]
    finally:
        doc.guardar()   # los tickets de lo ya aplicado se guardan pase lo que pase

    for c in todos:
        log(f"[{c.estado}] {c.tipo}: {c.campana} | {c.texto} {c.antes} -> {c.despues} — {c.motivo}")
    for c, m in descartados:
        log(f"[descartado] {c.tipo}: {c.campana} | {c.texto} — {m}")
    for _, _, m in decision.alertas:
        log(f"[aviso] {m}")
    return {"parado": None, "cambios": todos, "descartados": descartados, "decision": decision, "bulk": archivo_bulk}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Agente autónomo de Amazon Ads (FreshFinder)")
    ap.add_argument("--fuente", choices=("auto", "api", "bulk"), default="auto")
    ap.add_argument("--bulk", help="hoja masiva descargada (por defecto, la más reciente de datos/)")
    ap.add_argument("--documento", help=f"documento único (por defecto {config.DOCUMENTO})")
    ap.add_argument("--simular", action="store_true", help="decide y lo cuenta, sin tocar Amazon ni crear tickets")
    ap.add_argument("--investigar", action="store_true", help="forzar la investigación de mercado en esta ronda")
    ap.add_argument("--sin-investigacion", action="store_true", help="no llamar al LLM en esta ronda")
    ap.add_argument("--hoy", help="fecha de la ronda (AAAA-MM-DD); por defecto, hoy")
    args = ap.parse_args(argv)

    ahora = datetime.now()
    hoy = date.fromisoformat(args.hoy) if args.hoy else ahora.date()
    doc = Documento(args.documento)
    try:
        fuente = elegir_fuente(args, doc)
        res = ejecutar(fuente, doc, Catalogo(), hoy, ahora, simular=args.simular,
                       investigar="no" if args.sin_investigacion else ("si" if args.investigar else "auto"))
    except SystemExit:
        raise
    except Exception:
        # nunca fallar en silencio: aviso y salida con error, sin haber guardado nada a medias
        detalle = traceback.format_exc()
        print(detalle, file=sys.stderr)
        try:
            alertas.enviar("⚠ Amazon Ads: el agente ha fallado", f"La ejecución del {ahora:%d/%m/%Y %H:%M} ha fallado "
                           f"antes de terminar. No se ha guardado nada a medias.\n\n{detalle[-3000:]}", ahora,
                           simular=args.simular)
        finally:
            sys.exit(1)
    if res["parado"]:
        sys.exit(2)


if __name__ == "__main__":
    main()
