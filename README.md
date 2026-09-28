# FreshFinder — Agente autónomo de Amazon Ads

Diseño: `AGENTE_AUTONOMO.md` (qué decide y por qué) y `CLAUDE.md` (resumen para Claude Code).
Esto es el "cómo lo pongo en marcha".

## 1. Instalar (una vez)

Python 3.10 o más nuevo.

```bash
cd AMAZON
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Configurar (variables de entorno, en TU ordenador)

Nunca pegues estas claves en un chat ni las subas a GitHub.

| Variable | Para qué | Obligatoria |
|---|---|---|
| `AMAZON_ADS_CLIENT_ID` | App de Login with Amazon con acceso a la Amazon Ads API | Sí (modo API) |
| `AMAZON_ADS_CLIENT_SECRET` | ídem | Sí (modo API) |
| `AMAZON_ADS_REFRESH_TOKEN` | el token que da el alta OAuth de tu cuenta de Ads | Sí (modo API) |
| `AMAZON_ADS_PROFILE_ID` | perfil de anunciante; si falta, se usa el de España | No |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | enviar los correos a yubunama62@gmail.com (Gmail: `smtp.gmail.com`, 587, contraseña de aplicación) | No: sin ellas los correos quedan en `salidas/<día>/correos_pendientes/` |
| `ANTHROPIC_API_KEY` | investigación de mercado semanal con Claude (unos céntimos por producto y semana) | No: sin ella no se investiga |
| `AGENTE_MODELO_LLM` | modelo para la investigación (por defecto `claude-opus-5`) | No |
| `AGENTE_ENTRADAS`, `AGENTE_SALIDAS` | carpetas de entrada y salida (por defecto `entradas/` y `salidas/`, una subcarpeta por día) | No |

Mac/Linux: `export VARIABLE=valor` (o en `~/.bashrc`). Windows: `setx VARIABLE valor`.

## 3. Primera ejecución: simulación

```bash
python agente.py --simular
```

Lee la cuenta, guarda los datos del día en el documento único y **cuenta lo que haría sin tocar Amazon** (lo verás en pantalla y en un correo "(simulación)"). Compáralo con lo que ves en la consola de Amazon Ads.

Si todas las campañas están en pausa, el agente te avisa y se para: no reactiva nada. Actívalas tú cuando la cuenta esté bien.

## 4. Modo real

```bash
python agente.py
```

- Con credenciales de la API: aplica los cambios, **relee Amazon para confirmar cada uno** y te manda un correo con todo lo que cambió.
- Sin API: usa la hoja masiva de la carpeta más reciente de `entradas/AAAA-MM-DD/` (Operaciones en bloque → descargar Sponsored Products, desde la creación de las campañas hasta hoy) y genera `salidas/<hoy>/bulk_cambios_<fecha>.xlsx` para que la subas. Los cambios se confirman al leer la siguiente descarga. Si en la misma carpeta está `Documento_investigacion_keywords.xlsx`, se importa a la hoja "Investigación".

Se puede lanzar las veces que quieras (cada keyword lleva su propio reloj). Recomendado: una vez al día.

- Mac/Linux: `crontab -e` → `15 9 * * * cd /ruta/AMAZON && venv/bin/python agente.py >> salidas/agente.log 2>&1`
- Windows: Programador de tareas → `venv\Scripts\python.exe agente.py`, con la carpeta del proyecto como directorio de trabajo.

Opciones: `--investigar` (fuerza la investigación de mercado), `--sin-investigacion`, `--fuente api|bulk`, `--entrada entradas/AAAA-MM-DD`, `--bulk archivo.xlsx`, `--documento ruta.xlsx`.

Códigos de salida: 0 bien, 1 error (te llega un correo con el detalle), 2 parado por la cuenta.

## 5. El documento único

`salidas/<día>/memoria_agente.xlsx` (cada día parte de la del día anterior). Lo que más vas a mirar:

- **Resumen**: la última ronda en cifras (gasto del mes, tope, cambios).
- **Segmentación**: cada keyword/ASIN, su estado y la decisión de esta ronda. Columna "Requiere revisión de Juan".
- **Tickets**: cada cambio con motivo, si se confirmó en Amazon y su veredicto (mejora/empeora) cuando madura.
- **Competencia**: ASIN de la competencia. **Pon "Sí" en "Confirmado por Juan"** en los que quieras que el agente pueda usar.

Ciérralo mientras corre el agente. Si quieres que Claude/Cowork lo vea, haz commit y push.

## 6. Tests

```bash
python -m pytest tests/ -q
```

Prueban todas las reglas con una API de Amazon falsa (nunca tocan tu cuenta).

## 7. Otras herramientas

- `python keyword_ml.py --producto pinza` — el modelo de keywords por producto.
- `python crear_memoria.py …` — campañas iniciales en hoja masiva (skill `crear-campana`).
- `legacy/` — el sistema anterior (navegador + LLM decidiendo). Ya no se usa.
