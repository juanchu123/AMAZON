"""
finanzas.py — el agente de finanzas de FreshFinder (especificación de mejoras, P0-B §2).

Con los costes de cada producto que Juan rellena en la hoja "Economía" de la memoria, calcula:
  - el margen por unidad antes de publicidad y el ACOS de equilibrio (a partir del cual cada venta
    por anuncio pierde dinero). El agente de marketing lo usa como límite de las pujas (pujas.py);
    mientras falten costes, se usa config.ACOS_EQUILIBRIO_DEFECTO.
  - por producto (hoja "Finanzas"): gasto y ventas por anuncios, beneficio después de publicidad
    y ACOS frente al equilibrio, en el mes en curso y en los últimos 30 días; y el gasto del mes
    frente al tope de 840 €.
No toca Amazon ni decide nada: son cuentas.

  margen = (ticket / (1 + IVA) − ticket × comisión − tarifa FBA − coste) × (1 − devoluciones)
  ACOS de equilibrio = margen / ticket      (Amazon calcula el ACOS sobre las ventas con IVA)

Uso suelto (lee la memoria más reciente y no guarda nada):  python finanzas.py
"""

from datetime import date, timedelta

import config
import safety
from documento import num

FALTAN = ("Rellena Comisión Amazon (15 % accesorios de electrónica, 12 % automoción, 15 % juguetes: mira la categoría "
          "en Seller Central), Tarifa FBA (calculadora de ingresos de Seller Central; unos 2,5-4 €) y Coste del producto")


def _pct(v):
    """15, 0.15 o '15 %' -> 0.15. None si está vacío."""
    if v in (None, ""):
        return None
    x = num(str(v).replace("%", ""), None)
    if x is None:
        return None
    return x / 100 if x > 1 else x


def margen_unitario(ticket, iva, comision, fba, coste, devoluciones=0.0):
    return (ticket / (1 + iva) - ticket * comision - fba - coste) * (1 - (devoluciones or 0))


def sembrar(doc, catalogo):
    """Una fila por producto con ventas en el histórico. Nunca pisa lo que Juan haya escrito."""
    hoja = doc.hojas["Economía"]
    ya = {str(f["Producto (ASIN)"]) for f in hoja}
    for asin, p in sorted(catalogo.productos.items()):
        if asin in ya or not p.ticket:
            continue
        hoja.append({"Producto (ASIN)": asin, "Producto": p.corto, "Ticket medio con IVA (€)": round(p.ticket, 2),
                     "IVA": 0.21, "Comisión Amazon": None, "Tarifa FBA (€/ud)": None, "Coste del producto (€/ud)": None,
                     "Devoluciones": None, "Notas": FALTAN})


def aplicar(doc):
    """Calcula margen y ACOS de equilibrio de cada fila y se los pasa al agente de marketing.
    Devuelve {asin: ACOS de equilibrio} de los productos con los costes completos."""
    equilibrios = {}
    for f in doc.hojas["Economía"]:
        ticket = num(f.get("Ticket medio con IVA (€)"), None)
        iva = _pct(f.get("IVA"))
        comision = _pct(f.get("Comisión Amazon"))
        fba = num(f.get("Tarifa FBA (€/ud)"), None)
        coste = num(f.get("Coste del producto (€/ud)"), None)
        asin = str(f["Producto (ASIN)"])
        if None in (ticket, iva, comision, fba, coste) or not ticket:
            if ticket and asin in config.MARGEN_UNITARIO:          # Juan dio el margen por correo
                margen = float(config.MARGEN_UNITARIO[asin])
                f["Margen por unidad (€)"], f["ACOS de equilibrio"] = round(margen, 2), round(max(0.0, margen / ticket), 3)
                f["Notas"] = "Margen por unidad que dio Juan (directivas.json); sin desglose de costes"
                equilibrios[asin] = max(0.0, margen / ticket)
                continue
            f["Margen por unidad (€)"], f["ACOS de equilibrio"] = None, None
            f["Notas"] = f.get("Notas") or FALTAN
            continue
        margen = margen_unitario(ticket, iva, comision, fba, coste, _pct(f.get("Devoluciones")) or 0)
        f["Margen por unidad (€)"], f["ACOS de equilibrio"] = round(margen, 2), round(max(0.0, margen / ticket), 3)
        if f.get("Notas") == FALTAN:
            f["Notas"] = ""
        equilibrios[str(f["Producto (ASIN)"])] = max(0.0, margen / ticket)
    config.ACOS_EQUILIBRIO_POR_ASIN = equilibrios
    return equilibrios


def _claves_por_producto(doc):
    out = {}
    for hoja in ("Segmentación", "Seguimiento"):
        for f in doc.hojas[hoja]:
            if f.get("Producto (ASIN)") and f.get("Clave"):
                out.setdefault(str(f["Producto (ASIN)"]), set()).add(str(f["Clave"]))
    return out


def _ventana(series, claves, desde, hasta):
    """Métricas de los días (desde, hasta]. None si no hay datos de antes de 'desde' (con fotos,
    el primer acumulado incluye todo lo anterior y no se puede partir por fechas)."""
    if not any(series.tiene_diario(k) or any(d <= desde for d, _ in series.fotos.get(k, [])) for k in claves):
        return None
    m = None
    for k in claves:
        d = series.acumulado(k, hasta) - series.acumulado(k, desde)
        m = d if m is None else m + d
    return m


def informe(doc, series, catalogo, hoy):
    """Filas de la hoja Finanzas: por producto y periodo, y el total de la cuenta."""
    margenes = {str(f["Producto (ASIN)"]): (num(f.get("Margen por unidad (€)"), None), num(f.get("ACOS de equilibrio"), None))
                for f in doc.hojas["Economía"]}
    periodos = [("Mes en curso", hoy.replace(day=1) - timedelta(days=1)), ("Últimos 30 días", hoy - timedelta(days=30))]
    filas = []
    claves_de = _claves_por_producto(doc)
    for asin in sorted(margenes):                  # los productos de la hoja Economía
        claves = claves_de.get(asin)
        if not claves:
            continue
        margen, eq = margenes[asin]
        for nombre, desde in periodos:
            m = _ventana(series, claves, desde, hoy)
            if m is None:
                filas.append({"Producto (ASIN)": asin, "Producto": catalogo.producto(asin).corto, "Periodo": nombre,
                              "Situación": "sin datos de antes del periodo (hacen falta más días de fotos)"})
                continue
            bruto = m.compras * margen if margen is not None else None
            beneficio = bruto - m.coste if bruto is not None else None
            if margen is None:
                situacion = "sin costes: rellena la hoja Economía"
            elif m.coste == 0:
                situacion = "sin gasto en anuncios"
            else:
                situacion = "gana dinero" if beneficio >= 0 else "pierde dinero"
            filas.append({"Producto (ASIN)": asin, "Producto": catalogo.producto(asin).corto, "Periodo": nombre,
                          "Gasto en anuncios (€)": round(m.coste, 2), "Ventas por anuncios (€)": round(m.ventas, 2),
                          "Compras por anuncios": m.compras,
                          "ACOS": round(m.acos, 3) if m.acos not in (None, float("inf")) else None,
                          "ACOS de equilibrio": eq, "Margen antes de publicidad (€)": None if bruto is None else round(bruto, 2),
                          "Beneficio después de publicidad (€)": None if beneficio is None else round(beneficio, 2),
                          "Situación": situacion})
    gasto = series.gasto_mes(hoy)
    proy = safety.gasto_proyectado(hoy, gasto)
    filas.append({"Producto (ASIN)": "TOTAL", "Producto": "Toda la cuenta", "Periodo": "Mes en curso",
                  "Gasto en anuncios (€)": None if gasto is None else round(gasto, 2),
                  "Situación": ("gasto del mes desconocido (hacen falta fotos de antes del día 1)" if gasto is None else
                                f"proyectado {proy:.2f} € de {config.TOPE_MENSUAL_EUR:.0f} € de tope "
                                f"({proy / config.TOPE_MENSUAL_EUR:.0%})")})
    return filas


def avisos(doc):
    """Productos cuyo ACOS objetivo (30-35 %) ya pierde dinero con sus costes reales."""
    out = []
    for f in doc.hojas["Economía"]:
        eq = num(f.get("ACOS de equilibrio"), None)
        if eq is not None and eq < config.ACOS_OBJETIVO_MAX:
            out.append(("equilibrio", str(f["Producto (ASIN)"]),
                        f"{f.get('Producto')}: con sus costes, el ACOS de equilibrio es {eq:.0%}, por debajo del objetivo "
                        f"{config.ACOS_OBJETIVO_MIN:.0%}-{config.ACOS_OBJETIVO_MAX:.0%}. El agente limita las pujas a ese "
                        "equilibrio; revisa si quieres bajar el ACOS objetivo."))
    return out


def main():
    import carpetas
    from documento import Documento
    from prediccion import Catalogo
    hoy = date.today()
    memoria = carpetas.memoria_anterior(hoy)
    if not memoria:
        raise SystemExit(f"No hay ninguna memoria en {config.SALIDAS}/: ejecuta antes el agente.")
    doc, catalogo = Documento(memoria), Catalogo()
    sembrar(doc, catalogo)
    aplicar(doc)
    print(f"Memoria: {memoria}\n")
    for f in doc.hojas["Economía"]:
        eq = f.get("ACOS de equilibrio")
        print(f"{f['Producto']:<10} ticket {num(f.get('Ticket medio con IVA (€)')):.2f} €  "
              + (f"margen {f['Margen por unidad (€)']:.2f} €/ud  ACOS de equilibrio {eq:.0%}" if eq is not None else f["Notas"]))
    print()
    for f in informe(doc, doc.series(), catalogo, hoy):
        print(" | ".join(str(f.get(c, "")) for c in ("Producto", "Periodo", "Gasto en anuncios (€)",
                                                      "Beneficio después de publicidad (€)", "Situación")))


if __name__ == "__main__":
    main()
