# Agente de página de producto — FreshFinder

Audita cada semana la página de producto (listing) de tus ASIN en Amazon.es, decide qué campo toca mejorar,
prepara la propuesta y te la deja **lista para copiar y pegar** en Seller Central. Guarda en una memoria
cada cambio y cómo ha ido según el agente evaluador. **No publica nunca nada en Amazon**: eso lo haces tú.

Diseño completo: `AGENTE_PAGINA_PRODUCTO.md` y la guía "Product page inmejorable en Amazon.es".

## 1. Instalar

```bash
cd listing_agent
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp config.example.json config.json
cp .env.example .env              # y rellena las credenciales
```

- **SP-API**: `SP_API_CLIENT_ID`, `SP_API_CLIENT_SECRET`, `SP_API_REFRESH_TOKEN` y `SP_API_SELLER_ID` de tu
  app en Seller Central (Apps y servicios → Desarrollar apps). La app necesita los roles de **Listados de
  productos** (Listings y Catalog), **Inventario y seguimiento de pedidos** (inventario FBA) y **Análisis de ventas
  y tráfico** o similar (informe de negocio). Si falta alguno, el informe lo dice y sigue con lo demás.
- **Email**: con Gmail, activa la verificación en dos pasos y crea una *contraseña de aplicación* para `SMTP_PASSWORD`.
- **config.json**: revisa la keyword principal, las keywords semilla, las marcas de la competencia y las
  rutas a los CSV de Ads. Las rutas son relativas a la carpeta donde esté `config.json`.

## 2. Programarlo (una vez por semana)

```bash
# cron: lunes a las 8:52
52 8 * * 1 cd /ruta/a/listing_agent && venv/bin/python main.py auditar >> informes/cron.log 2>&1
```

En Windows: Programador de tareas → `venv\Scripts\python.exe main.py auditar`, con la carpeta del agente
como directorio de inicio.

## 3. El ciclo

| Paso | Quién | Comando |
|---|---|---|
| Diagnóstico + brief + email | el agente (cron) | `python main.py auditar` |
| Redactar la propuesta | Cowork (ver `COWORK.md`) o la API si algún día hay `ANTHROPIC_API_KEY` | — |
| Validar y generar el paquete | Cowork o tú | `python main.py validar trabajo/propuesta_X.json --preview-amazon` |
| Publicar en Seller Central | **tú** | copiar y pegar desde `trabajo/paquete_<ID>.md` |
| Marcar como publicado | tú (o lo detecta solo la siguiente auditoría) | `python main.py aplicado <ID>` |
| Evaluar a los 7–14 días | el agente evaluador | `python main.py resultado <ID> --veredicto mejora\|empeora\|neutro` |
| Deshacer si empeoró | tú | `python main.py revertir <ID>` |
| No publicar una propuesta | tú | `python main.py descartar <ID>` |
| Ver la memoria | — | `python main.py memoria` |

## 4. La memoria (para el agente evaluador)

Todo vive en `logs/` en archivos JSON Lines, una línea por evento:

- `listing_changes.jsonl`: lo escribe este agente. Contiene `id`, `asin`, `campo`, `estado`
  (propuesto/aplicado/descartado), `valor_antes`, `valor_despues`, el estado completo anterior, el motivo,
  el riesgo, `metricas_base` (sesiones, conversión, Buy Box…) e `indexacion_base`.
- `listing_outcomes.jsonl`: **lo escribe el agente evaluador**, con el comando `resultado` o añadiendo
  líneas directamente:

  ```json
  {"change_id": "LST-20261001-B0DHYBY6MS-titulo-1a2b", "asin": "B0DHYBY6MS", "campo": "titulo",
   "fecha_evaluacion": "2026-10-15", "ventana": "7-14d",
   "metricas_despues": {"sesiones": 140, "conversion_pct": 7.1},
   "veredicto": "mejora", "notas": "", "agente": "evaluador"}
  ```

  `veredicto` solo puede ser `mejora`, `empeora` o `neutro`. Con el comando, un id inexistente o un cambio
  que no esté aplicado se rechazan.
- `listing_events_for_ads.jsonl`: avisos para el agente de Ads (`cambio_previsto`, `cambio_aplicado`,
  `titulo_cambiado_fuera_del_agente`). De momento solo se escriben; la lectura desde el agente de Ads
  queda pendiente.
- `listing_indexation.jsonl`: resultado de cada comprobación de indexación.
- `snapshots/<ASIN>/<fecha>.json`: foto semanal del listing, para detectar cambios que nadie ha registrado
  (por ejemplo, la IA de Amazon reescribiendo un título largo, que sin Brand Registry no avisa).

Antes de proponer, el agente lee esta memoria y la incluye en el brief: lo que empeoró no se repite, y lo
que funcionó se toma como referencia. Si el último cambio empeoró, el informe propone revertirlo.

## 5. Reglas que el código impone (no se pueden saltar)

- **Solo lectura en Amazon.** El cliente SP-API bloquea cualquier escritura. La única excepción es
  `VALIDATION_PREVIEW`, que valida sin publicar.
- **Un cambio cada vez.** No se genera otra propuesta mientras haya una sin publicar o descartar.
- **Esperas entre cambios.** 14 días tras un cambio sin evaluar, 7 si ya está evaluado y 42 días entre cambios
  de título. Una corrección de error real (título por encima de 75 caracteres, backend por encima del límite o
  error de Amazon en ese campo) se salta la espera, pero el validador comprueba que el error existe.
- **Límites.** Título de 75 caracteres, Item Highlights de 125, 5 bullets de 250 caracteres como máximo cada uno,
  descripción de 2.000 y backend de 249 bytes menos 5 de margen. Si el esquema de Amazon da un valor más bajo,
  se usa ese. El paquete indica de dónde sale cada límite.
- **Contenido prohibido.** Marcas de la competencia, marcas de móviles en el backend, ASIN, URL, emails,
  teléfonos, lenguaje promocional, emojis y afirmaciones de seguridad o conformidad que legal no haya
  confirmado (`claims_confirmados_por_legal`).
- **Estado anterior siempre guardado** para poder revertir.

## 6. Límites honestos

- **Indexación.** La SP-API no dice si un ASIN está indexado para una keyword. Se aproxima buscando la
  keyword en el catálogo. "Encontrado" es una buena señal; "no encontrado" no prueba nada. El informe incluye el
  enlace *keyword + ASIN* de Amazon.es para comprobarlo a mano en una ventana de incógnito.
- **Sin Brand Registry** no hay Brand Analytics, A+, pruebas A/B, CTR orgánico ni aviso de 14 días antes de que
  Amazon reescriba un título. El CTR se puede aproximar con los datos de Ads.
- **No se pueden leer por la SP-API** las reseñas, el vídeo ni si la imagen principal tiene fondo blanco.
  Salen como ❓ en el checklist.
- El nombre del atributo **Item Highlights** se lee del esquema de Amazon. Si el esquema no lo trae, el
  agente lo indica y no se inventa un nombre.

## 7. Pruebas

```bash
python -m unittest discover -s tests
```

Las pruebas simulan Amazon con un cliente falso y no necesitan credenciales.
