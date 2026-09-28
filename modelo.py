"""
modelo.py — las estructuras de datos que comparten todas las piezas del agente.

Las fuentes (ads_api.py, fuente_bulk.py) solo producen estas estructuras; el motor
(analyzer.py, presupuesto.py, campanas.py) solo las consume. Así, cambiar de fuente
(API oficial, hoja masiva descargada…) no toca ni una línea de las reglas.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

ACTIVO, PAUSADO, ARCHIVADO = "activo", "pausado", "archivado"
FINALIZADA = "finalizada"               # campaña activada pero con la fecha de finalización ya pasada:
                                        # Amazon no la sirve, así que para el agente no está activa

# estrategia de pujas de una campaña (columna "Estrategia de pujas" / dynamicBidding.strategy)
SOLO_BAJA, ALZA_BAJA, PUJA_FIJA, ESTRATEGIA_DESCONOCIDA = (
    "Pujas dinámicas: solo a la baja", "Pujas dinámicas: al alza y a la baja", "Puja fija", "")

# emplazamientos (hoja "Ajuste de puja" / dynamicBidding.placementBidding)
SUPERIOR, RESTO_BUSQUEDA, PAGINA_PRODUCTO, AMAZON_BUSINESS = (
    "superior", "resto de la búsqueda", "página del producto", "Amazon Business")

# tipos de elemento (lo que tiene puja propia dentro de un grupo de anuncios)
KEYWORD, PRODUCTO, CATEGORIA, AUTO = "keyword", "producto", "categoria", "auto"


@dataclass
class Metricas:
    clics: float = 0.0
    coste: float = 0.0
    compras: float = 0.0
    ventas: float = 0.0
    impresiones: float = 0.0

    def __add__(self, o):
        return Metricas(self.clics + o.clics, self.coste + o.coste, self.compras + o.compras,
                        self.ventas + o.ventas, self.impresiones + o.impresiones)

    def __sub__(self, o):
        return Metricas(self.clics - o.clics, self.coste - o.coste, self.compras - o.compras,
                        self.ventas - o.ventas, self.impresiones - o.impresiones)

    @property
    def acos(self) -> Optional[float]:
        if self.ventas > 0:
            return self.coste / self.ventas
        return None if self.coste <= 0 else float("inf")


@dataclass
class Campana:
    id: str
    nombre: str
    estado: str
    presupuesto: float
    segmentacion: str = "MANUAL"        # MANUAL / AUTO
    id_cartera: Optional[str] = None
    estado_servicio: str = ""           # extendedData.servingStatus (informativo)
    estrategia_pujas: str = ESTRATEGIA_DESCONOCIDA
    ajustes_emplazamiento: dict = field(default_factory=dict)   # emplazamiento -> % (20.0 = +20 %)
    fecha_fin: Optional[date] = None
    estrategia_objetivo: str = ""       # la que elige el agente en esta ronda (pujas.decidir_estrategias)
    motivo_estrategia: str = ""


@dataclass
class Grupo:
    id: str
    id_campana: str
    nombre: str
    estado: str
    puja_defecto: Optional[float] = None


@dataclass
class Anuncio:
    id: str
    id_campana: str
    id_grupo: str
    asin: str
    sku: str
    estado: str
    estado_servicio: str = ""


@dataclass
class Elemento:
    """Keyword, ASIN, categoría o segmentación automática: lo que tiene puja propia."""
    clave: str                          # ID de Amazon (keywordId / targetId)
    tipo: str                           # KEYWORD / PRODUCTO / CATEGORIA / AUTO
    id_campana: str
    id_grupo: str
    texto: str                          # la keyword, el ASIN o la expresión
    coincidencia: str                   # Amplia/Frase/Exacta, "ASIN", "Categoría", "Automática"
    estado: str
    puja: Optional[float]
    metricas: Metricas = field(default_factory=Metricas)  # acumulado que trae la fuente (informativo)


@dataclass
class Cuenta:
    """Foto completa de la cuenta en el momento de leerla."""
    fecha: date
    campanas: dict = field(default_factory=dict)    # id -> Campana
    grupos: dict = field(default_factory=dict)      # id -> Grupo
    elementos: dict = field(default_factory=dict)   # clave -> Elemento
    anuncios: list = field(default_factory=list)    # [Anuncio]
    avisos_cuenta: list = field(default_factory=list)  # problemas de cuenta detectados por la fuente

    # --- consultas útiles para el motor
    def productos_de_grupo(self, id_grupo):
        return sorted({a.asin for a in self.anuncios if a.id_grupo == id_grupo and a.estado != ARCHIVADO})

    def producto_de_grupo(self, id_grupo):
        """Un grupo normalmente promociona un único producto (CLAUDE.md). Si hay varios,
        el aprendizaje se indexa por el primero (orden estable)."""
        p = self.productos_de_grupo(id_grupo)
        return p[0] if p else None

    def producto_de_campana(self, id_campana):
        p = sorted({a.asin for a in self.anuncios if a.id_campana == id_campana and a.estado != ARCHIVADO})
        return p[0] if p else None

    def sku_de_producto(self, asin):
        return next((a.sku for a in self.anuncios if a.asin == asin and a.sku), None)

    def elementos_de_grupo(self, id_grupo):
        return [e for e in self.elementos.values() if e.id_grupo == id_grupo]

    def campana_activa(self, id_campana):
        c = self.campanas.get(id_campana)
        return c is not None and c.estado == ACTIVO

    def grupo_activo(self, id_grupo):
        g = self.grupos.get(id_grupo)
        return g is not None and g.estado == ACTIVO and self.campana_activa(g.id_campana)


# tipos de cambio (columna "Tipo" de la hoja Tickets)
PUJA, PAUSAR, NUEVA_KEYWORD, NUEVO_ASIN, PRESUPUESTO, CREAR_CAMPANA, ESTRATEGIA = (
    "puja", "pausar", "añadir_keyword", "añadir_asin", "presupuesto", "crear_campaña", "estrategia")


@dataclass
class Cambio:
    tipo: str
    clave: str                          # elemento (o "camp:<id>" para campañas)
    producto: Optional[str]
    id_campana: Optional[str]
    id_grupo: Optional[str]
    campana: str
    texto: str
    coincidencia: str
    antes: object
    despues: object
    motivo: str
    base: Metricas = field(default_factory=Metricas)
    estado: str = "propuesto"           # propuesto / confirmado / fallido / simulado / enviado_bulk
    detalle: str = ""
    requiere_revision: bool = False
    extra: dict = field(default_factory=dict)   # datos propios del tipo (p. ej. campaña nueva)
