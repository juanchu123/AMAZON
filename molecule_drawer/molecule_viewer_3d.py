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


def molecula_3d(nombre, smiles):
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

    return {
        "nombre": nombre,
        "smiles": smiles,
        "formula": rdMolDescriptors.CalcMolFormula(mol),
        "masa": round(Descriptors.MolWt(mol), 3),
        "atomos": mol.GetNumAtoms(),
        "elementos": elementos,
        "molblock": Chem.MolToMolBlock(mol),
        "admet": admet.calcular(mol),
    }


def construir_html(moleculas):
    datos = json.dumps(moleculas, ensure_ascii=False).replace("</", "<\\/")
    return PLANTILLA.read_text(encoding="utf-8").replace("/*MOLECULAS*/[]", datos)


def main():
    moleculas = []
    for nombre, smiles in MOLECULAS:
        try:
            moleculas.append(molecula_3d(nombre, smiles))
        except ValueError as error:
            print(error)
    if not moleculas:
        sys.exit("No se ha podido generar ninguna molécula.")

    SALIDA.write_text(CABECERA + construir_html(moleculas), encoding="utf-8")
    print(f"Visor guardado en {SALIDA} ({len(moleculas)} moléculas). Ábrelo en el navegador.")


if __name__ == "__main__":
    main()
