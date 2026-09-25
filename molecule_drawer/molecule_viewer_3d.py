"""Genera un visor 3D interactivo (HTML) de moléculas sencillas a partir de SMILES.

RDKit calcula las coordenadas 3D (ETKDG + optimización MMFF) y el resultado se
incrusta en una página HTML que usa 3Dmol.js para dibujarlas: se pueden girar
con el ratón, hacer zoom y cambiar de estilo, y cada una muestra su perfil ADMET
estimado (ver admet.py). Abre `visor_3d.html` en el navegador.
"""

import json
import sys
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import AllChem, Descriptors, rdMolDescriptors

import admet
from molecule_drawer import MOLECULAS

CARPETA = Path(__file__).parent
PLANTILLA = CARPETA / "plantilla_visor.html"
SALIDA = CARPETA / "visor_3d.html"
CABECERA = '<!doctype html>\n<html lang="es">\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'


def _backend_ml():
    """Backend de scikit-learn si hay modelos entrenados; si no, None (el visor sigue funcionando)."""
    try:
        from ml_model import BackendSklearn

        backend = BackendSklearn()
        return backend if backend.disponible else None
    except ImportError:
        return None


def _clase_logs(logs):
    if logs < -6:
        return "mal"
    if logs < -4:
        return "aviso"
    return "bien"


def criterios_ml(backend, smiles):
    """Convierte las predicciones del modelo en filas para el panel del visor."""
    if backend is None:
        return []
    resultado = backend.predecir(smiles)
    if not resultado.get("disponible"):
        return []
    sol = resultado["predicciones"]["solubilidad"]
    bhe = resultado["predicciones"]["bhe"]
    return [
        {"grupo": "Modelo ML", "nombre": "Solubilidad predicha (logS)",
         "valor": f"{sol['logS']:.2f} log mol/L".replace(".", ","),
         "estado": _clase_logs(sol["logS"]),
         "detalle": f"RandomForest sobre ESOL · R² test {sol['test_R2']}"},
        {"grupo": "Modelo ML", "nombre": "Barrera hematoencefálica",
         "valor": f"{round(bhe['probabilidad_cruzar'] * 100)}% probable ({bhe['prediccion']})",
         "estado": "info",
         "detalle": f"RandomForest sobre BBBP · ROC-AUC test {bhe['test_ROC_AUC']}"},
    ]


def molecula_3d(nombre, smiles, backend_ml=None):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"SMILES no válido para {nombre}: {smiles}")
    mol = Chem.AddHs(mol)
    if AllChem.EmbedMolecule(mol, randomSeed=42) != 0:
        raise ValueError(f"No se pudo generar la geometría 3D de {nombre}")
    if AllChem.MMFFHasAllMoleculeParams(mol):
        AllChem.MMFFOptimizeMolecule(mol)
    else:
        AllChem.UFFOptimizeMolecule(mol)

    elementos = []
    for atomo in mol.GetAtoms():
        if atomo.GetSymbol() not in elementos:
            elementos.append(atomo.GetSymbol())

    perfil = admet.calcular(mol)
    perfil["criterios"].extend(criterios_ml(backend_ml, smiles))

    return {
        "nombre": nombre,
        "smiles": smiles,
        "formula": rdMolDescriptors.CalcMolFormula(mol),
        "masa": round(Descriptors.MolWt(mol), 3),
        "atomos": mol.GetNumAtoms(),
        "elementos": elementos,
        "molblock": Chem.MolToMolBlock(mol),
        "admet": perfil,
    }


def construir_html(moleculas):
    datos = json.dumps(moleculas, ensure_ascii=False).replace("</", "<\\/")
    return PLANTILLA.read_text(encoding="utf-8").replace("/*MOLECULAS*/[]", datos)


def main():
    backend = _backend_ml()
    if backend is None:
        print("Aviso: sin modelos ML (ejecuta ml_train.py); el visor mostrará solo las reglas.")
    moleculas = []
    for nombre, smiles in MOLECULAS:
        try:
            moleculas.append(molecula_3d(nombre, smiles, backend))
        except ValueError as error:
            print(error)
    if not moleculas:
        sys.exit("No se ha podido generar ninguna molécula.")

    SALIDA.write_text(CABECERA + construir_html(moleculas), encoding="utf-8")
    print(f"Visor guardado en {SALIDA} ({len(moleculas)} moléculas). Ábrelo en el navegador.")


if __name__ == "__main__":
    main()
