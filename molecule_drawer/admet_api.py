"""API de perfil ADMET: puente entre RDKit/NumPy y modelos de DeepChem/PyTorch/TensorFlow.

Diseño en dos capas:

1. Base determinista (siempre disponible): reglas empíricas de `admet.py` sobre
   RDKit + una featurización con NumPy (huella ECFP y vector de descriptores) que
   sirve de entrada a cualquier modelo.
2. Capa de modelos entrenados (opcional): si están instalados DeepChem y su motor
   (PyTorch o TensorFlow), se puede enchufar un modelo para predecir endpoints que
   las reglas no cubren (CYP, hERG, toxicidad aguda...). Si no están, la API lo
   dice explícitamente en vez de inventar valores.

Formas de llamarla:
    from admet_api import predict_admet
    predict_admet("CC(=O)OC1=CC=CC=C1C(=O)O")        # dict con el perfil

    python admet_api.py "CCO"                          # imprime JSON por consola
    python admet_api.py --serve                        # levanta una API HTTP local
    #   -> GET http://127.0.0.1:8000/admet?smiles=CCO

Instalar la capa de modelos (pesada, opcional):
    pip install deepchem torch            # o: pip install deepchem tensorflow
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from rdkit import Chem
from rdkit.Chem import Descriptors, rdMolDescriptors

import admet

FINGERPRINT_BITS = 2048
FINGERPRINT_RADIUS = 2
# Descriptores que forman el vector de entrada "clásico" para un modelo tabular.
DESCRIPTORES = (
    ("MolWt", Descriptors.MolWt),
    ("MolLogP", Descriptors.MolLogP),
    ("TPSA", rdMolDescriptors.CalcTPSA),
    ("NumHDonors", rdMolDescriptors.CalcNumLipinskiHBD),
    ("NumHAcceptors", rdMolDescriptors.CalcNumLipinskiHBA),
    ("NumRotatableBonds", rdMolDescriptors.CalcNumRotatableBonds),
    ("FractionCSP3", rdMolDescriptors.CalcFractionCSP3),
    ("NumAromaticRings", rdMolDescriptors.CalcNumAromaticRings),
)


def _tiene(modulo: str) -> bool:
    try:
        return importlib.util.find_spec(modulo) is not None
    except (ImportError, ValueError):
        return False


def backends_disponibles() -> dict[str, bool]:
    """Qué librerías de la pila están instaladas en este entorno."""
    return {m: _tiene(m) for m in ("numpy", "rdkit", "deepchem", "torch", "tensorflow")}


def parsear(smiles: str) -> Chem.Mol:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"SMILES no válido: {smiles!r}")
    return mol


def featurizar(smiles: str) -> dict[str, Any]:
    """Convierte un SMILES en las matrices NumPy que consume un modelo.

    - `fingerprint`: huella ECFP/Morgan binaria (NumPy uint8, 2048 bits).
    - `descriptores`: vector de descriptores fisicoquímicos (NumPy float32).
    """
    mol = parsear(smiles)

    from rdkit.Chem import rdFingerprintGenerator
    from rdkit.DataStructs import ConvertToNumpyArray

    huella = np.zeros((FINGERPRINT_BITS,), dtype=np.uint8)
    generador = rdFingerprintGenerator.GetMorganGenerator(radius=FINGERPRINT_RADIUS, fpSize=FINGERPRINT_BITS)
    ConvertToNumpyArray(generador.GetFingerprint(mol), huella)

    vector = np.array([funcion(mol) for _, funcion in DESCRIPTORES], dtype=np.float32)

    return {
        "smiles": smiles,
        "fingerprint": huella,
        "descriptores": {nombre: float(valor) for (nombre, _), valor in zip(DESCRIPTORES, vector)},
        "vector": vector,
    }


class ModeloADMET:
    """Interfaz mínima que debe cumplir cualquier backend de predicción."""

    nombre = "base"
    disponible = False

    def predecir(self, smiles: str) -> dict[str, Any]:  # pragma: no cover - interfaz
        raise NotImplementedError


@dataclass
class BackendDeepChem(ModeloADMET):
    """Backend que carga un modelo entrenado de DeepChem (motor PyTorch o TensorFlow).

    DeepChem no trae pesos de ADMET listos para producción, así que este backend
    espera un modelo ya entrenado y guardado por ti en `model_dir` (por ejemplo un
    `dc.models.AttentiveFPModel` o `GraphConvModel` reentrenado sobre datos ADMET-AI
    o Therapeutics Data Commons). Sin ese modelo, `disponible` es False y la API
    sigue funcionando con la capa determinista.
    """

    model_dir: str | None = None
    tareas: tuple[str, ...] = ("solubilidad", "hERG", "CYP2D6")
    nombre: str = "deepchem"
    _modelo: Any = field(default=None, repr=False)
    _featurizer: Any = field(default=None, repr=False)

    @property
    def disponible(self) -> bool:
        return _tiene("deepchem") and (_tiene("torch") or _tiene("tensorflow")) and self.model_dir is not None

    def _cargar(self) -> None:
        if self._modelo is not None:
            return
        import deepchem as dc  # import perezoso: solo si de verdad se usa

        self._featurizer = dc.feat.MolGraphConvFeaturizer(use_edges=True)
        self._modelo = dc.models.AttentiveFPModel(
            n_tasks=len(self.tareas), mode="regression", model_dir=self.model_dir
        )
        self._modelo.restore()  # carga los pesos guardados en model_dir

    def motor(self) -> str:
        if _tiene("torch"):
            return "PyTorch"
        if _tiene("tensorflow"):
            return "TensorFlow"
        return "desconocido"

    def predecir(self, smiles: str) -> dict[str, Any]:
        if not self.disponible:
            return {
                "disponible": False,
                "motivo": "DeepChem + (PyTorch o TensorFlow) y un model_dir con un modelo entrenado.",
                "backends": backends_disponibles(),
            }
        self._cargar()
        entrada = self._featurizer.featurize([smiles])
        predicciones = np.asarray(self._modelo.predict_on_batch(entrada)).reshape(-1)
        return {
            "disponible": True,
            "motor": self.motor(),
            "predicciones": {tarea: float(v) for tarea, v in zip(self.tareas, predicciones)},
        }


def predict_admet(smiles: str, modelo: ModeloADMET | None = None, incluir_features: bool = False) -> dict[str, Any]:
    """Perfil ADMET completo de un SMILES.

    Siempre devuelve la capa determinista (reglas RDKit). Si se pasa un `modelo`
    disponible, añade sus predicciones bajo la clave `ml`; si no, deja constancia
    de que la capa de modelos no está activa.
    """
    mol = parsear(smiles)
    resultado: dict[str, Any] = {
        "smiles": smiles,
        "formula": rdMolDescriptors.CalcMolFormula(mol),
        "masa": round(Descriptors.MolWt(mol), 3),
        "reglas": admet.calcular(mol),
        "backends": backends_disponibles(),
    }

    if incluir_features:
        f = featurizar(smiles)
        resultado["features"] = {
            "descriptores": f["descriptores"],
            "fingerprint_bits": int(f["fingerprint"].sum()),
            "fingerprint_dim": FINGERPRINT_BITS,
        }

    resultado["ml"] = (modelo or modelo_por_defecto()).predecir(smiles)
    return resultado


def modelo_por_defecto() -> ModeloADMET:
    """Elige el mejor backend disponible: scikit-learn si hay modelos, si no DeepChem."""
    try:
        from ml_model import BackendSklearn

        backend = BackendSklearn()
        if backend.disponible:
            return backend
    except ImportError:
        pass
    return BackendDeepChem()


# --- API HTTP opcional -------------------------------------------------------

def create_app():
    """Devuelve una app Flask que expone la API por HTTP. Requiere `pip install flask`."""
    try:
        from flask import Flask, jsonify, request
    except ImportError as error:  # pragma: no cover
        raise SystemExit("Para --serve hace falta Flask: pip install flask") from error

    app = Flask(__name__)

    @app.after_request
    def cors(respuesta):
        respuesta.headers["Access-Control-Allow-Origin"] = "*"
        return respuesta

    @app.get("/health")
    def health():
        return jsonify({"ok": True, "backends": backends_disponibles()})

    @app.get("/admet")
    def endpoint_admet():
        smiles = request.args.get("smiles", "").strip()
        if not smiles:
            return jsonify({"error": "Falta el parámetro ?smiles="}), 400
        try:
            return jsonify(predict_admet(smiles, incluir_features=True))
        except ValueError as error:
            return jsonify({"error": str(error)}), 422

    return app


def _serializable(obj: Any) -> Any:
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    raise TypeError(type(obj))


def main(argv: list[str]) -> None:
    if "--serve" in argv:
        puerto = 8000
        if "--port" in argv:
            puerto = int(argv[argv.index("--port") + 1])
        print(f"API ADMET en http://127.0.0.1:{puerto}/admet?smiles=CCO  (Ctrl+C para parar)")
        create_app().run(host="127.0.0.1", port=puerto)
        return

    argumentos = [a for a in argv if not a.startswith("-")]
    if not argumentos:
        print(__doc__)
        print("Backends:", json.dumps(backends_disponibles(), ensure_ascii=False))
        return

    perfil = predict_admet(argumentos[0], incluir_features=True)
    print(json.dumps(perfil, ensure_ascii=False, indent=2, default=_serializable))


if __name__ == "__main__":
    main(sys.argv[1:])
