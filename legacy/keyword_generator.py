"""
keyword_generator.py
---------------------
Genera ideas de keywords NUEVAS, sin ningún dato real detrás — a
diferencia del harvesting (analyzer.decide_new_keyword_action), que solo
promueve términos que YA tienen clics y ventas reales.

Esto es una apuesta deliberada: el sistema usa su propio criterio (vía la
API de Claude) para imaginar frases de búsqueda que un cliente podría usar
y que todavía no se han probado, con la idea de aprender cuáles funcionan.
El riesgo de esa apuesta lo limita safety.py (fondo de exploración +
stop-loss), no este módulo.

Requiere la variable de entorno ANTHROPIC_API_KEY (una API key propia de
Juan desde console.anthropic.com — distinta de cualquier acceso a Claude
que use en el chat o en Claude Code). Ver README.md para cómo conseguirla.
"""

import json
import os

import anthropic

MODEL = os.environ.get("KEYWORD_GENERATOR_MODEL", "claude-sonnet-4-5")


def generate_keyword_ideas(
    product_title: str,
    product_category: str,
    already_tried: set[str],
    count: int,
) -> list[str]:
    """Devuelve hasta `count` frases de búsqueda nuevas para probar como
    keywords, en español, que un cliente real podría escribir para
    encontrar este producto — evitando cualquier frase ya presente en
    `already_tried` (keywords ya configuradas + experimentos ya probados
    antes, ganados o perdidos).

    Si la llamada a la API falla por cualquier motivo, devuelve una lista
    vacía — nunca inventa nada localmente ni deja pasar una excepción que
    pudiera confundirse con "sin ideas por diseño".
    """
    client = anthropic.Anthropic()  # usa ANTHROPIC_API_KEY del entorno

    tried_list = "\n".join(f"- {kw}" for kw in sorted(already_tried)) or "(ninguna todavía)"

    prompt = f"""Eres un especialista en Amazon PPC para FreshFinder, una tienda de
juguetes y artículos de deporte. Necesito {count} frases de búsqueda NUEVAS
para probar como keywords de Amazon Ads en el siguiente producto:

Producto: {product_title}
Categoría: {product_category}

Frases que YA se han probado (no las repitas, ni variaciones triviales de ellas):
{tried_list}

Genera {count} frases de búsqueda distintas, realistas, cortas (2-5 palabras),
en español de España, que un cliente real podría escribir en Amazon para
encontrar este producto. Piensa en variaciones de uso, público objetivo,
características o problemas que resuelve — no solo sinónimos del nombre.

Responde ÚNICAMENTE con un array JSON de strings, sin texto adicional,
sin backticks ni markdown. Ejemplo de formato: ["frase uno", "frase dos"]"""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=500,
            temperature=0.9,  # aquí sí queremos variedad e ideas poco obvias
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        ideas = json.loads(text)
        if not isinstance(ideas, list):
            return []
        # Filtro de seguridad extra: nunca devolver algo ya probado, aunque
        # el modelo se equivoque y lo repita.
        return [
            idea.strip() for idea in ideas
            if isinstance(idea, str) and idea.strip().lower() not in
            {t.lower() for t in already_tried}
        ][:count]
    except Exception as e:
        print(f"  [keyword_generator] No se pudieron generar ideas: {e}")
        return []
