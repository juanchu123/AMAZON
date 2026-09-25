"""Perfil ADMET estimado con RDKit a partir de reglas publicadas.

No son predicciones de un modelo entrenado: son descriptores fisicoquímicos y
reglas empíricas clásicas (Lipinski, Veber, Egan, ESOL, QED) más alertas
estructurales (PAINS, Brenk). El metabolismo (CYP) y la excreción no se pueden
estimar con reglas sencillas, así que no se inventan.
"""

from rdkit import Chem
from rdkit.Chem import QED, Crippen, Descriptors, rdMolDescriptors
from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams

_CATALOGOS = {}
for _nombre, _tipo in [("PAINS", FilterCatalogParams.FilterCatalogs.PAINS),
                       ("Brenk", FilterCatalogParams.FilterCatalogs.BRENK)]:
    _params = FilterCatalogParams()
    _params.AddCatalog(_tipo)
    _CATALOGOS[_nombre] = FilterCatalog(_params)


def _num(x, decimales=2):
    return f"{x:.{decimales}f}".replace(".", ",")


def _solubilidad_esol(mol, logp, mw, rotables):
    """ESOL (Delaney, 2004): logS en mol/L."""
    pesados = mol.GetNumHeavyAtoms()
    aromaticos = sum(1 for a in mol.GetAtoms() if a.GetIsAromatic())
    proporcion_aromatica = aromaticos / pesados if pesados else 0
    return 0.16 - 0.63 * logp - 0.0062 * mw + 0.066 * rotables - 0.74 * proporcion_aromatica


def _clase_solubilidad(logs):
    if logs < -10:
        return "Insoluble", "mal"
    if logs < -6:
        return "Poco soluble", "mal"
    if logs < -4:
        return "Moderadamente soluble", "aviso"
    if logs < -2:
        return "Soluble", "bien"
    return "Muy soluble", "bien"


def calcular(mol):
    """Devuelve el perfil ADMET de una molécula (sin hidrógenos explícitos)."""
    mol = Chem.RemoveHs(mol)
    mw = Descriptors.MolWt(mol)
    logp = Crippen.MolLogP(mol)
    tpsa = rdMolDescriptors.CalcTPSA(mol)
    hbd = rdMolDescriptors.CalcNumLipinskiHBD(mol)
    hba = rdMolDescriptors.CalcNumLipinskiHBA(mol)
    rotables = rdMolDescriptors.CalcNumRotatableBonds(mol)
    fsp3 = rdMolDescriptors.CalcFractionCSP3(mol)
    qed = QED.qed(mol)
    logs = _solubilidad_esol(mol, logp, mw, rotables)

    incumplimientos = [nombre for nombre, falla in [
        ("MW > 500", mw > 500), ("LogP > 5", logp > 5),
        ("donadores H > 5", hbd > 5), ("aceptores H > 10", hba > 10)] if falla]
    veber = rotables <= 10 and tpsa <= 140
    absorcion_gi = tpsa <= 131.6 and logp <= 5.88
    bhe = tpsa < 90 and mw < 450
    clase_sol, estado_sol = _clase_solubilidad(logs)

    alertas = []
    for catalogo, filtro in _CATALOGOS.items():
        for coincidencia in filtro.GetMatches(mol):
            alertas.append(f"{catalogo}: {coincidencia.GetDescription()}")

    criterios = [
        {"grupo": "Absorción", "nombre": "Regla de Lipinski",
         "valor": "Cumple" if not incumplimientos else f"{len(incumplimientos)} incumplimiento(s): " + ", ".join(incumplimientos),
         "estado": "bien" if len(incumplimientos) <= 1 else "mal",
         "detalle": "Se tolera 1 incumplimiento para fármacos orales."},
        {"grupo": "Absorción", "nombre": "Regla de Veber",
         "valor": "Cumple" if veber else "No cumple",
         "estado": "bien" if veber else "aviso",
         "detalle": "Enlaces rotables ≤ 10 y TPSA ≤ 140 Å²."},
        {"grupo": "Absorción", "nombre": "Absorción intestinal",
         "valor": "Alta" if absorcion_gi else "Baja",
         "estado": "bien" if absorcion_gi else "mal",
         "detalle": "Regla de Egan: TPSA ≤ 131,6 Å² y LogP ≤ 5,88."},
        {"grupo": "Absorción", "nombre": "Solubilidad en agua (ESOL)",
         "valor": f"{clase_sol} (logS {_num(logs)})",
         "estado": estado_sol,
         "detalle": "Ecuación de Delaney; logS en mol/L."},
        {"grupo": "Distribución", "nombre": "Barrera hematoencefálica",
         "valor": "Probable que la cruce" if bhe else "Poco probable",
         "estado": "info",
         "detalle": "TPSA < 90 Å² y MW < 450 (perfil típico de fármacos del SNC)."},
        {"grupo": "Metabolismo", "nombre": "Inhibición de CYP450",
         "valor": "No estimable", "estado": "na",
         "detalle": "Requiere un modelo entrenado; no hay una regla sencilla fiable."},
        {"grupo": "Excreción", "nombre": "Aclaramiento y vida media",
         "valor": "No estimable", "estado": "na",
         "detalle": "Requiere un modelo entrenado; no hay una regla sencilla fiable."},
        {"grupo": "Toxicidad", "nombre": "Alertas estructurales",
         "valor": "Ninguna" if not alertas else f"{len(alertas)} alerta(s)",
         "estado": "bien" if not alertas else "aviso",
         "detalle": "; ".join(alertas) if alertas else "Sin coincidencias en los filtros PAINS ni Brenk."},
        {"grupo": "Tipo fármaco", "nombre": "QED",
         "valor": _num(qed),
         "estado": "bien" if qed >= 0.67 else "aviso" if qed >= 0.49 else "mal",
         "detalle": "De 0 a 1. ≥ 0,67 atractivo; < 0,49 poco atractivo (Bickerton, 2012)."},
    ]

    return {
        "descriptores": {
            "LogP": _num(logp), "TPSA": f"{_num(tpsa, 1)} Å²",
            "Donadores H": str(hbd), "Aceptores H": str(hba),
            "Enlaces rotables": str(rotables), "Fsp3": _num(fsp3),
        },
        "criterios": criterios,
    }


if __name__ == "__main__":
    from molecule_drawer import MOLECULAS

    for nombre, smiles in MOLECULAS:
        perfil = calcular(Chem.MolFromSmiles(smiles))
        print(f"\n{nombre} ({smiles})")
        print("  " + " · ".join(f"{k} {v}" for k, v in perfil["descriptores"].items()))
        for c in perfil["criterios"]:
            print(f"  [{c['estado']:>5}] {c['grupo']} / {c['nombre']}: {c['valor']}")
