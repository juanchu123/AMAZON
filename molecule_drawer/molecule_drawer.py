"""Dibuja moléculas sencillas en 2D a partir de SMILES y las guarda como PNG."""

import unicodedata
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import Draw

MOLECULAS = [
    ("Metano", "C"),
    ("Oxígeno", "O=O"),
    ("Agua", "O"),
    ("Dióxido de carbono", "O=C=O"),
    ("Amoníaco", "N"),
    ("Etanol", "CCO"),
    ("Benceno", "c1ccccc1"),
    ("Cafeína", "CN1C=NC2=C1C(=O)N(C(=O)N2C)C"),
    ("Aspirina", "CC(=O)OC1=CC=CC=C1C(=O)O"),
    ("Paracetamol", "CC(=O)NC1=CC=C(O)C=C1"),
    ("Ibuprofeno", "CC(C)CC1=CC=C(C=C1)C(C)C(=O)O"),
]

SALIDA = Path(__file__).parent / "imagenes"


def nombre_archivo(nombre):
    """Quita tildes y espacios: 'Dióxido de carbono' -> 'Dioxido_de_carbono'."""
    ascii_ = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    return ascii_.replace(" ", "_")


def main():
    SALIDA.mkdir(exist_ok=True)
    for nombre, smiles in MOLECULAS:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            print(f"SMILES no válido para {nombre}: {smiles}")
            continue
        ruta = SALIDA / f"{nombre_archivo(nombre)}.png"
        Draw.MolToFile(mol, str(ruta), size=(300, 300))
        print(f"Guardada: {ruta}")


if __name__ == "__main__":
    main()
