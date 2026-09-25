"""
commands.py
-----------
El contrato entre los dos agentes. El agente de marketing (marketing_agent.py)
NUNCA toca el navegador — solo mira datos y devuelve una lista de Command.
El subagente (browser_agent.py) NUNCA decide nada — solo recibe un Command
y lo ejecuta contra Amazon Ads, confirmando que se aplicó de verdad.

Esta frontera es la que permite pensar en ellos como dos agentes separados:
uno "sabe de marketing", el otro "sabe de Amazon Ads y navegadores". Ninguno
necesita saber cómo funciona el otro por dentro.
"""

from dataclasses import dataclass
from typing import Optional

from analyzer import Action


@dataclass
class Command:
    """Una orden concreta que el subagente debe ejecutar. Todo lo que el
    subagente necesita para actuar y para registrar el resultado va aquí
    dentro — no debe tener que volver a preguntarle nada al agente de
    marketing a mitad de la ejecución.
    """
    action: Action
    producto: str          # SKU/ASIN — para el aprendizaje, nunca se pierde
    campana: str            # trazabilidad humana
    ad_group: str
    keyword: str
    match_type: Optional[str]   # requerido para AÑADIR_KEYWORD
    valor_antes: Optional[float]
    valor_despues: Optional[float]
    motivo: str
    # "Foto" del rendimiento de la keyword EN EL MOMENTO de esta decisión
    # (solo aplica a subida_puja/bajada_puja). Sin esto, learner.py no
    # puede saber más adelante si el cambio mejoró algo o no — comparar
    # contra el acumulado histórico completo mezclaría el antes y el
    # después. Los rellena sanitize_commands() a partir del KeywordRow
    # real, nunca la IA.
    clics_base: Optional[int] = None
    coste_base: Optional[float] = None
    ventas_base: Optional[float] = None
