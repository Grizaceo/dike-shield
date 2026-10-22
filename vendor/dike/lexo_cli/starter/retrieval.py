"""Recuperación de normas sobre el Starter Corpus.

Hasta la auditoría 2026-08-16 Diké no tenía recuperación sobre el corpus
canónico: `StarterCorpusResolver` solo sabe resolver un GID que alguien ya
conoce. El benchmark tapaba el hueco entregándole a `prepare_case` una lista
`TASK_SOURCES` escrita a mano, de modo que medía «dadas las normas correctas,
¿redacta y cita bien?» y nunca «¿encuentra las normas?».

Este módulo cierra ese hueco con cuatro canales **deterministas y sin modelo**.
Que no intervenga un LLM no es una limitación: es el requisito. El harness debe
comportarse igual con cualquier modelo, y una recuperación que dependiera del
modelo bajo prueba contaminaría la comparación entre brazos.

Cada resultado declara **por qué** fue recuperado (`channel` + `evidence`), de
modo que la traza es auditable artículo por artículo.

Canales, en orden de precisión decreciente:

1. `cita_explicita` — el documento nombra el artículo. Comparte la tokenización
   con `citation_check`, así que lo que el documento cita es exactamente lo que
   el gate sabrá reconocer después.
2. `lexico` — BM25 por cláusula. Consultar el documento entero diluye la señal:
   un contrato de compraventa es siete problemas jurídicos distintos, y cada
   cláusula («Arras», «Saneamiento», «Mora») es su propia consulta.
3. `referencia` — los artículos recuperados citan otros artículos; en un código
   esas remisiones son parte de la norma aplicable.
4. `contiguidad` — en un código la materia es contigua: si el art. 1857 puntúa
   alto, el 1858 y el 1859 tratan lo mismo.

Límite conocido y medido: lo léxico no cruza el salto concepto→norma. Un
contrato que dice «Arras» no comparte vocabulario con el art. 1535, que habla
de «cláusula penal». La contigüidad lo mitiga; no lo resuelve.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import math
import re
from pathlib import Path
from threading import Lock
import unicodedata

from lexo_cli.citation_check import article_token, cited_article_numbers
from lexo_cli.starter.morfologia import familia

# Solo palabras funcionales: determinantes, pronombres, preposiciones y verbos
# auxiliares. La lista NO incluye ya el vocabulario de oficio («ley», «código»,
# «artículo», «caso»): quitarlo era un error medible. BM25 tiene su propio
# mecanismo para descontar lo que aparece en todas partes —el IDF, que lo hace
# de forma graduada y dependiente del corpus—, mientras que la lista negra es
# absoluta y destruye la consulta. «El contrato es una ley para las partes»
# perdía justo la palabra que la distingue, y el art. 1545 no aparecía.
_VACIAS = frozenset("""
del las los una unos unas por para con sus que como mas pero sobre entre cuando
donde este esta estos estas ese esa eso aquel cual cuales quien quienes sea sean
ser sera seran son era eran han haya hubiere fuere segun ademas asi aun cada
desde hasta sino solo tambien toda todo todos todas otra otro otras otros
respectivo respectiva dicho dicha misma mismo tal tales
podra podran debera deberan puede pueden tiene tienen hubiese sido
""".split())

_TERMINO = re.compile(r"[a-zñ]{3,}")
# "artículos 1857, 1858 y 1859" -> tres remisiones, no una.
#
# El ancho del numeral es `\d+`, no un tope de dígitos. Medido sobre el
# snapshot 3e2e6f13…: los GID numéricos del pack son de 4 dígitos, así que un
# tope parecería inofensivo — pero un tope NO es una medición, es un
# supositorio que deja fuera lo que exceda. Con `\d{1,4}` un numeral de 5 o
# 6 dígitos no matchea y la remisión entera desaparece del índice; en
# `_GID_NUMERO` el ancla `$` hacía lo mismo. Ampliar a `\d+` solo hace entrar
# lo que hoy queda fuera: no cambia el trato de ningún artículo que ya
# indexa.
_REMISION = re.compile(
    r"\bart[íi]culos?\s+((?:\d+)(?:\s*(?:,|;|\by\b|\be\b)\s*\d+)*)", re.IGNORECASE
)
_GID_NUMERO = re.compile(r":art:0*(\d+)$")
# Cuánto pesa una coincidencia por variante morfológica frente a una exacta.
# El art. 1489 dice «resolutoria» y «cumplirse» donde el abogado escribe
# «resolución» e «incumplimiento»: sin esto no aparecía ni en el top 8. Que
# pese menos que la coincidencia literal es deliberado — la variante es una
# inferencia sobre la lengua, no una coincidencia observada.
_PESO_VARIANTE = 0.45

# Cuánto pesa cubrir la consulta completa frente a coincidir muy fuerte en una
# sola palabra. BM25 puro es aditivo y con 8.533 artículos cortos gana siempre
# el que repite el término más raro: para «despido por necesidades de la
# empresa» los ocho primeros resultados coincidían solo en «despido» y el art.
# 161 CT —que es literalmente esa causal— no aparecía. El factor de
# coordinación multiplica el puntaje por la fracción de conceptos de la
# consulta que el artículo efectivamente toca.
_PISO_COBERTURA = 0.20

# Un término de arte jurídico es una frase, no dos palabras sueltas:
# «necesidades de la empresa», «cláusula penal», «intención de los
# contratantes», «lesión enorme». Que el artículo las tenga contiguas es
# evidencia mucho más fuerte que tenerlas dispersas. Los pares se comparan
# normalizados por familia y sin orden: el Código escribe «las obligaciones se
# extinguen» donde el abogado escribe «extinguir las obligaciones».
_BONO_FRASE = 0.4

# Sobre el valor de las tres constantes anteriores: un barrido sobre el goldset
# (`tests/fixtures/goldset_recuperacion.json`) da una superficie plana — entre
# `_BONO_FRASE` 0,4 y 1,5 las métricas se mueven lo que mueve UNA consulta de
# 22. Están puestas en una región razonable, no ajustadas finamente, y los
# pisos del test están por debajo de lo medido justamente por eso. Afinarlas de
# verdad exige un goldset mayor; hacerlo con 22 consultas sería ajustar al
# ruido y llamarlo mejora.

# Cuánto del puntaje de la semilla hereda lo que se alcanza por expansión.
_HERENCIA_REFERENCIA = 0.7
_HERENCIA_CONTIGUIDAD = 0.5

# Peso mínimo del IDF para considerar una familia como activa en la consulta.
_IDF_PISO_FAMILIA = 2.0

# Máximo boost que el canal gráfico puede aplicar sobre un candidato BM25.
_BOOST_GRAFICO_MAX = 3.0

# Fracción de familias de la consulta que un GID debe cubrir para boost completo.
_COBERTURA_FAMILIA_PARA_BOOST_COMPLETO = 0.4


def _sin_acentos(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def terminos(texto: str) -> list[str]:
    """Términos indexables de un texto: minúsculas, sin acentos, sin vacías."""
    return [t for t in _TERMINO.findall(_sin_acentos(texto or "")) if t not in _VACIAS]


def _pares_contiguos(secuencia: list[str]) -> frozenset[tuple[str, str]]:
    """Pares de términos contiguos, por familia y sin orden."""
    pares = set()
    for primero, segundo in zip(secuencia, secuencia[1:]):
        a, b = familia(primero), familia(segundo)
        if a != b:
            pares.add((a, b) if a < b else (b, a))
    return frozenset(pares)


def clausulas(documento: str) -> list[str]:
    """Parte el documento en unidades con carga jurídica propia.

    Los encabezados markdown abren cláusula y viajan con su cuerpo: el título
    («QUINTO: Saneamiento») suele ser el término jurídico más discriminante del
    bloque, y separado de su texto no recupera nada.
    """
    partes: list[str] = []
    actual: list[str] = []
    for linea in (documento or "").splitlines():
        limpia = linea.strip()
        if limpia.startswith("#"):
            if actual:
                partes.append("\n".join(actual))
            actual = [limpia.lstrip("# ").strip()]
        elif limpia:
            actual.append(limpia)
    if actual:
        partes.append("\n".join(actual))
    utiles = [p for p in partes if len(p) > 15]
    return utiles or ([documento] if documento else [])


@dataclass(frozen=True)
class Hit:
    """Una norma recuperada, con la razón por la que se recuperó."""

    gid: str
    score: float
    channel: str
    evidence: str = ""


@dataclass
class RetrievalResult:
    hits: list[Hit] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def gids(self) -> list[str]:
        return [hit.gid for hit in self.hits]

    def to_dict(self) -> dict:
        return {
            "gids": self.gids,
            "hits": [
                {"gid": h.gid, "score": round(h.score, 4),
                 "channel": h.channel, "evidence": h.evidence}
                for h in self.hits
            ],
            "channels": dict(Counter(h.channel for h in self.hits)),
            "warnings": list(self.warnings),
        }


class StarterCorpusRetriever:
    """Índice BM25 sobre los artículos que el resolver ya cargó y verificó.

    Se construye sobre un `StarterCorpusResolver` en vez de releer el paquete:
    así solo se indexa material que pasó las verificaciones de hash, vigencia y
    completitud. Lo que no es resoluble no es recuperable.
    """

    def __init__(self, resolver, *, k1: float = 1.5, b: float = 0.75) -> None:
        self.resolver = resolver
        self.k1 = k1
        self.b = b
        self._indexado = False
        self._tf: dict[str, Counter] = {}
        self._largo: dict[str, int] = {}
        self._postings: dict[str, list[str]] = {}
        self._idf: dict[str, float] = {}
        self._largo_medio = 0.0
        self._alias: dict[str, str] = {}
        self._por_token: dict[tuple[str, str], str] = {}
        self._numero: dict[str, int] = {}
        self._por_familia: dict[str, list[str]] = {}
        self._pares: dict[str, frozenset[tuple[str, str]]] = {}
        # Grafico: familia → GIDs que tienen al menos un término de esa familia.
        # Se construye durante indexación y permite rerankear candidatos BM25 usando
        # centralidad familiar — los GIDs que cubren familias compartidas con la
        # consulta se boostan proporcionalmente a cuántas familias comparten.
        self._por_familia_gid: dict[str, list[str]] = {}
        # 2.0: caché a disco del índice BM25, clave = snapshot_hash del corpus.
        # El snapshot es inmutable (su ruta ES su hash), así que el índice
        # construido sobre él también lo es: reconstruirlo por proceso era el
        # cuello de botella (30 s de CPU de los 44,4 s de `dike buscar --capa ley`).
        self._cache_path: Path | None = None

    # -- caché a disco (2.0) ------------------------------------------------

    def _cache_key(self) -> str | None:
        """Hash del snapshot canónico: la clave del índice persistido."""
        try:
            binding = self.resolver.binding()
            corpora = binding.get("corpora", [])
            if corpora:
                return corpora[0].get("snapshot_hash", "")
        except Exception:
            pass
        return None

    def _cache_file(self) -> Path | None:
        key = self._cache_key()
        if not key:
            return None
        cache_dir = Path.home() / ".dike" / "bm25_cache"
        return cache_dir / f"{key[:16]}.pkl"

    def _cargar_desde_disco(self) -> bool:
        """Carga el índice persistido si existe para este snapshot. 2.0."""
        path = self._cache_file()
        if path is None or not path.exists():
            return False
        try:
            import pickle

            with path.open("rb") as f:
                data = pickle.load(f)
            self._tf = data["tf"]
            self._largo = data["largo"]
            self._postings = data["postings"]
            self._idf = data["idf"]
            self._largo_medio = data["largo_medio"]
            self._alias = data["alias"]
            self._por_token = data["por_token"]
            self._numero = data["numero"]
            self._por_familia = data["por_familia"]
            self._pares = data["pares"]
            self._por_familia_gid = data["por_familia_gid"]
            self._indexado = True
            return True
        except Exception:
            # Índice corrupto: se reconstruye desde la fuente (nunca es el
            # único artefacto del dato — regla §13).
            self._indexado = False
            return False

    def _persistir_a_disco(self) -> None:
        """Persiste el índice recién construido. 2.0."""
        path = self._cache_file()
        if path is None:
            return
        try:
            import pickle

            path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "tf": self._tf,
                "largo": self._largo,
                "postings": self._postings,
                "idf": self._idf,
                "largo_medio": self._largo_medio,
                "alias": self._alias,
                "por_token": self._por_token,
                "numero": self._numero,
                "por_familia": self._por_familia,
                "pares": self._pares,
                "por_familia_gid": self._por_familia_gid,
            }
            with path.open("wb") as f:
                pickle.dump(data, f, protocol=4)
        except Exception:
            # Persistir es optimización, no contrato: si falla, el índice en
            # memoria sigue sirviendo esta invocación.
            pass

    # -- construcción ------------------------------------------------------

    def _indexar(self) -> None:
        if self._indexado:
            return
        # 2.0: intentar cargar el índice persistido antes de reconstruir.
        if self._cargar_desde_disco():
            return
        evidencias = getattr(self.resolver, "_by_gid", {})
        postings: dict[str, set[str]] = {}
        for gid, evidencia in evidencias.items():
            alias = gid.split(":art:", 1)[0].removeprefix("cl.norma.")
            self._alias[gid] = alias
            self._por_token[(alias, article_token(gid))] = gid
            numero = _GID_NUMERO.search(gid)
            if numero:
                self._numero[gid] = int(numero.group(1))
            secuencia = terminos(getattr(evidencia, "text", ""))
            self._pares[gid] = _pares_contiguos(secuencia)
            cuenta = Counter(secuencia)
            self._tf[gid] = cuenta
            self._largo[gid] = sum(cuenta.values())
            for termino in cuenta:
                postings.setdefault(termino, set()).add(gid)
        total = len(self._tf) or 1
        self._largo_medio = sum(self._largo.values()) / total
        self._postings = {t: sorted(g) for t, g in postings.items()}
        self._idf = {
            t: math.log(1 + (total - len(g) + 0.5) / (len(g) + 0.5))
            for t, g in self._postings.items()
        }
        familias: dict[str, list[str]] = {}
        for termino in self._postings:
            familias.setdefault(familia(termino), []).append(termino)
        self._por_familia = {f: sorted(t) for f, t in familias.items()}

        # _por_familia_gid: familia → GIDs ordenados por cuántos términos únicos
        # de esa familia cubren (proxy de centralidad en la familia). Un GID que
        # tiene más términos de una familia institucional es más representativo.
        gid_familias: dict[str, dict[str, int]] = {}
        for gid, tf in self._tf.items():
            gid_fam: dict[str, int] = {}
            for termino in tf:
                fam = familia(termino)
                gid_fam.setdefault(fam, 0)
                gid_fam[fam] += 1
            gid_familias[gid] = gid_fam
        # familia → [(gid, cobertura), ...] ordenada por cobertura descendente
        familia_to_gids: dict[str, list[tuple[str, int]]] = {}
        for gid, fam_cov in gid_familias.items():
            for fam, cov in fam_cov.items():
                familia_to_gids.setdefault(fam, []).append((gid, cov))
        self._por_familia_gid = {
            fam: [gid for gid, _ in sorted(gids, key=lambda p: -p[1])]
            for fam, gids in familia_to_gids.items()
        }
        self._indexado = True
        # 2.0: persistir el índice recién construido para las próximas invocaciones.
        self._persistir_a_disco()

    # -- consulta ----------------------------------------------------------

    def term_weight(self, termino: str) -> float:
        """Cuán discriminante es un término en este corpus (su IDF).

        Sirve fuera de la búsqueda: para decidir si dos textos comparten algo
        significativo, «finiquito» pesa mucho más que «laboral», que aparece en
        media parte del Código del Trabajo. Un término desconocido para el
        corpus pesa 0: no puede sostener una relación con una norma.
        """
        self._indexar()
        return self._idf.get(_sin_acentos(termino.lower()), 0.0)

    def expandir(self, query: str) -> dict[str, tuple[float, str]]:
        """Términos del corpus que la consulta activa, con su peso y su origen.

        Devuelve `{termino_del_corpus: (peso, termino_de_la_consulta)}`. Un
        término que coincide literalmente pesa lo que se repita en la
        consulta; uno que solo comparte familia morfológica pesa
        `_PESO_VARIANTE` de eso. Se expone aparte de `search` porque es la
        explicación de por qué apareció un artículo, y esa explicación tiene
        que poder mostrarse al abogado.
        """
        self._indexar()
        consulta = Counter(terminos(query))
        pesos: dict[str, tuple[float, str]] = {}
        for termino, veces in consulta.items():
            if termino in self._idf:
                pesos[termino] = (float(veces), termino)
        for termino, veces in consulta.items():
            for variante in self._por_familia.get(familia(termino), ()):  # noqa: B007
                if variante in pesos:
                    continue
                pesos[variante] = (veces * _PESO_VARIANTE, termino)
        return pesos

    def search(self, query: str, *, alias: str | None = None, limit: int = 10) -> list[Hit]:
        """Artículos mejor puntuados por BM25 para la consulta."""
        self._indexar()
        pesos = self.expandir(query)
        # Se agrupa por término de la consulta y dentro del grupo se toma el
        # MÁXIMO, no la suma: la familia nombra un solo concepto. Sumar hacía
        # que un artículo que menciona «pacto», «convención» y «estipulado»
        # acumulara tres veces el crédito de haber hablado de un contrato.
        # La agrupación es por FAMILIA del término de la consulta, no por el
        # término: si el abogado escribe «contrato» y «partes», está nombrando
        # un solo concepto, y el art. 1545 —que dice «contrato» y
        # «contratantes»— tiene que contar como cobertura completa.
        por_origen: dict[str, list[tuple[str, float]]] = {}
        etiqueta: dict[str, str] = {}
        for termino, (peso, origen) in pesos.items():
            clave = familia(origen)
            por_origen.setdefault(clave, []).append((termino, peso))
            etiqueta.setdefault(clave, origen)
        puntajes: Counter = Counter()
        cubiertos: dict[str, int] = {}
        mejor: dict[str, tuple[float, str, str]] = {}
        for clave, variantes in por_origen.items():
            origen = etiqueta[clave]
            aportes: dict[str, tuple[float, str]] = {}
            for termino, peso in variantes:
                idf = self._idf.get(termino)
                if idf is None:
                    continue
                for gid in self._postings[termino]:
                    if alias and self._alias.get(gid) != alias:
                        continue
                    frecuencia = self._tf[gid][termino]
                    largo = self._largo[gid]
                    denominador = frecuencia + self.k1 * (
                        1 - self.b + self.b * largo / (self._largo_medio or 1)
                    )
                    aporte = idf * (frecuencia * (self.k1 + 1)) / denominador * peso
                    previo = aportes.get(gid)
                    if previo is None or aporte > previo[0]:
                        aportes[gid] = (aporte, termino)
            for gid, (aporte, termino) in aportes.items():
                puntajes[gid] += aporte
                cubiertos[gid] = cubiertos.get(gid, 0) + 1
                anterior = mejor.get(gid)
                if anterior is None or aporte > anterior[0]:
                    mejor[gid] = (aporte, termino, origen)
        conceptos = len(por_origen) or 1
        pares_consulta = _pares_contiguos(terminos(query))
        for gid, puntaje in list(puntajes.items()):
            cobertura = cubiertos.get(gid, 0) / conceptos
            factor = _PISO_COBERTURA + (1 - _PISO_COBERTURA) * cobertura
            if pares_consulta:
                compartidos = len(pares_consulta & self._pares.get(gid, frozenset()))
                factor *= 1 + _BONO_FRASE * compartidos / len(pares_consulta)
            puntajes[gid] = puntaje * factor
        # Desempate por GID: dos artículos con el mismo puntaje deben salir
        # siempre en el mismo orden o la traza deja de ser reproducible.
        ordenados = sorted(puntajes.items(), key=lambda par: (-par[1], par[0]))

        # Canal gráfico: rerankear candidatos BM25 usando cobertura de familias de la
        # consulta. El boost es proporcional a cuántas familias de la consulta cubre
        # cada GID; se ancla al espacio BM25 antes de mezclarlos.
        hits_bm25 = [
            Hit(gid=gid, score=puntaje, channel="lexico", evidence="BM25")
            for gid, puntaje in ordenados
        ]
        hits_con_grafico = self._canal_grafico(
            consulta=query, candidatos=hits_bm25, alias=alias
        )
        if hits_con_grafico:
            max_bm = max((h.score for h in hits_bm25), default=1.0)
            boost_max = max((h.score for h in hits_con_grafico), default=1.0)
            escala = max_bm / boost_max if boost_max > 0 else 1.0
            gid_boost: dict[str, float] = {
                h.gid: h.score * escala for h in hits_con_grafico
            }
            mejor: dict[str, Hit] = {}
            for hit in hits_bm25:
                boost = gid_boost.get(hit.gid, 1.0)
                canal = "grafico" if boost > 1.0 else "lexico"
                nuevo = Hit(
                    gid=hit.gid,
                    score=hit.score * boost,
                    channel=canal,
                    evidence=hit.evidence,
                )
                prev = mejor.get(hit.gid)
                if prev is None or nuevo.score > prev.score:
                    mejor[hit.gid] = nuevo
            for h in hits_con_grafico:
                if h.gid not in mejor:
                    escala = gid_boost.get(h.gid, 1.0)
                    mejor[h.gid] = Hit(
                        gid=h.gid,
                        score=h.score * escala * max_bm,  # anchor to BM25 space
                        channel="grafico",
                        evidence=h.evidence,
                    )
            # Ordenar solo por score descendente, sin prioridad de canal.
            # El canal se registra para trazabilidad, no como criterio de orden.
            hits_ordenados = sorted(
                mejor.values(), key=lambda h: -h.score
            )
        else:
            hits_ordenados = hits_bm25

        return hits_ordenados[:limit]

    # -- canales -----------------------------------------------------------

    def _canal_citas(self, documento: str, alias: str | None) -> list[Hit]:
        hits: list[Hit] = []
        for token in cited_article_numbers(documento):
            for candidato_alias in ([alias] if alias else sorted(set(self._alias.values()))):
                gid = self._por_token.get((candidato_alias, token))
                if gid:
                    hits.append(Hit(gid=gid, score=float("inf"), channel="cita_explicita",
                                    evidence=f"el documento cita el art. {token}"))
                    break
        return hits

    def _canal_lexico(self, partes: list[str], alias: str | None, por_clausula: int) -> list[Hit]:
        hits: list[Hit] = []
        vistos: dict[str, Hit] = {}
        for parte in partes:
            etiqueta = parte.splitlines()[0][:60]
            for posicion, hit in enumerate(self.search(parte, alias=alias, limit=por_clausula)):
                previo = vistos.get(hit.gid)
                if previo is not None and previo.score >= hit.score:
                    continue
                nuevo = Hit(gid=hit.gid, score=hit.score, channel="lexico",
                            evidence=f"cláusula «{etiqueta}» (#{posicion + 1})")
                vistos[hit.gid] = nuevo
        hits.extend(vistos.values())
        return hits

    def _canal_referencias(self, semillas: dict[str, float], alias: str | None) -> list[Hit]:
        self._indexar()
        evidencias = getattr(self.resolver, "_by_gid", {})
        hits: list[Hit] = []
        for gid, puntaje in semillas.items():
            texto = getattr(evidencias.get(gid), "text", "")
            propio = self._alias.get(gid)
            for coincidencia in _REMISION.finditer(texto or ""):
                for numero in re.findall(r"\d+", coincidencia.group(1)):
                    destino = self._por_token.get((propio, str(int(numero))))
                    if destino and destino != gid and (not alias or self._alias.get(destino) == alias):
                        # Hereda parte del puntaje de su semilla: así un artículo
                        # al que remite una coincidencia fuerte compite con las
                        # coincidencias léxicas en vez de caer al final y ser lo
                        # primero que se pierde al acotar el conjunto.
                        hits.append(Hit(gid=destino, score=puntaje * _HERENCIA_REFERENCIA,
                                        channel="referencia", evidence=f"remisión desde {gid}"))
        return hits

    def _canal_contiguidad(self, semillas: dict[str, float], alias: str | None, radio: int) -> list[Hit]:
        self._indexar()
        hits: list[Hit] = []
        for gid, puntaje in semillas.items():
            base = self._numero.get(gid)
            propio = self._alias.get(gid)
            if base is None:
                continue
            for delta in range(-radio, radio + 1):
                if delta == 0:
                    continue
                vecino = self._por_token.get((propio, str(base + delta)))
                if vecino and (not alias or self._alias.get(vecino) == alias):
                    # Decae con la distancia: el artículo de al lado trata la
                    # misma materia mucho más a menudo que el de tres más allá.
                    heredado = puntaje * _HERENCIA_CONTIGUIDAD / abs(delta)
                    hits.append(Hit(gid=vecino, score=heredado, channel="contiguidad",
                                    evidence=f"contiguo a {gid} ({delta:+d})"))
        return hits

    def _canal_grafico(
        self,
        consulta: str,
        candidatos: list[Hit],
        *,
        alias: str | None = None,
    ) -> list[Hit]:
        """Booster familiar: artículos que cubren familias de la consulta pero BM25 no rankeó bien.

        El canal léxico打分 por coincidencia de término. Un artículo que habla de
        muchas familias de la consulta (y por tanto cubre la institución completa)
        puede quedar relegado si sus términos específicos no coinciden exactamente
        con los de la consulta. Este canal lo rescata:

        1. Extrae las familias que la consulta activa (IDF-weighted).
        2. Para cada candidato actual, calcula cobertura familiar =fracción de
           familias de la consulta que el GID cubre.
        3. Los GIDs que cubren familias de la consulta pero NO están en los
           candidatos actuales se añaden como hits grafico con boost.

        El boost no domina la señal léxica: se limita a _BOOST_GRAFICO_MAX×
        y solo se aplica cuando la cobertura familiar supera el umbral.

        Args:
            consulta: texto de la consulta original.
            candidatos: hits actuales del retriever (lexico + referencia + contiguidad).
            alias: filtro de corpus opcional.

        Returns:
            Lista de hits adicionales del canal grafico.
        """
        self._indexar()

        # Familias de la consulta con peso IDF
        consulta_terms = terminos(consulta)
        familias_consulta: dict[str, float] = {}
        for termino in consulta_terms:
            idf = self._idf.get(termino, 0.0)
            if idf < _IDF_PISO_FAMILIA:
                continue
            fam = familia(termino)
            familias_consulta[fam] = max(familias_consulta.get(fam, 0.0), idf)

        if not familias_consulta:
            return []

        gid_candidatos = {h.gid for h in candidatos if h.channel != "grafico"}

        # GIDs que cubren familias de la consulta pero no están en candidatos
        nuevos: list[tuple[float, str, str]] = []  # (boost, gid, evidencia)
        for fam in familias_consulta:
            for gid in self._por_familia_gid.get(fam, ()):
                if gid in gid_candidatos:
                    continue
                if alias and self._alias.get(gid) != alias:
                    continue
                # Cuántas familias de la consulta cubre este GID
                gid_fams = getattr(self.resolver, "_by_gid", {}).get(gid)
                if not gid_fams:
                    continue
                gid_terms = set(terminos(getattr(gid_fams, "text", "")))
                cobertura = sum(
                    1 for f in familias_consulta if any(familia(t) == f for t in gid_terms)
                ) / len(familias_consulta)

                if cobertura < 0.15:
                    continue  # demasiado marginal para rescatarlo

                # El boost máximo se aplica cuando la cobertura familiar es alta;
                # cobertura parcial recibe boost proporcional.
                factor = min(cobertura / _COBERTURA_FAMILIA_PARA_BOOST_COMPLETO, 1.0)
                boost = 1.0 + _BOOST_GRAFICO_MAX * factor

                evidencia = (
                    f"cubriendo {cobertura:.0%} de las familias de la consulta "
                    f"(«{fam[:30]}…»)"
                )
                nuevos.append((boost, gid, evidencia))

        # Devolver como hits, ordenados por boost descendente.
        # El score del hit gráfico es el boost; el score final se combina después.
        hits_grafico = [
            Hit(gid=gid, score=boost, channel="grafico", evidence=evidencia)
            for boost, gid, evidencia in sorted(nuevos, key=lambda x: -x[0])
        ]
        return hits_grafico

    # -- orquestación ------------------------------------------------------

    def retrieve_for_document(
        self,
        document_text: str,
        *,
        alias: str | None = None,
        legal_question: str = "",
        por_clausula: int = 8,
        semillas_expansion: int = 8,
        radio_contiguidad: int = 2,
        limit: int | None = None,
    ) -> RetrievalResult:
        """Normas candidatas para un documento, con la traza de cada canal.

        `limit` acota el conjunto final. No es solo una cuestión de tamaño de
        prompt: el gate de citación considera respaldado todo lo que esté en la
        evidencia resuelta, así que **un conjunto más grande es un gate más
        débil**. Recuperar de más tiene un costo de integridad, no solo de
        tokens.
        """
        self._indexar()
        if not (document_text or "").strip():
            return RetrievalResult(warnings=["documento vacío: nada que recuperar"])

        partes = clausulas(document_text)
        if legal_question.strip():
            partes = [legal_question.strip(), *partes]

        hits = self._canal_citas(document_text, alias)
        hits += self._canal_lexico(partes, alias, por_clausula)

        # La expansión parte solo de las semillas más fuertes: expandir desde
        # una coincidencia débil propaga ruido en vez de materia.
        base = max((h.score for h in hits if h.score != float("inf")), default=1.0) or 1.0
        fuertes = {
            h.gid: (base if h.score == float("inf") else h.score)
            for h in sorted(hits, key=lambda h: -h.score)[:semillas_expansion]
        }
        hits += self._canal_referencias(fuertes, alias)
        hits += self._canal_contiguidad(fuertes, alias, radio_contiguidad)

        # Canal gráfico: rerankear candidatos existentes + añadir nuevos por cobertura
        # familiar. Se aplica solo sobre search() que tiene corpus curado; no sobre
        # retrieve_for_document que puede recibir documentos arbitrarios sin corpus.
        gid_boost: dict[str, float] = {}
        hits_grafico = self._canal_grafico(
            consulta=document_text, candidatos=hits, alias=alias
        )
        if hits_grafico:
            max_bm25 = max(
                (h.score for h in hits if h.score != float("inf")), default=1.0
            )
            boost_max = max((h.score for h in hits_grafico), default=1.0)
            escala = max_bm25 / boost_max if boost_max > 0 else 1.0
            for h in hits_grafico:
                gid_boost[h.gid] = h.score * escala

        # Un GID recuperado por varios canales se queda con el más preciso.
        prioridad = {
            "cita_explicita": 0,
            "lexico": 1,
            "referencia": 2,
            "contiguidad": 3,
            "grafico": 4,
        }
        mejor: dict[str, Hit] = {}
        for hit in hits:
            boost = gid_boost.get(hit.gid, 1.0)
            canal_real = "grafico" if boost > 1.0 else hit.channel
            score_ajustado = hit.score * boost if hit.channel != "grafico" else hit.score
            nuevo = Hit(
                gid=hit.gid,
                score=score_ajustado,
                channel=canal_real,
                evidence=hit.evidence,
            )
            previo = mejor.get(hit.gid)
            if (
                previo is None
                or (prioridad[nuevo.channel], -nuevo.score)
                < (prioridad[previo.channel], -previo.score)
            ):
                mejor[hit.gid] = nuevo
        if hits_grafico:
            for h in hits_grafico:
                if h.gid not in mejor:
                    escala = gid_boost.get(h.gid, 1.0)
                    mejor[h.gid] = Hit(
                        gid=h.gid,
                        score=h.score * escala,
                        channel="grafico",
                        evidence=h.evidence,
                    )

        # Se ordena por puntaje, no por canal: al acotar el conjunto hay que
        # conservar lo más relacionado con el documento, venga del canal que
        # venga. La cita explícita va siempre primero porque el documento la
        # nombra: no es una estimación de relevancia sino un hecho del texto.
        ordenados = sorted(
            mejor.values(),
            key=lambda h: (0 if h.channel == "cita_explicita" else 1, -h.score, h.gid),
        )
        avisos: list[str] = []
        if limit is not None and len(ordenados) > limit:
            avisos.append(
                f"recuperación truncada a {limit} de {len(ordenados)} candidatos"
            )
            ordenados = ordenados[:limit]
        return RetrievalResult(hits=ordenados, warnings=avisos)


def retrieval_metrics(recuperados: list[str], esperados: list[str]) -> dict:
    """Contraste entre lo recuperado y un goldset, para medir el paso que antes
    no se medía. Sin goldset devuelve `supported=False` en vez de fingir un 1.0.
    """
    if not esperados:
        return {"supported": False}
    obtenidos, oro = set(recuperados), set(esperados)
    aciertos = obtenidos & oro
    return {
        "supported": True,
        "expected": len(oro),
        "retrieved": len(obtenidos),
        "hits": len(aciertos),
        "recall": round(len(aciertos) / len(oro), 4),
        "precision": round(len(aciertos) / len(obtenidos), 4) if obtenidos else 0.0,
        "missed": sorted(oro - obtenidos),
    }


# ── Retriever compartido ─────────────────────────────────────────────────────
# Indexar el corpus sellado (8.533 artículos, con sus pares contiguos) cuesta
# segundos. El índice depende solo del resolver, que a su vez es inmutable:
# reconstruirlo por consulta hacía que el buscador de normas de la web tardara
# entre 3 y 26 segundos en responder.
_RETRIEVER_CACHE: "dict[int, StarterCorpusRetriever]" = {}
_RETRIEVER_LOCK = Lock()


def shared_retriever(resolver) -> "StarterCorpusRetriever":
    """El retriever del proceso para este resolver, indexado una sola vez."""
    clave = id(resolver)
    with _RETRIEVER_LOCK:
        cached = _RETRIEVER_CACHE.get(clave)
        if cached is None or cached.resolver is not resolver:
            cached = StarterCorpusRetriever(resolver)
            _RETRIEVER_CACHE[clave] = cached
    return cached
