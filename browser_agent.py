"""
browser_agent.py
-----------------
Toda la interacción con Amazon Ads Console vive aquí. El resto del
sistema (analyzer, learner, safety) no sabe nada de navegadores ni de
selectores CSS — solo recibe/devuelve datos simples (dicts, listas).

IMPORTANTE — esto es el punto más frágil de todo el proyecto:
Amazon puede cambiar el HTML de su consola en cualquier momento sin avisar.
Los selectores de abajo (data-testid, texto de columnas) son un punto de
partida basado en la estructura vista el 24/09/2026 — verifícalos e
ajústalos con el inspector de Chrome (botón derecho > Inspeccionar) antes
de confiar en ellos para aplicar cambios reales con dinero.

Principio de diseño: si algo no se puede leer o confirmar con certeza,
NUNCA se asume — se lanza SessionExpiredError o ScrapeError y el agente
diario se detiene y avisa, en vez de seguir a ciegas.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

AUTH_DIR = Path(__file__).resolve().parent.parent / ".auth"
SESSION_FILE = AUTH_DIR / "session.json"
CAMPAIGNS_URL = "https://advertising.amazon.es/campaign-manager/all-campaigns"


class SessionExpiredError(Exception):
    """La sesión guardada ya no sirve — hay que volver a ejecutar capture_session.py."""


class ScrapeError(Exception):
    """La página no tiene la forma esperada — probablemente Amazon cambió el HTML."""


@dataclass
class KeywordRow:
    campaign_name: str
    campaign_id: str
    ad_group_name: str
    product_sku: str  # SKU (o ASIN si no hay SKU) del producto del grupo de
                       # anuncios — ver pestaña "Anuncios" del grupo. Esto es
                       # lo que learner.py usa para NO mezclar aprendizaje
                       # entre productos distintos, aunque compartan keyword.
    keyword_text: str
    match_type: str
    current_bid: float
    clicks: int
    cost: float
    sales: float
    orders: int

    @property
    def acos(self) -> Optional[float]:
        if self.sales <= 0:
            return None
        return self.cost / self.sales


@dataclass
class SearchTermRow:
    campaign_name: str
    ad_group_name: str
    product_sku: str
    search_term: str
    clicks: int
    cost: float
    sales: float
    orders: int
    avg_cpc: float  # cost / clicks — base para la puja inicial si se promueve


@dataclass
class ProductInfo:
    sku: str
    title: str
    category: str


class BrowserAgent:
    """Uso:
    with BrowserAgent() as agent:
        rows = agent.get_keyword_performance(days=7)
        agent.update_bid(rows[0], new_bid=0.65)
    """

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._pw = None
        self._browser = None
        self._context = None
        self.page: Optional[Page] = None

    def __enter__(self):
        if not SESSION_FILE.exists():
            raise SessionExpiredError(
                f"No existe {SESSION_FILE}. Ejecuta primero: "
                f"python src/capture_session.py"
            )
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(storage_state=str(SESSION_FILE))
        self.page = self._context.new_page()
        self._goto_campaigns_and_verify_login()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    # ------------------------------------------------------------------
    # Login / navegación base
    # ------------------------------------------------------------------

    def _goto_campaigns_and_verify_login(self):
        self.page.goto(CAMPAIGNS_URL)
        try:
            # Si la sesión caducó, Amazon redirige a una pantalla de login.
            # Ajusta este selector si detectas que el check falla en falso.
            self.page.wait_for_selector(
                "text=Campañas", timeout=15000
            )
        except PWTimeout:
            raise SessionExpiredError(
                "La sesión guardada parece haber caducado (no se encontró "
                "la vista de Campañas tras cargar la página). "
                "Ejecuta de nuevo: python src/capture_session.py"
            )

    # ------------------------------------------------------------------
    # Lectura de datos
    # ------------------------------------------------------------------

    def get_active_campaign_names(self) -> list[str]:
        """Devuelve los nombres de campañas visibles en la tabla principal.
        TODO: verificar el selector de filas de la tabla de campañas con el
        inspector — placeholder basado en la estructura vista manualmente.
        """
        rows = self.page.locator("table tbody tr")
        count = rows.count()
        if count == 0:
            raise ScrapeError(
                "La tabla de campañas está vacía o no se encontró. "
                "No asumir que 'no hay campañas' — puede ser un cambio de HTML."
            )
        names = []
        for i in range(count):
            name = rows.nth(i).locator("a").first.inner_text()
            names.append(name.strip())
        return names

    def get_keyword_performance(self, campaign_name: str) -> list[KeywordRow]:
        """Entra en una campaña concreta y lee la tabla de keywords/segmentación
        de cada grupo de anuncios.

        IMPORTANTE: cada KeywordRow debe llevar su product_sku. Para
        conseguirlo, por cada grupo de anuncios hace falta visitar también
        su pestaña "Anuncios" (URL termina en /ads, no /targeting) y leer
        la columna "SKU o ASIN" — normalmente hay un único producto por
        grupo, pero si hubiera varios, no asumas cuál: sin un producto
        inequívoco, no se puede indexar el aprendizaje correctamente y hay
        que lanzar ScrapeError en vez de adivinar.

        NOTA: esto es el scrape más importante y el más frágil. Antes de usarlo
        en real, ejecútalo en modo headless=False y compara visualmente los
        datos extraídos contra lo que ves en pantalla.
        """
        self.page.get_by_text(campaign_name, exact=False).first.click()
        self.page.wait_for_selector("text=Grupos de anuncios", timeout=15000)

        # TODO: por cada grupo de anuncios:
        #   1. entrar en su pestaña "Anuncios" (/ads) y leer el SKU/ASIN
        #      del producto (columna "SKU o ASIN"), p. ej. "5E-I8NY-S191"
        #   2. entrar en su pestaña "Segmentación" (/targeting) y parsear
        #      la tabla de keywords (Puja, Impresiones, Clics, Coste total,
        #      Compras, Ventas — activar estas columnas vía el botón
        #      "Columnas" si no aparecen en la vista por defecto)
        #   3. construir un KeywordRow por fila, con ese product_sku
        # Selectores pendientes de fijar contra la cuenta real — esto es
        # el esqueleto, no el scraper final.
        raise NotImplementedError(
            "Pendiente: fijar selectores exactos de la tabla de keywords "
            "y de la tabla de anuncios (para el SKU/ASIN) dentro de un "
            "grupo de anuncios. Hazlo con headless=False y el inspector "
            "de Chrome abierto sobre la campaña real."
        )

    # ------------------------------------------------------------------
    # Escritura (cambios de puja)
    # ------------------------------------------------------------------

    def update_bid(self, row: KeywordRow, new_bid: float) -> bool:
        """Cambia la puja de una keyword concreta. Devuelve True solo si
        se pudo CONFIRMAR el cambio releyendo el campo tras guardar.

        Nunca devuelve True "a ciegas" — si no se puede confirmar, lanza
        ScrapeError para que el llamador NO registre el cambio como aplicado.
        """
        raise NotImplementedError(
            "Pendiente: localizar el campo de puja de la keyword, "
            "escribir el nuevo valor, guardar, y releer el campo para "
            "confirmar que el valor guardado coincide con new_bid."
        )

    # ------------------------------------------------------------------
    # Descubrimiento de nuevas keywords (harvesting)
    # ------------------------------------------------------------------

    def get_search_terms(self, campaign_name: str) -> list[SearchTermRow]:
        """Lee la pestaña "Términos de búsqueda" de cada grupo de anuncios
        de la campaña (URL termina en /search-terms). A diferencia de
        get_keyword_performance, esto son búsquedas REALES de clientes,
        no las keywords que ya has configurado — es la fuente de la que
        se sacan candidatas a keyword nueva.

        Igual que con las keywords, cada fila necesita su product_sku
        (de la pestaña "Anuncios" del grupo) para que el aprendizaje de
        una keyword nueva no se mezcle entre productos desde el día 1.
        """
        raise NotImplementedError(
            "Pendiente: fijar selectores de la pestaña 'Términos de "
            "búsqueda' (Clics, Coste total, Compras, Ventas por término)."
        )

    def keyword_already_exists(self, ad_group_name: str, search_term: str) -> bool:
        """Comprueba si un término ya está añadido como keyword (en
        cualquier tipo de coincidencia) en ese grupo de anuncios, para no
        duplicarlo. Usa get_keyword_performance internamente o una
        consulta más ligera si el sitio lo permite.
        """
        raise NotImplementedError(
            "Pendiente: comprobar contra la tabla de Segmentación del "
            "grupo de anuncios."
        )

    def add_keyword(
        self,
        ad_group_name: str,
        keyword_text: str,
        match_type: str,
        bid: float,
    ) -> bool:
        """Añade una keyword nueva (botón 'Añadir palabras clave' visto en
        la pestaña Segmentación). Devuelve True solo si se pudo CONFIRMAR
        que la keyword aparece en la tabla tras guardar — igual que
        update_bid, nunca confirma a ciegas.

        Se usa tanto para keywords cosechadas (AÑADIR_KEYWORD) como para
        experimentos inventados (GENERAR_EXPERIMENTO) — la única
        diferencia entre ambos vive en marketing_agent.py, no aquí.
        """
        raise NotImplementedError(
            "Pendiente: usar el botón 'Añadir palabras clave', escribir "
            "keyword_text con coincidencia Exacta y la puja inicial, "
            "guardar, y releer la tabla para confirmar que aparece."
        )

    def pause_keyword(self, ad_group_name: str, keyword_text: str, match_type: str) -> bool:
        """Pausa una keyword existente (toggle 'Activo' a apagado en la
        tabla de Segmentación). Se usa para ejecutar MATAR_EXPERIMENTO
        (stop-loss). Igual que las demás escrituras: solo devuelve True
        si se confirma releyendo el estado tras el cambio.
        """
        raise NotImplementedError(
            "Pendiente: localizar la fila de la keyword en la tabla de "
            "Segmentación, apagar su toggle 'Activo', y releer el estado "
            "para confirmar que quedó en 'En pausa'."
        )

    def get_product_info(self, campaign_name: str, ad_group_name: str) -> ProductInfo:
        """Lee la pestaña "Anuncios" del grupo (SKU/ASIN, nombre del
        anuncio) para poder generar ideas de keywords con contexto real
        del producto. La "categoría" no siempre está expuesta directamente
        en esta pantalla — si no se puede leer con fiabilidad, usar el
        nombre del producto como único contexto y dejar category="" en vez
        de adivinar una categoría que podría ser incorrecta.
        """
        raise NotImplementedError(
            "Pendiente: leer la tabla de la pestaña Anuncios (Nombre del "
            "anuncio, SKU o ASIN) del grupo, como se vio para "
            "'Soporte Movil Coche Universal Ajustable 360...' (B0DHYBY6MS)."
        )
