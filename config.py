"""
config.py — todos los números del agente autónomo en un solo sitio.

Cada valor sale de AGENTE_AUTONOMO.md (conversación de diseño con Juan, 26-27/09/2026).
Los que Juan fijó como NO negociables están marcados así. El resto son ajustables, pero
cualquier cambio lo decide Juan (CLAUDE.md: las reglas de seguridad no se relajan solas).
"""

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent

# ---------------------------------------------------------------- archivos
# Una subcarpeta por día (AAAA-MM-DD) en cada una (carpetas.py):
#   entradas/<día>/  la hoja masiva descargada de Amazon y Documento_investigacion_keywords.xlsx
#   salidas/<día>/   la memoria actualizada (documento único, AGENTE_AUTONOMO.md §4), la hoja de
#                    cambios para subir a Amazon y los correos que no se pudieron enviar.
# La memoria de cada día parte de la del día anterior más reciente. resultados/memoria.xlsx y
# memoria_pou.xlsx son la memoria de la etapa manual: el agente no las toca.
ENTRADAS = Path(os.environ.get("AGENTE_ENTRADAS", RAIZ / "entradas"))
SALIDAS = Path(os.environ.get("AGENTE_SALIDAS", RAIZ / "salidas"))
NOMBRE_MEMORIA = "memoria_agente.xlsx"
PREFIJO_INVESTIGACION = "documento_investigacion"   # Documento_investigacion_keywords.xlsx (Cowork)
NOMBRES_CORTOS = {"B0DCZS1NR6": "Pinza", "B0DHYBY6MS": "Rejilla", "B0DSV986XY": "Ventosa",
                  "B0F746MFPQ": "3 en 1", "B0CPHXXHRQ": "Pou"}   # para hojas, informes y nombres de campaña
HISTORICO_XLSX = Path(os.environ.get("AGENTE_HISTORICO", RAIZ / "FreshFinder_Amazon_Ads_historico.xlsx"))
CORREOS_PENDIENTES = SALIDAS / "correos_pendientes"   # agente.py la pone dentro de la carpeta del día

# ---------------------------------------------------------------- objetivo de negocio
ACOS_OBJETIVO_MIN = 0.30            # rango objetivo 30-35 %
ACOS_OBJETIVO_MAX = 0.35
ACOS_MAX_KEYWORD_NUEVA = 0.30       # §2.3: una keyword nueva entra solo con ACOS predicho ≤ 30 %
ACOS_CLARAMENTE_BUENA = 0.25        # §2.6: candidata "claramente buena" para abrir campaña nueva

# ---------------------------------------------------------------- ronda de decisión (§2.1)
DIAS_ENTRE_CAMBIOS = 3              # ≥ 3 días desde el último cambio del elemento…
MIN_CLICS_NUEVOS = 10               # …y ≥ 10 clics nuevos desde ese cambio
DIAS_MADUREZ = 7                    # atribución de Amazon: un clic "madura" a los 7 días

# ---------------------------------------------------------------- pujas (§2.2)
PUJA_MINIMA_AMAZON = 0.02           # suelo real de Amazon (único límite duro de la puja)
ESTRATEGIA_PUJAS = "LEGACY_FOR_SALES"  # "Pujas dinámicas: solo a la baja" en la API v3
CAMBIO_MINIMO_PUJA_EUR = 0.02       # no se mueve una puja por menos de esto…
CAMBIO_MINIMO_PUJA_PCT = 0.05       # …ni por menos del 5 % (evita ruido: cambios que no cambian nada)
PRIOR_CLICS = 20                    # peso del modelo frente a los datos propios de la keyword:
                                    # con 20 clics maduros propios pesan igual que el modelo
MIN_COMPRAS_MODELO = 10             # producto con < 10 compras: el modelo no es fiable (se usa
PUJA_MAX_SIN_MODELO = 0.30          # su conversión media) y las keywords nuevas pujan ≤ 0,30 €
PUJA_GRUPO_DEFECTO = 0.30
# CPC calibrado (mejoras P1-B.2): la "puja recomendada baja" de Amazon se queda corta frente a lo
# que se paga de verdad (histórico: ×2,35 en la rejilla, ×1,38 en la pinza). CPC estimado =
# puja sugerida × mediana(CPC pagado / puja rec. baja) de las keywords del producto con ≥ 5 clics.
# Nunca por debajo de ×1: con pocos datos el factor solo puede hacer la predicción más prudente.
FACTOR_CPC_MIN_CLICS = 5
FACTOR_CPC_MIN_FILAS = 5

# ---------------------------------------------------------------- estrategia de pujas (mejoras P0-B §4)
# Gestión autorizada por Juan (especificación de mejoras, 28/09/2026): el agente elige por campaña
# entre "solo a la baja" y "al alza y a la baja" (pujas.elegir_estrategia).
ALZA_MIN_COMPRAS_30D = 10           # "al alza y a la baja" solo con ≥ 10 compras maduras en 30 días…
                                    # …y ACOS ≤ equilibrio (campaña probada, como el fondo del 80 %)
# Cuánto puede subir Amazon la puja escrita con "al alza y a la baja" (ayuda de Amazon Ads):
SUBIDA_DINAMICA_SUPERIOR = 1.00     # hasta +100 % en la parte superior de la búsqueda (1ª página)
SUBIDA_DINAMICA_RESTO = 0.50        # hasta +50 % en el resto de emplazamientos
# ACOS a partir del cual cada venta pierde dinero. Lo calcula finanzas.py con los costes de la hoja
# "Economía" (P0-B §2); para los productos sin costes rellenados, el máximo del objetivo (35 %).
ACOS_EQUILIBRIO_DEFECTO = ACOS_OBJETIVO_MAX
ACOS_EQUILIBRIO_POR_ASIN = {}       # lo rellena finanzas.aplicar() en cada ronda


def acos_equilibrio(asin=None):
    return ACOS_EQUILIBRIO_POR_ASIN.get(asin, ACOS_EQUILIBRIO_DEFECTO)

# ---------------------------------------------------------------- keywords (§2.3, §2.4)
MAX_KEYWORDS_POR_GRUPO = 12         # por campaña / grupo de anuncios, cada producto por su cuenta
COINCIDENCIA_NUEVAS = "Frase"
STOPLOSS_CLICS_MADUROS = 20         # pausar a los 20 clics maduros…
STOPLOSS_COSTE_MADURO_EUR = 4.0     # …o 4 € gastados en clics maduros, sin ninguna venta
PAUSAS_PARA_REVISION = 2            # pausada 2 veces -> se marca para que Juan la revise

# ---------------------------------------------------------------- presupuesto (§2.5) — NO negociable
TOPE_MENSUAL_EUR = 840.0            # techo duro (cartera de Amazon). Solo Juan lo cambia.
PCT_EXPERIMENTACION = 0.20          # 20 % global para lo que aún no está probado (168 €/mes)
PRESUPUESTO_MINIMO_AMAZON = 1.0     # mínimo técnico de Amazon por campaña y día
PRESUPUESTO_MIN_CAMPANA_EXPERIMENTAL = 2.5  # §2.6: abrir campaña cuesta dinero "significativo";
                                    # si al repartir el fondo le tocaría menos, no se abre
CAMBIO_MINIMO_PRESUPUESTO_EUR = 0.5
CAMBIO_MINIMO_PRESUPUESTO_PCT = 0.10
DIAS_ENTRE_SUBIDAS_PRESUPUESTO = 3
PROBADO_MIN_COMPRAS_HISTORICO = 10  # producto con ≥ 10 compras en el histórico = "probado"
GRADUACION_MIN_COMPRAS = 3          # campaña experimental que ya vende: ≥ 3 compras maduras…
GRADUACION_ACOS_MAX = ACOS_OBJETIVO_MAX  # …con ACOS ≤ 35 % pasa al 80 %
VENTANA_PUNTUACION_DIAS = 30        # ACOS de campaña para repartir el 80 %: últimos 30 días maduros

# ---------------------------------------------------------------- campañas nuevas (§2.6)
MAX_CAMPANAS_NUEVAS_POR_RONDA = 1
MIN_KEYWORDS_CAMPANA_NUEVA = 3      # sin 3 candidatas que pasen el filtro no se abre nada

# ---------------------------------------------------------------- alertas (§2.9)
EMAIL_DESTINO = os.environ.get("AGENTE_EMAIL_DESTINO", "yubunama62@gmail.com")

# ---------------------------------------------------------------- investigación (§2.11)
MODELO_INVESTIGACION = os.environ.get("AGENTE_MODELO_LLM", "claude-opus-5")
DIAS_ENTRE_INVESTIGACIONES = 7
MAX_CANDIDATAS_INVESTIGACION = 25

# ---------------------------------------------------------------- datos de la API
DIAS_INICIALES_INFORME = 60         # primera ejecución: pide los últimos 60 días
DIAS_REFRESCO_INFORME = 10          # después, vuelve a pedir los últimos 10 (ventas que llegan tarde)
