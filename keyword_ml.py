"""
keyword_ml.py — Machine learning de keywords para UN producto (por defecto: el soporte de pinza).

Qué hace, en orden:
  1. Lee todos los exports de Amazon Ads de la carpeta de datos:
       - Sponsored_Products_Ad_*.csv      -> anuncios (SÍ traen producto: ASIN, SKU, nombre)
       - Sponsored_Products_Target_*.csv  -> palabras clave (NO traen producto)
  2. Detecta duplicados (archivos idénticos o exports de palabras que no cuadran con ningún anuncio).
  3. RELACIONA cada archivo de palabras con su archivo de anuncios: los exports no traen
     campaña ni grupo de anuncios, así que el vínculo se hace comparando los totales
     (coste, clics, impresiones, compras, ventas). Si la suma de todas las palabras de un
     archivo es igual a los totales de un archivo de anuncios, son el mismo grupo de anuncios.
  4. Se queda SOLO con las palabras de los grupos cuyo producto principal es el elegido
     (--producto-contiene pinza, o --asin).
  5. Entrena un modelo P(compra | clic) (regresión logística regularizada sobre palabras y
     pares de palabras): cuántos clics hacen falta para vender con esa frase.
     El CPC NO se modela: depende sobre todo de la puja que pone Juan, no de la palabra.
     Lo que se calcula es la PUJA MÁXIMA RENTABLE = P(compra) × ticket medio × ACOS objetivo:
     pujando eso o menos, el gasto/ventas de esa frase queda en el objetivo o por debajo.
     La regularización es clave: con tan pocos datos, sin ella el modelo "memorizaría" ruido.
  6. Genera frases candidatas NUEVAS (combinando el vocabulario del título del producto y de
     sus keywords), descarta las que ya existen en la cuenta, las ordena por compra/clic
     (a igual puja, más compra/clic = menos gasto por venta) y devuelve las mejores,
     evitando que salgan casi iguales entre sí.

Salida: resultados/palabras_recomendadas_<producto>.csv  (+ resumen por pantalla)

No toca la cuenta de Amazon Ads — solo lee CSV y escribe un CSV de recomendaciones.

Uso:
    python keyword_ml.py                       # soporte de pinza, datos en la carpeta actual
    python keyword_ml.py --datos ./exports --top 20
    python keyword_ml.py --asin B0DCZS1NR6
    python keyword_ml.py --acos-objetivo 30
"""

import argparse
import csv
import glob
import hashlib
import itertools
import json
import os
import re
import unicodedata
from collections import defaultdict

import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression

STOPWORDS = {"para", "de", "con", "y", "el", "la", "los", "las", "por", "en", "a", "del", "al", "mas", "genérico", "generico"}
TOTAL_KEYS = ("impresiones", "clics", "coste", "compras", "ventas")
REGULARIZACION_C = 1.0          # más bajo = más prudente (más regularización)
PENALIZACION_A_CIEGAS = 0.85    # al ordenar, compra/clic × esto por cada palabra sin datos
ACOS_OBJETIVO_PCT = 35.0        # para la puja máxima rentable (confirmado por Juan: 35%)
NUCLEO = {"soporte", "movil", "coche", "pinza"}  # palabras que casi todas las frases comparten
MAX_REPETICION = 2              # veces que una misma palabra extra puede repetirse en el top
TOLERANCIA_EUR = 0.02           # margen de redondeo al comparar totales entre archivos


# ---------------------------------------------------------------- lectura de CSV

def _num(s):
    """Números de los exports: '101.77', '0,0079', '27,89%', ''."""
    s = (s or "").strip().replace("%", "").replace("€", "")
    if not s:
        return 0.0
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _totales(rows):
    return {
        "impresiones": sum(_num(r.get("Impresiones")) for r in rows),
        "clics": sum(_num(r.get("Clics")) for r in rows),
        "coste": round(sum(_num(r.get("Coste total (EUR)")) for r in rows), 2),
        "compras": sum(_num(r.get("Compras")) for r in rows),
        "ventas": round(sum(_num(r.get("Ventas (EUR)")) for r in rows), 2),
    }


def _mismos_totales(a, b):
    return all(abs(a[k] - b[k]) <= TOLERANCIA_EUR for k in TOTAL_KEYS)


# ---------------------------------------------------------------- texto

def normalizar(texto):
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9ñ]+", " ", t).strip()


def tokens_contenido(texto):
    return [w for w in normalizar(texto).split() if w not in STOPWORDS]


def firma(texto):
    """Dos keywords con la misma firma son 'la misma' a efectos prácticos
    (p. ej. 'soporte móvil para coche con pinza' == 'soporte movil coche de pinza')."""
    return frozenset(tokens_contenido(texto))


def features(texto, coincidencia):
    toks = tokens_contenido(texto)
    f = {f"w={w}": 1.0 for w in toks}
    for a, b in zip(toks, toks[1:]):
        f[f"b={a}_{b}"] = 1.0
    f[f"match={normalizar(coincidencia)}"] = 1.0
    f["n_palabras"] = len(toks) / 5.0
    return f


# ---------------------------------------------------------------- 1-4: datos y relación

def cargar_y_relacionar(carpeta):
    ads = {p: _read_csv(p) for p in sorted(glob.glob(os.path.join(carpeta, "Sponsored_Products_Ad_*.csv")))}
    targets = {p: _read_csv(p) for p in sorted(glob.glob(os.path.join(carpeta, "Sponsored_Products_Target_*.csv")))}
    if not ads or not targets:
        raise SystemExit(f"No encuentro exports de Ad y Target en {carpeta!r}")

    informe = {"duplicados_identicos": [], "relaciones": [], "sin_relacionar": []}

    # duplicados byte a byte
    por_hash = defaultdict(list)
    for p in list(ads) + list(targets):
        with open(p, "rb") as f:
            por_hash[hashlib.md5(f.read()).hexdigest()].append(os.path.basename(p))
    for grupo in por_hash.values():
        if len(grupo) > 1:
            informe["duplicados_identicos"].append(grupo)
            for extra in grupo[1:]:
                ads.pop(os.path.join(carpeta, extra), None)
                targets.pop(os.path.join(carpeta, extra), None)

    tot_ads = {p: _totales(r) for p, r in ads.items()}
    grupos = []  # cada grupo = (archivo_target, archivo_ad, filas_target, filas_ad)
    usados = set()
    for pt, rows_t in targets.items():
        tt = _totales(rows_t)
        match = [pa for pa, ta in tot_ads.items() if pa not in usados and _mismos_totales(tt, ta)]
        if len(match) == 1:
            pa = match[0]
            usados.add(pa)
            grupos.append((pt, pa, rows_t, ads[pa]))
            informe["relaciones"].append({"palabras": os.path.basename(pt), "anuncios": os.path.basename(pa), "totales": tt})
        else:
            motivo = "ningún export de anuncios tiene los mismos totales" if not match else "coincide con varios exports a la vez"
            informe["sin_relacionar"].append({"archivo": os.path.basename(pt), "motivo": motivo, "totales": tt})
    for pa in ads:
        if pa not in usados:
            informe["sin_relacionar"].append({"archivo": os.path.basename(pa), "motivo": "ningún export de palabras suma lo mismo", "totales": tot_ads[pa]})
    return grupos, informe


def producto_principal(rows_ad):
    """El ASIN que se lleva la mayor parte del gasto del grupo, y qué % del gasto supone."""
    gasto = defaultdict(float)
    nombre = {}
    for r in rows_ad:
        gasto[r["ASIN"]] += _num(r.get("Coste total (EUR)"))
        nombre[r["ASIN"]] = r.get("Nombre del anuncio", "")
    asin = max(gasto, key=gasto.get)
    total = sum(gasto.values()) or 1.0
    return asin, nombre[asin], gasto[asin] / total


def filas_producto(grupos, asin=None, contiene=None):
    filas, info, titulo, asin_elegido = [], [], "", None
    for pt, pa, rows_t, rows_ad in grupos:
        a, nom, cuota = producto_principal(rows_ad)
        elegido = (asin and a == asin) or (contiene and normalizar(contiene) in normalizar(nom))
        info.append({"palabras": os.path.basename(pt), "asin": a, "producto": nom[:70], "cuota_gasto": round(cuota, 3), "usado": bool(elegido)})
        if elegido:
            titulo, asin_elegido = nom, a
            for r in rows_t:
                filas.append({
                    "keyword": r["Palabra clave"].strip(),
                    "coincidencia": r["Tipo de coincidencia objetivo"].strip(),
                    "impresiones": _num(r["Impresiones"]),
                    "clics": _num(r["Clics"]),
                    "coste": _num(r["Coste total (EUR)"]),
                    "compras": _num(r["Compras"]),
                    "ventas": _num(r["Ventas (EUR)"]),
                    "puja": _num(r["Puja (EUR)"]),
                    "puja_rec": _num(r.get("Puja recomendada (mediana)(EUR)")),
                    "puja_rec_baja": _num(r.get("Puja recomendada (baja)(EUR)")),
                    "archivo": os.path.basename(pt),
                })
    return filas, info, titulo, asin_elegido


# ---------------------------------------------------------------- 5: modelos

def _dataset(filas, exito, intentos):
    X, y, w = [], [], []
    for f in filas:
        n, k = f[intentos], min(f[exito], f[intentos])
        if n <= 0:
            continue
        x = features(f["keyword"], f["coincidencia"])
        if k > 0:
            X.append(x); y.append(1); w.append(k)
        if n - k > 0:
            X.append(x); y.append(0); w.append(n - k)
    return X, np.array(y), np.array(w, dtype=float)


def entrenar(filas, exito, intentos):
    X, y, w = _dataset(filas, exito, intentos)
    vec = DictVectorizer()
    Xm = vec.fit_transform(X)
    modelo = LogisticRegression(C=REGULARIZACION_C, max_iter=2000)
    modelo.fit(Xm, y, sample_weight=w)
    return vec, modelo


def predecir(vec, modelo, keyword, coincidencia):
    return float(modelo.predict_proba(vec.transform([features(keyword, coincidencia)]))[0, 1])


def validacion_cruzada(filas, exito, intentos):
    """Deja fuera una keyword cada vez (todas sus coincidencias), entrena con el resto y
    compara el error (log-loss ponderado) del modelo contra predecir siempre la media.
    Negativo = el modelo no mejora a la media -> tomar sus predicciones con mucha cautela."""
    grupos = sorted({firma(f["keyword"]) for f in filas if f[intentos] > 0}, key=sorted)
    ll_m = ll_b = peso = 0.0
    for g in grupos:
        train = [f for f in filas if firma(f["keyword"]) != g]
        test = [f for f in filas if firma(f["keyword"]) == g and f[intentos] > 0]
        tot_n = sum(f[intentos] for f in train)
        if tot_n == 0 or sum(f[exito] for f in train) == 0:
            continue
        base = np.clip(sum(f[exito] for f in train) / tot_n, 1e-4, 1 - 1e-4)
        vec, mod = entrenar(train, exito, intentos)
        for f in test:
            p = np.clip(predecir(vec, mod, f["keyword"], f["coincidencia"]), 1e-4, 1 - 1e-4)
            k, n = f[exito], f[intentos]
            ll_m -= k * np.log(p) + (n - k) * np.log(1 - p)
            ll_b -= k * np.log(base) + (n - k) * np.log(1 - base)
            peso += n
    if peso == 0:
        return None
    return {"logloss_modelo": ll_m / peso, "logloss_media": ll_b / peso, "mejora_pct": 100 * (1 - ll_m / ll_b)}


# ---------------------------------------------------------------- 6: candidatas

def vocabulario(titulo, filas):
    """Piezas para construir frases, sacadas SOLO del título del producto y de sus keywords."""
    t = normalizar(titulo)
    cabezas = ["soporte móvil"] if "soporte movil" in t else []
    lugares = [l for l in ["salpicadero", "parasol", "retrovisor", "espejo retrovisor"] if normalizar(l) in t]
    atributos = [a for a in ["ajustable 360", "ajustable", "360", "antideslizante", "estable", "universal"] if normalizar(a) in t]
    marcas = [m for m in ["iphone", "samsung", "xiaomi"] if m in t]
    for f in filas:  # cabezas que ya usan sus keywords reales
        toks = normalizar(f["keyword"]).split()
        if len(toks) >= 2 and toks[0] in {"soporte", "sujeta", "porta"} and toks[1] not in STOPWORDS:
            cab = " ".join(toks[:2]).replace("movil", "móvil").replace("telefono", "teléfono")
            if cab not in cabezas:
                cabezas.append(cab)
    return cabezas, lugares, atributos, marcas


def generar_candidatas(titulo, filas):
    cabezas, lugares, atributos, marcas = vocabulario(titulo, filas)
    mods = [""] + [f"para {l}" for l in lugares] + atributos + [f"para {m}" for m in marcas]
    cands = set()
    for cab, mod in itertools.product(cabezas, mods):
        for plantilla in ("{c} para coche con pinza {m}", "{c} coche pinza {m}", "{c} de pinza {m}", "{c} pinza coche {m}"):
            cands.add(re.sub(r"\s+", " ", plantilla.format(c=cab, m=mod)).strip())
    for l in lugares:
        cands.add(f"soporte móvil {l} coche")
        cands.add(f"soporte móvil coche {l} pinza")
    for a in atributos:
        cands.add(f"pinza móvil coche {a}")
    cands.update({"pinza móvil coche", "pinza para móvil coche", "soporte pinza coche", "soporte pinza móvil"})
    return sorted(cands)


# ---------------------------------------------------------------- orquestación

def recomendar(filas, titulo, existentes, top, acos_objetivo=ACOS_OBJETIVO_PCT, puja_minima=0.0, coincidencia="Frase"):
    """puja_minima: por debajo de esta puja no se ganan subastas (la puja recomendada 'baja'
    más barata que da Amazon para las keywords del producto). Frases cuya puja máxima rentable
    no llega a ese mínimo no se recomiendan: o no saldrían, o saldrían perdiendo dinero."""
    vec_c, mod_c = entrenar(filas, "compras", "clics")

    tot = {k: sum(f[k] for f in filas) for k in ("clics", "coste", "compras", "ventas")}
    ticket = tot["ventas"] / tot["compras"] if tot["compras"] else 0.0
    cpc_global = tot["coste"] / tot["clics"] if tot["clics"] else 0.0

    vistos = {k.split("=", 1)[1] for k in vec_c.feature_names_ if k.startswith("w=")}
    coefs = dict(zip(vec_c.feature_names_, mod_c.coef_[0]))

    puntuadas = []
    for kw in generar_candidatas(titulo, filas):
        if firma(kw) in existentes:
            continue
        toks = tokens_contenido(kw)
        p_compra = predecir(vec_c, mod_c, kw, coincidencia)
        puja_max = p_compra * ticket * acos_objetivo / 100
        nuevas = [w for w in toks if w not in vistos]
        aportes = sorted(((coefs.get(f"w={w}", 0.0), w) for w in toks if w in vistos), reverse=True)
        motivo = []
        if aportes and aportes[0][0] > 0.05:
            motivo.append("venden más: " + ", ".join(w for c, w in aportes if c > 0.05))
        if aportes and aportes[-1][0] < -0.05:
            motivo.append("venden menos: " + ", ".join(w for c, w in aportes if c < -0.05))
        if nuevas:
            motivo.append("sin datos (se prueba a ciegas): " + ", ".join(nuevas))
        puntuadas.append({
            "palabra_clave": kw,
            "coincidencia_sugerida": coincidencia,
            "prob_compra_por_clic": round(p_compra, 4),
            "clics_por_venta": round(1 / p_compra, 1) if p_compra > 0 else None,
            "puja_max_rentable_eur": round(puja_max, 2),
            "acos_si_pujas_cpc_medio_pct": round(100 * cpc_global / (p_compra * ticket), 1) if p_compra * ticket > 0 else None,
            "palabras_sin_datos": len(nuevas),
            "motivo": " | ".join(motivo),
            # a igual puja, más compra/clic = menos gasto por venta; ir a ciegas penaliza
            "_score": p_compra * PENALIZACION_A_CIEGAS ** len(nuevas),
        })

    # selección diversa: no dos frases casi iguales, y cada palabra "extra" (la que no es
    # soporte/móvil/coche/pinza) aparece como mucho en MAX_REPETICION frases de la lista.
    puntuadas.sort(key=lambda r: r["_score"], reverse=True)
    elegidas, usos = [], defaultdict(int)
    for r in puntuadas:
        if r["puja_max_rentable_eur"] < puja_minima:
            continue
        s = firma(r["palabra_clave"])
        extra = s - NUCLEO
        if any(len(s & firma(e["palabra_clave"])) / len(s | firma(e["palabra_clave"])) >= 0.6 for e in elegidas):
            continue
        if any(usos[w] >= MAX_REPETICION for w in extra):
            continue
        for w in extra:
            usos[w] += 1
        elegidas.append(r)
        if len(elegidas) >= top:
            break
    for i, r in enumerate(elegidas, 1):
        r["rank"] = i
        r.pop("_score")
    resumen = {"ticket_medio_eur": round(ticket, 2), "cpc_medio_eur": round(cpc_global, 2),
               "candidatas_generadas": len(puntuadas), "coeficientes_conversion": {k: round(v, 3) for k, v in sorted(coefs.items(), key=lambda kv: -kv[1])},
               "acos_objetivo_pct": acos_objetivo}
    return elegidas, resumen


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--datos", default=".", help="carpeta con los CSV exportados de Amazon Ads")
    ap.add_argument("--producto-contiene", default="pinza", help="texto que debe aparecer en el nombre del anuncio")
    ap.add_argument("--asin", help="en vez de por nombre, filtrar por ASIN exacto")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--acos-objetivo", type=float, default=ACOS_OBJETIVO_PCT, help="ACOS objetivo en %% para la puja máxima rentable")
    ap.add_argument("--salida", default="resultados")
    args = ap.parse_args()

    grupos, informe = cargar_y_relacionar(args.datos)
    filas, info_grupos, titulo, asin = filas_producto(grupos, asin=args.asin, contiene=None if args.asin else args.producto_contiene)
    informe["grupos"] = info_grupos

    print("\n=== 1. Duplicados y relación palabras <-> anuncios ===")
    for g in informe["duplicados_identicos"]:
        print(f"  DUPLICADO idéntico (se usa solo el primero): {g}")
    for r in informe["relaciones"]:
        t = r["totales"]
        print(f"  {r['palabras']}  <->  {r['anuncios']}   (coste {t['coste']:.2f}€, {t['clics']:.0f} clics, {t['compras']:.0f} compras)")
    for s in informe["sin_relacionar"]:
        print(f"  DESCARTADO {s['archivo']}: {s['motivo']} (coste {s['totales']['coste']:.2f}€)")
    print("\n=== 2. Producto de cada grupo ===")
    for g in info_grupos:
        print(f"  {'USADO   ' if g['usado'] else 'ignorado'} {g['palabras']}: {g['asin']} ({g['cuota_gasto']:.0%} del gasto) {g['producto']}")
        if g["usado"] and g["cuota_gasto"] < 0.95:
            print(f"           ojo: el {1 - g['cuota_gasto']:.0%} del gasto de este grupo es de otro producto")

    if not filas:
        raise SystemExit("Ningún grupo de anuncios corresponde a ese producto.")
    con_clics = [f for f in filas if f["clics"] > 0]
    print(f"\n=== 3. Entrenamiento: {asin} — {len(filas)} filas, {len({firma(f['keyword']) for f in filas})} keywords distintas, "
          f"{sum(f['clics'] for f in filas):.0f} clics, {sum(f['compras'] for f in filas):.0f} compras ===")
    if len(con_clics) < 8:
        print("  AVISO: muy pocos datos; las predicciones son orientativas.")
    cv = validacion_cruzada(filas, "compras", "clics")
    if cv:
        print(f"  Validación (dejando fuera cada keyword): modelo {cv['logloss_modelo']:.3f} vs media {cv['logloss_media']:.3f} "
              f"-> {'mejora' if cv['mejora_pct'] > 0 else 'NO mejora'} un {abs(cv['mejora_pct']):.1f}%")

    # nunca recomendar algo que ya exista en la cuenta (de cualquier producto)
    existentes = {firma(r["Palabra clave"]) for pt, pa, rows_t, _ in grupos for r in rows_t}
    for p in glob.glob(os.path.join(args.datos, "Sponsored_Products_Target_*.csv")):
        existentes |= {firma(r["Palabra clave"]) for r in _read_csv(p)}

    recs_baja = [f["puja_rec_baja"] for f in filas if f["puja_rec_baja"] > 0]
    recs, resumen = recomendar(filas, titulo, existentes, args.top, acos_objetivo=args.acos_objetivo,
                               puja_minima=min(recs_baja) if recs_baja else 0.0)
    recs_amazon = [f["puja_rec"] for f in filas if f["puja_rec"] > 0]
    print(f"  Ticket medio {resumen['ticket_medio_eur']}€, CPC medio {resumen['cpc_medio_eur']}€, "
          f"{resumen['candidatas_generadas']} candidatas nuevas evaluadas")
    if recs_amazon:
        print(f"  Competencia: Amazon recomienda pujar {min(recs_amazon):.2f}-{max(recs_amazon):.2f}€ en las keywords actuales. "
              f"Se descartan las frases cuya puja máx. rentable no llega a {min(recs_baja):.2f}€.")

    os.makedirs(args.salida, exist_ok=True)
    slug = normalizar(args.asin or args.producto_contiene).replace(" ", "_")
    out = os.path.join(args.salida, f"palabras_recomendadas_{slug}.csv")
    campos = ["rank", "palabra_clave", "coincidencia_sugerida", "prob_compra_por_clic", "clics_por_venta",
              "puja_max_rentable_eur", "acos_si_pujas_cpc_medio_pct", "palabras_sin_datos", "motivo"]
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(recs)
    with open(os.path.join(args.salida, f"informe_{slug}.json"), "w", encoding="utf-8") as f:
        json.dump({"asin": asin, "informe_datos": informe, "validacion": cv, **resumen}, f, ensure_ascii=False, indent=2)

    print(f"\n=== 4. Palabras recomendadas para probar ({out}) — puja máx. para ACOS {args.acos_objetivo:.0f}% ===")
    for r in recs:
        print(f"  {r['rank']:2d}. {r['palabra_clave']:<48s} compra/clic {r['prob_compra_por_clic']:.1%}  "
              f"puja máx {r['puja_max_rentable_eur']:.2f}€  {r['motivo']}")


if __name__ == "__main__":
    main()
