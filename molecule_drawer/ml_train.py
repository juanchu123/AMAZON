"""Entrena modelos ADMET de verdad con scikit-learn sobre datos experimentales.

No es una regla empírica: descarga datasets públicos (MoleculeNet), featuriza cada
molécula con huellas de RDKit (NumPy) y ajusta un modelo por endpoint, evaluándolo
con una partición train/test. Los modelos entrenados se guardan en `models/` y los
usa `ml_model.py` / `admet_api.py` para predecir moléculas nuevas.

    python ml_train.py            # entrena todos los endpoints y guarda los modelos

Endpoints:
- solubilidad  -> regresión   (Delaney/ESOL, logS experimental en mol/L)
- bhe          -> clasificación (BBBP, si la molécula cruza la barrera hematoencefálica)
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import mean_squared_error, r2_score, roc_auc_score
from sklearn.model_selection import train_test_split

from admet_api import featurizar
from rdkit import Chem

CARPETA = Path(__file__).parent
DATOS = CARPETA / "ml_data"
MODELOS = CARPETA / "models"
SEMILLA = 42

FUENTES = {
    "delaney-processed.csv": "https://deepchemdata.s3-us-west-1.amazonaws.com/datasets/delaney-processed.csv",
    "BBBP.csv": "https://deepchemdata.s3-us-west-1.amazonaws.com/datasets/BBBP.csv",
}


def descargar():
    DATOS.mkdir(exist_ok=True)
    for archivo, url in FUENTES.items():
        destino = DATOS / archivo
        if not destino.exists():
            print(f"Descargando {archivo}...")
            urllib.request.urlretrieve(url, destino)


def leer_csv(nombre: str) -> list[dict[str, str]]:
    import csv

    with open(DATOS / nombre, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def matriz_features(smiles_list: list[str]) -> tuple[np.ndarray, list[int]]:
    """Featuriza una lista de SMILES; devuelve la matriz X y los índices válidos."""
    filas, validos = [], []
    for i, smi in enumerate(smiles_list):
        if Chem.MolFromSmiles(smi) is None:
            continue
        filas.append(featurizar(smi)["fingerprint"])
        validos.append(i)
    return np.array(filas, dtype=np.float32), validos


def entrenar_regresion(nombre, filas, col_smiles, col_y):
    smiles = [r[col_smiles] for r in filas]
    X, validos = matriz_features(smiles)
    y = np.array([float(filas[i][col_y]) for i in validos], dtype=np.float32)

    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=SEMILLA)
    modelo = RandomForestRegressor(n_estimators=200, max_depth=18, n_jobs=-1, random_state=SEMILLA)
    modelo.fit(X_tr, y_tr)
    pred = modelo.predict(X_te)
    metricas = {
        "tipo": "regresion",
        "n": len(y),
        "R2_test": round(float(r2_score(y_te, pred)), 3),
        "RMSE_test": round(float(np.sqrt(mean_squared_error(y_te, pred))), 3),
    }
    return modelo, metricas


def entrenar_clasificacion(nombre, filas, col_smiles, col_y):
    smiles = [r[col_smiles] for r in filas]
    X, validos = matriz_features(smiles)
    y = np.array([int(filas[i][col_y]) for i in validos], dtype=np.int32)

    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=SEMILLA, stratify=y)
    modelo = RandomForestClassifier(n_estimators=200, max_depth=18, n_jobs=-1, random_state=SEMILLA, class_weight="balanced")
    modelo.fit(X_tr, y_tr)
    prob = modelo.predict_proba(X_te)[:, 1]
    metricas = {
        "tipo": "clasificacion",
        "n": len(y),
        "ROC_AUC_test": round(float(roc_auc_score(y_te, prob)), 3),
        "positivos": int(y.sum()),
    }
    return modelo, metricas


def main():
    import joblib

    descargar()
    MODELOS.mkdir(exist_ok=True)
    resumen = {}

    # Solubilidad (regresión)
    delaney = leer_csv("delaney-processed.csv")
    modelo, metricas = entrenar_regresion(
        "solubilidad", delaney, "smiles", "measured log solubility in mols per litre")
    joblib.dump(modelo, MODELOS / "solubilidad.joblib", compress=3)
    resumen["solubilidad"] = {**metricas, "unidad": "logS (mol/L)", "dataset": "Delaney/ESOL"}
    print("solubilidad:", metricas)

    # Barrera hematoencefálica (clasificación)
    bbbp = [r for r in leer_csv("BBBP.csv") if r.get("p_np") in ("0", "1")]
    modelo, metricas = entrenar_clasificacion("bhe", bbbp, "smiles", "p_np")
    joblib.dump(modelo, MODELOS / "bhe.joblib", compress=3)
    resumen["bhe"] = {**metricas, "salida": "probabilidad de cruzar la BHE", "dataset": "BBBP"}
    print("bhe:", metricas)

    (MODELOS / "metricas.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nModelos guardados en {MODELOS}/")


if __name__ == "__main__":
    main()
