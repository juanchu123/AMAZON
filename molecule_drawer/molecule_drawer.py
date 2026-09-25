"""Dibuja moléculas sencillas en 2D a partir de SMILES y las guarda como PNG."""

from pathlib import Path

from rdkit import Chem
from rdkit.Chem import Draw

MOLECULAS = [
    ("Metano", "C"),
    ("Oxigeno", "O=O"),
    ("Agua", "O"),
    ("Dioxido_de_carbono", "O=C=O"),
    ("Amoniaco", "N"),
    ("Etanol", "CCO"),
    ("Benceno", "c1ccccc1"),
    ("Cafeina", "CN1C=NC2=C1C(=O)N(C(=O)N2C)C"),
]

SALIDA = Path(__file__).parent / "imagenes"


def main():
    SALIDA.mkdir(exist_ok=True)
    for nombre, smiles in MOLECULAS:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            print(f"SMILES no válido para {nombre}: {smiles}")
            continue
        ruta = SALIDA / f"{nombre}.png"
        Draw.MolToFile(mol, str(ruta), size=(300, 300))
        print(f"Guardada: {ruta}")


if __name__ == "__main__":
    main()
