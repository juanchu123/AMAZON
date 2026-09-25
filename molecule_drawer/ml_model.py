"""Carga los modelos de scikit-learn entrenados por `ml_train.py` y predice SMILES nuevos.

Es el backend ML "real" de la API: a diferencia del enganche a DeepChem (que espera
un modelo que entrenes tú), estos modelos ya vienen entrenados en el repo (`models/`)
y funcionan en cuanto tienes scikit-learn instalado.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from admet_api import ModeloADMET, backends_disponibles, featurizar

MODELOS = Path(__file__).parent / "models"


class BackendSklearn(ModeloADMET):
    """Predice endpoints ADMET con los RandomForest entrenados sobre datos MoleculeNet."""

    nombre = "sklearn"

    def __init__(self, carpeta: Path = MODELOS):
        self.carpeta = carpeta
        self._cache: dict[str, Any] = {}
        self.metricas = {}
        ruta = carpeta / "metricas.json"
        if ruta.exists():
            self.metricas = json.loads(ruta.read_text(encoding="utf-8"))

    @property
    def disponible(self) -> bool:
        return backends_disponibles().get("rdkit", False) \
            and (self.carpeta / "solubilidad.joblib").exists()

    def _modelo(self, nombre: str):
        if nombre not in self._cache:
            import joblib

            self._cache[nombre] = joblib.load(self.carpeta / f"{nombre}.joblib")
        return self._cache[nombre]

    def predecir(self, smiles: str) -> dict[str, Any]:
        if not self.disponible:
            return {
                "disponible": False,
                "motivo": "Faltan los modelos entrenados. Ejecuta: python ml_train.py",
                "backends": backends_disponibles(),
            }

        X = featurizar(smiles)["fingerprint"].reshape(1, -1)
        predicciones = {}

        logs = float(self._modelo("solubilidad").predict(X)[0])
        predicciones["solubilidad"] = {
            "logS": round(logs, 2),
            "unidad": "log mol/L",
            "test_R2": self.metricas.get("solubilidad", {}).get("R2_test"),
        }

        prob = float(self._modelo("bhe").predict_proba(X)[0, 1])
        predicciones["bhe"] = {
            "probabilidad_cruzar": round(prob, 3),
            "prediccion": "cruza" if prob >= 0.5 else "no cruza",
            "test_ROC_AUC": self.metricas.get("bhe", {}).get("ROC_AUC_test"),
        }

        return {
            "disponible": True,
            "motor": "scikit-learn (RandomForest, huellas Morgan)",
            "predicciones": predicciones,
        }


if __name__ == "__main__":
    import sys

    backend = BackendSklearn()
    smiles = sys.argv[1] if len(sys.argv) > 1 else "CC(=O)OC1=CC=CC=C1C(=O)O"
    print(json.dumps(backend.predecir(smiles), ensure_ascii=False, indent=2))
