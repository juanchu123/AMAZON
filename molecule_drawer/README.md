# Moléculas: dibujo 2D, visor 3D y perfil ADMET

Herramientas para cargar moléculas por SMILES, verlas y estimar su perfil ADMET.

## Instalación

```bash
pip install -r requirements.txt   # rdkit + numpy
```

## Herramientas

### 1. Dibujo 2D — `molecule_drawer.py`
Guarda cada molécula de la lista `MOLECULAS` como PNG en `imagenes/`.
```bash
python molecule_drawer.py
```
Para añadir moléculas, edita la lista `MOLECULAS` (la comparten todos los scripts).

### 2. Visor 3D — `molecule_viewer_3d.py`
Calcula la geometría 3D (RDKit: ETKDG + MMFF) y genera `visor_3d.html`, un visor
interactivo (3Dmol.js) donde se puede girar, hacer zoom y cambiar de estilo. Cada
molécula muestra su perfil ADMET.
```bash
python molecule_viewer_3d.py     # -> abre visor_3d.html en el navegador
```

### 3. Perfil ADMET — `admet.py`
Estima el perfil ADMET con RDKit a partir de reglas empíricas (Lipinski, Veber,
Egan, ESOL, QED) y alertas estructurales (PAINS, Brenk). Metabolismo y excreción
se marcan como no estimables en vez de inventarlos.
```bash
python admet.py                   # perfil de todas las moléculas por consola
```

### 4. API — `admet_api.py`
Puente entre RDKit/NumPy y modelos de DeepChem/PyTorch/TensorFlow. Siempre
devuelve la capa por reglas; si instalas DeepChem con su motor y un modelo
entrenado, añade predicciones ML (CYP, hERG...). Si no, lo dice explícitamente.
```bash
python admet_api.py "CCO"         # imprime el perfil en JSON
python admet_api.py --serve       # API HTTP: GET /admet?smiles=CCO   (necesita flask)
```
Capa de modelos (opcional, pesada): `pip install deepchem torch` (o `tensorflow`).

### 5. Simulador ADMET — `simulador_admet.html`
Página web independiente: escribes un SMILES y calcula el perfil ADMET aproximado
en el propio navegador con OpenChemLib (`vendor/openchemlib.js`). Como carga la
librería como módulo ES, hay que servirlo por HTTP (no vale abrirlo con `file://`):
```bash
python servir_simulador.py        # abre http://127.0.0.1:8000/simulador_admet.html
```

## Nota sobre las estimaciones
El ADMET calculado aquí son **reglas empíricas orientativas**, no un modelo
entrenado ni datos de laboratorio. Para predicciones de verdad (metabolismo,
excreción, toxicidad), enchufa un modelo a través de `admet_api.py`.
