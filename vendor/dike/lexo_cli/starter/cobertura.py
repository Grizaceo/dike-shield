#!/usr/bin/env python3
"""Cobertura del corpus: que la búsqueda pueda decir «no tengo esto».

H8 (2026-09-30). El defecto medido: `humanize.relevancia` es una etiqueta
RELATIVA al mejor resultado de la misma lista, así que el primer artículo de
cualquier lista sale «relevancia alta en esta búsqueda». Ante un tema fuera del
corpus («impuesto a las criptomonedas») eso producía cinco artículos de
derecho tributario etiquetados «alta» y «media» — un escalar de precisión que
no significa nada absoluto.

Este módulo aporta la señal que faltaba, y la separa en dos porque son dos
fallos distintos:

1. **Cobertura léxica**: ¿están los términos de la consulta en el índice? Es lo
   que falla con «impuesto a las criptomonedas» (criptomoned no aparece en
   ningún artículo de los 8.544).
2. **Cobertura de cuerpo**: ¿está el cuerpo del que la consulta proviene? Es lo
   que falla con «homicidio», «prescripción de la acción» y «legítima defensa»:
   los términos SÍ existen (homicidio está en 6 artículos) pero son del Código
   Civil, y el Código Penal está instalado con 2 artículos de 674. Devolver el
   art. 969 del Código Civil como respuesta a una consulta de materia penal no
   es una respuesta: es otro cuerpo hablando.

Reglas duras:

- Abstenerse es una RESPUESTA (`SIN_COBERTURA` + mensaje legible), nunca una
  excepción. Un fallo-closed que lanza no le dice nada al abogado.
- La etiqueta de relevancia del artículo NO cambia. Lo que cambia es que ahora
  la lista viaja con su veredicto de cobertura, y la interfaz puede mostrarlo.
- El umbral no se calibra contra `normas_qrels_v1` (reservado para medir), sino
  contra las 7 consultas de humo declaradas abajo.
- `CORPUS_DECLARADO` son HECHOS del corpus declarados a mano y versionados, no
  una heurística de runtime. Si el pack cambia, el número se corrige acá.
"""

from __future__ import annotations

from typing import Any, Iterable

# Veredictos, en orden de fuerza. Tres, no dos: «cubierto» y «parcial» se
# comportan distinto en pantalla (una se puede citar; la otra, no), y colapsarlos
# volvería a mentir en un caso distinto al que arreglamos.
#
# `AMBIGUA` es el cuarto y llega en la quinta ronda de H8. NO es una Endrench de
# fuerza: se emite en un sitio distinto —cuando no hay materia declarada y hay
# más de un cuerpo candidato— y significa exactamente lo que dice: que no se
# sabe de qué materia trata la consulta. No es «cubierto» (afirmaría una
# cobertura de algo que el sistema no pudo determinar) ni «sin cobertura» (no
# falta nada que se pueda afirmar). Es la respuesta honesta a «¿esto es de qué
# materia?», y sin ella el sistema sabía que no sabía y lo callaba.
VEREDICTOS = ("CUBIERTO", "PARCIAL", "AMBIGUA", "SIN_COBERTURA")

# ── El corpus, declarado ──────────────────────────────────────────────────────
# Medición del 2026-09-30 sobre el pack `chile-base` instalado
# (snapshot 3e2e6f13…, 8.544 artículos, 25 alias). NO se investiga por qué el
# pack quedó así: es el corpus, no el código (decisión del usuario).
#
# `articulos_totales` es el tamaño real del cuerpo en Chile; sirve para que la
# interfaz pueda decir «2 de 674» en vez de un número suelto que no significaría
# nada. Los cuerpos sin total conocido lo dicen con `None`.
CORPUS_DECLARADO: dict[str, Any] = {
    "fecha": "2026-09-30",
    "pack": "chile-base",
    "snapshot": "3e2e6f13b86c3409",
    "articulos_en_pack": 8544,
    "cuerpos_catalogo": 41,
    "cuerpos_en_pack": 25,
    "cuerpos": {
        # alias -> {"articulos_en_pack": n, "articulos_totales": n|None}
        "cc": {"articulos_en_pack": 2419, "articulos_totales": None},
        "ccom": {"articulos_en_pack": 1223, "articulos_totales": None},
        "cpc": {"articulos_en_pack": 920, "articulos_totales": None},
        "cot": {"articulos_en_pack": 621, "articulos_totales": None},
        "cpp": {"articulos_en_pack": 550, "articulos_totales": None},
        "ct": {"articulos_en_pack": 545, "articulos_totales": None},
        "ley_20720": {"articulos_en_pack": 398, "articulos_totales": None},
        "dfl_1122": {"articulos_en_pack": 328, "articulos_totales": None},
        "ctrib": {"articulos_en_pack": 223, "articulos_totales": None},
        "dl_3500": {"articulos_en_pack": 187, "articulos_totales": None},
        "ley_19968": {"articulos_en_pack": 158, "articulos_totales": None},
        "ley_18046": {"articulos_en_pack": 155, "articulos_totales": None},
        "cpr": {"articulos_en_pack": 151, "articulos_totales": 160},
        "ley_19496": {"articulos_en_pack": 135, "articulos_totales": None},
        "ley_18092": {"articulos_en_pack": 112, "articulos_totales": None},
        "ley_16744": {"articulos_en_pack": 98, "articulos_totales": None},
        "ley_19728": {"articulos_en_pack": 82, "articulos_totales": None},
        "ley_20000": {"articulos_en_pack": 76, "articulos_totales": None},
        "ley_18216": {"articulos_en_pack": 51, "articulos_totales": None},
        "ley_17322": {"articulos_en_pack": 34, "articulos_totales": None},
        "ley_20066": {"articulos_en_pack": 33, "articulos_totales": None},
        "ley_19628": {"articulos_en_pack": 24, "articulos_totales": None},
        "ley_19828": {"articulos_en_pack": 14, "articulos_totales": None},
        "ley_21719": {"articulos_en_pack": 5, "articulos_totales": None},
        # El Código Penal: 2 artículos de 674. Es el caso que motivó H8.
        "cp": {"articulos_en_pack": 2, "articulos_totales": 674},
    },
}

# Un cuerpo con menos de este porcentaje de sus artículos NO se considera
# material de consulta: está instalado, no cubierto. 3 % del total.
UMBRAL_PROFUNDIDAD = 0.03

# ── Materia → cuerpo esperado ─────────────────────────────────────────────────
# Léxico curado, no un clasificador. Regla: si un abogado escribe «homicidio»,
# «legítima defensa» o «prescripción de la acción», el cuerpo del que espera
# respuesta es el penal, no el civil queCasualmente menciona la palabra.
#
# Se anota el término, NO la consulta. Una consulta es una frase; un término es
# una palabra que el abogado escribió. El léxico se puede auditar término a
# término, que es lo que un lexicon tiene que ser.
LEXICO_MATERIA: dict[str, str] = {
    # Penal sustantivo
    "homicidio": "cp", "homicida": "cp", "parricidio": "cp", "lesion": "cp",
    "hurto": "cp", "robo": "cp", "estafa": "cp", "cuasidelito": "cp", "mascara": "cp", "sindicato": "cp",
    "violacion": "cp", "abuso": "cp", "vejamen": "cp", "difamacion": "cp",
    "calumnia": "cp", "maltrato": "cp", "amenaza": "cp", "coaccion": "cp",
    "fraude": "cp", "delito": "cp", "delitos": "cp", "culpable": "cp",
    "condenacion": "cp", "reclusion": "cp", "remision": "cp",
    "detencion": "cp", "detenido": "cp",
    #[I] legítimo: el usuario escribe «defensa» y el Corpus Civil art.1200 tiene
    # «buena fe», pero la legítima defensa es CP art. 145. Es el caso del encargo.
    "legitima": "cp", "defensa": "cp",
    "imputabilidad": "cp", "menor": "cp", "inimputable": "cp",
    # ── Cuarta ronda de H8 (2026-10-01): términos de SANCIÓN penal ────────────
    # El defecto medido: «sentencia condenatoria pena privativa de libertad» dejó
    # de advertir el Código Penal tras 72f866fb. No porque «sentencia» dejara de
    # mapear al CP —sigue mapeando— sino porque al volverse COMPARTIDA la
    # consulta se quedó SIN NINGÚN término con peso propio, y sin términos con
    # peso propio no se afirma ningún cuerpo. Resultado: `cuerpos_esperados`
    # vacío, veredicto de CUERPO no emitido, y el abogado recibía artículos del
    # Código Civil a una pregunta sobre una condena.
    #
    # Lo que faltaba eran las palabras con las que un abogado NOMBRA la
    # sanción: el veredicto, la pena, la reclusión. «Sentencia» dice en qué
    # materia se juzga; «condenatoria» dice de qué materia se trata.
    #
    # Las claves son las FAMILIAS que devuelve `_fam`, que es como las consulta
    # el código (`_cuerpos_de_un_termino` prueba la forma y luego la familia).
    # Se midió el mapeo de cada una antes de escribirla:
    #   condena→conden · condenatoria→condenatori · absolución→absolucion
    #   absolutoria→absolutori ·-private/privativa→privativ · reclusión→reclusion
    #
    # «penal» y «pena» se declaran por su FORMA, no por la familia `fam:pena`:
    # esa familia cubre también «causa ilícita» (CC art. 1478) y «cláusula
    # penal» (CC art. 1476), que son materia civil. Es la razón —medida el
    # 2026-10-01 sobre las 31 reservadas— por la que `fam:pena` NO se declara
    # materia, y sigue sin declararse. Igual con `fam:delit`: cubre «delito»
    # (penal) y «ilícita» (civil), así que se usa la forma «delito».
    "condena": "cp", "conden": "cp", "condenatori": "cp", "absolutori": "cp",
    "absolucion": "cp", "privativ": "cp", "punitiv": "cp", "delituos": "cp",
    # «penal» y «pena» NO se declaran aquí, y la razón es medible: la función
    # que resuelve el léxico (`_cuerpos_de_un_termino`) prueba la forma y, si no
    # encuentra, prueba la FAMILIA. Así que una entrada `pena` alcanza igual a
    # `fam:pena`, que cubre «causa ilícita» (CC art. 1478) y «cláusula penal»
    # (CC art. 1476) — materia civil. Verificado: con la entrada puesta,
    # «cláusula penal en un contrato civil» arrastraba ('cp','cpp').
    # Es la razón —medida el 2026-10-01 sobre las 31 reservadas— por la que
    # `fam:pena` no es materia, y sigue sin serlo. El tratamiento está en
    # `TERMINOS_PENA_SANCION`, que exige el CONTEXTO de sanción.
    "condenatori": "cp", "absolutori": "cp", "privativ": "cp",
    "punitiv": "cp", "delituos": "cp", "imputad": "cp", "imputar": "cp",
    "agravacion": "cp", "condenacion": "cp", "condena": "cp", "conden": "cp",
    # Procesal penal (el género, no la sustantiva)
    # Procesal: casi todo el procedimiento penal vive en el CP y en el CPP. Un
    # término procesal declara AMBOS: si el CP no está cubierto, decir «cubierto»
    # porque el CPP sí lo está afirma una cobertura que el abogado no tiene.
    "prescripcion": ("cp", "cpp"), "imprescriptible": ("cp", "cpp"),
    "plazo": ("cpp", "cot"), "prueba": ("cpp", "cc", "cot"),
    "querella": ("cp", "cpp"), "acusacion": ("cp", "cpp"),
    "auto": ("cpp", "cc"), "sentencia": ("cp", "cpp", "cc"),
    "recurso": ("cpp", "cc", "cot"), "medida": ("cp", "cpp"),
}

# De los términos del léxico, cuáles son ambiguos y NO pueden decidir el cuerpo
# por sí solos. «defensa» aparece en ambos campos; «plazo» es procesal en todas
# las materias; «sentencia» existe en el CPC, en el CPP y en el Código Civil.
#
# H8, 3.ª ronda: esto antes era un comentario y una lista a medias. El defecto
# medido fue que `sentencia` → ("cp","cpp","cc") fixaba el Código Penal para
# una consulta de apelación civil. Ahora la decisión de cuerpo pasa a ser
# contextuales: la materia que el abogado DECLARA («civil», «laboral») manda.
TERMINOS_AMBIGUOS = frozenset({"defensa", "medida", "plazo", "prueba", "recurso", "auto",
                               "menor", "abuso", "violacion", "remision", "detencion"})

# ── Materia declarada por el abogado (3.ª ronda de H8) ───────────────────────
# El defecto medido: una palabra que vive en varias materias («sentencia»)
# fijaba un cuerpo sin que la consulta declarara cuál. Aquí se declara la
# materia que el abogado ESCRIBE, no la que se deduce.
#
# Las claves son FAMILIAS, no formas de superficie, porque así las guarda el
# índice y así las devuelve `familia()`: «penal» y «pena» son la misma
# (`fam:pena`), «laboral» y «trabajo» también (`fam:laboral`).
LEXICO_MATERIA_DECLARADA: dict[str, str] = {
    "civil": "civil",
    "fam:laboral": "laboral",
    "fam:trabajador": "laboral",
    # «penal» NO se declara materia aquí, y es deliberado. Medido el
    # 2026-10-01 sobre las 31 consultas reservadas: declarar `fam:pena` como
    # materia penal producía 3 advertencias nuevas y falsas, porque la familia
    # también cubre «causa ilícita» («nulidad absoluta por objeto o causa
    # ilícita», CC art. 1478) y «cláusula penal» (CC art. 1476), que son materia
    # civil. La materia penal se detecta por el LÉXICO (homicidio, hurto,
    # cuasidelito), que no tiene esa ambigüedad: una familia que agrupa de más
    # es peor que no agrupar.
    "tributari": "tributario",
    "comercial": "comercial",
    "constitucional": "constitucional",
    "ambiental": "ambiental",
    "fam:consumidor": "consumidor",
    "fam:previsional": "previsional",
}

# Los cuerpos que cada materia usa, tomados del catálogo
# (`materias_catalog.v1.json`) y NO del léxico. Un cuerpo que la materia declara
# es un cuerpo que el abogado espera: si el pack no lo tiene, hay que decirlo.
CUERPOS_POR_MATERIA: dict[str, tuple[str, ...]] = {
    "civil": ("cc", "cpc", "cot"),
    "laboral": ("ct", "ley_16744", "ley_17322", "ley_19728", "dl_3500"),
    "penal": ("cp", "cpp", "ley_20000", "ley_18216"),
    "tributario": ("ctrib",),
    "comercial": ("ccom", "ley_18046", "ley_18092", "ley_20720"),
    "constitucional": ("cpr",),
    "ambiental": ("dfl_1122",),
    "consumidor": ("ley_19496",),
    "previsional": ("dl_3500", "ley_16744", "ley_17322", "ley_19728"),
}

# El cuerpo NUCLEAR de cada materia: donde vive el grueso de sus preguntas.
#
# No es lo mismo que «los cuerpos de la materia». En laboral, el Código del
# Trabajo es el cuerpo nuclear; la Ley 17.322 (cobranza de cotizaciones, 34
# artículos en el pack) pertenece a la materia pero NO responde «despido del
# trabajador», y usarlo como cuerpo esperado producía una advertencia falsa:
# medido el 2026-10-01, «despido del trabajador en Chile» salía SIN_COBERTURA
# avisando de la Ley 17.322. Un cuerpo satélite no puede portar el veredicto.
CUERPO_NUCLEO_POR_MATERIA: dict[str, tuple[str, ...]] = {
    "civil": ("cc",),
    "laboral": ("ct",),
    "penal": ("cp",),
    "tributario": ("ctrib",),
    "comercial": ("ccom",),
    "constitucional": ("cpr",),
    "ambiental": ("dfl_1122",),
    "consumidor": ("ley_19496",),
    "previsional": ("dl_3500",),
}

# El cuerpo PROCEDURAL de cada materia, para cuando la consulta es
# claramente procesal («plazo para apelar una sentencia definitiva civil»).
# El CPC está instalado con 920 de los artículos que declara el catálogo: es
# `sustancial`, no `minimo`. Declararlo evita que una consulta procesal civil
# espere el Código Civil y reciba, en cambio, un artículo de otro cuerpo.
CUERPOS_PROCESALES_POR_MATERIA: dict[str, tuple[str, ...]] = {
    "civil": ("cpc", "cot"),
    "laboral": ("cot",),
    "penal": ("cpp", "cot"),
    "tributario": ("cot",),
    "comercial": ("cot",),
}

# Términos que el abogado escribe en MÁS de una materia. Cada entrada justifica
# por qué no puede fijar un cuerpo: es la lista que el arreglo de H8 3.ª ronda
# hace explícita, y la que `test_todo_ttermino_ambiguo_del_lexico_esta_clasificado`
# usa para auditar que todo término multi-cuerpo esté aquí.
#
# «plazo» es procesal civil, laboral, penal y tributario. «prueba» vive en el
# CPC, en el Código Civil y en el Código del Trabajo. «recurso», «auto» y
# «sentencia» tienen tres cuerpos cada uno. «medida» es una palabra vacía en
# derecho: nadie sabe si habla de una medida cautelar o de una medida disciplinaria.
TERMINOS_MATERIA_COMPARTIDA: frozenset[str] = frozenset({
    # Procedural o procesal: existen en el CPC, el CPP y el COT.
    "plazo", "fam:plazo", "prueba", "fam:prueb", "recurso", "fam:recurs",
    "auto", "medida", "medid", "sentenci", "sentencia",
    # sustantivas que también son sustantivas civiles: no son solo penales.
    "abuso", "violacion", "detencion", "remision", "menor", "defensa",
})

# Estos términos también mapean a varios cuerpos, pero CONSERVAN el veredicto de
# cuerpo. La unión es la respuesta honesta: «prescripción» vive en el CP (2 de
# 674 artículos) y en el CPP (550), y el abogado necesita saber que falta el
# primero. Declararlos «compartidos» los silenciaría, que es el defecto
# contrario y peor: una advertencia de menos sobre una materia que NO se cubre.
# No son de materia compartida: son materia que el propio término declara.
TERMINOS_LEXICO_PRESERVA: frozenset[str] = frozenset({
    "prescripcion", "imprescriptible", "querella", "acusacion",
})

# ── «pena» y «penal»: la palabra que SÍ distingue es el CONTEXTO (4.ª ronda) ─
# La familia `fam:pena` no puede ser materia: cubre «causa ilícita» (CC art.
# 1478) y «cláusula penal» (CC art. 1476), que son civil. Pero «pena del
# delito de hurto» es tan penal como «hurto», y con el léxico solo quedaba
# muda: era exactamente el caso del encargo.
#
# La regla es de COOCURRENCIA, no de forma. «pena» decide cuerpo penal si la
# consulta nombra algo que solo existe en materia penal —el delito, la persona
# imputada, la prisión— o si otra palabra de sanción ya decidió. Si el único
# contexto es civil («cláusula penal», «causa»), NO decide. Es el mismo
# criterio con el que no se declara `fam:pena`, aplicado un escalón más
# arriba: en vez de renunciar a la palabra, se exige la prueba que la acompaña.
FAMILIAS_PENA = frozenset({"pena", "fam:pena", "penal", "punitiv"})

# Un término que solo existe en materia penal. Si alguno está en la consulta,
# «pena» deja de ser ambigua y decide. Se listan familias, no formas, porque la
# consulta se lee por familia.
CONTEXTO_PENAL_INEQUIVOCO = frozenset({
    "delit", "delituos", "delito", "delitos",     # «delito», «delituoso»
    "homicid", "homicidi", "parricid",             # delitos de muerte
    "hurto", "robo", "estafa", "mascara", "sindicat", "lesion",
    "imputad", "imputar", "imputacion", "querell", "acusacion",
    "condenatori", "absolutori", "reclusion", "detencion", "reclud",
    "privativ", "delitos", "condena", "conden", "condenacion", "agravacion",
})


def _pena_es_sancion(terminos_q: Iterable[str]) -> bool:
    """«pena»/`penal` nombran una SANCIÓN, o son la palabra civil de un contrato.

    Se decide por coocurrencia con un término que solo existe en materia penal.
    «pena del delito de hurto» → True. «cláusula penal en un contrato civil» →
    False, porque ahí la penalidad es una cláusula, no una condena.
    """
    familias = {_fam(t) for t in terminos_q}
    if familias & CONTEXTO_PENAL_INEQUIVOCO:
        return True
    # Ya hay un término inequívocamente penal decidiendo: entonces la pena que
    # lo acompaña es la misma pena, y confirmarlo no cambia el veredicto.
    return any(_cuerpos_de_un_termino(t) and _fam(t) not in FAMILIAS_PENA
               and "cp" in _cuerpos_de_un_termino(t) for t in terminos_q)


# ── Umbrales léxicos ──────────────────────────────────────────────────────────
# Calibrados con las 7 consultas de humo del encargo, NO con `normas_qrels_v1`
# (que queda reservada para medir). Números y qué separan:
#
#   consulta                        cobertura_terminos   veredicto
#  .deletion… (despido del trabajador)      1.00            CUBIERTO
#   goodness (homicidio)                      1.00            SIN_COBERTURA  ← por CUERPO
#  ｡prescripción de la acción                 1.00            SIN_COBERTURA  ← por CUERPO
#   legit defense                        1.00            SIN_COBERTURA  ← por CUERPO
#   impuesto a las criptomonedas            0.50            SIN_COBERTURA  ← por TÉRMINO
#   receta de pastel de chocolate           0.33            SIN_COBERTURA  ← por TÉRMINO
#   taxi licuado                         0.00            SIN_COBERTURA  ← por TÉRMINO
#
# El corte en 0.60 separa «al menos la mitad de los conceptos están» de «la
# consulta nombra cosas que aquí no existen». Con 0.50 el caso de las
# criptomonedas would need an exact tie-break; con 0.60 «impuesto» solo (0.50)
# cae del lado correcto sin ambigüedad.
UMBRAL_COBERTURA_TERMINOS = 0.60
# Un solo concepto, sin ambigüedad, basta: no se puede exigir cobertura a un
# término único.
MINIMO_CONCEPTOS_PARA_EXIGIR = 2

# ── Términos de relleno (2.ª ronda de H8, 2026-10-01) ────────────────────────
# El defecto medido: «impuesto a las criptomonedas en Chile» tiene 3 conceptos
# (`impuest`, `criptomoned`, `chile`) y el índice tiene 2 → 0,67 > 0,60 → CUBIERTO.
# El concepto central NO existe en ninguno de los 8.544 artículos, pero `chile`
# está en 4.100 y tapó el hueco. `chile` no es un concepto: es el marco donde el
# abogado pregunta. Todo abogado chileno escribe «en Chile» en todas sus
# consultas, así que contarlo como concepto da cobertura artificial a todas.
#
# Regla de inclusión: entra un término solo si APORTA MATEMA CERO. La geografía
# que el abogado da por supuesta y los verbos de explicación entran; la
# «legislación» NO entra, porque una consulta sobre legislación pide materia
# («prescripción en la legislación chilena» sigue teniendo un concepto central).
#
# Se comparan por FAMILIA, no por forma de superficie: el índice guarda
# `chilen`, no `chilena`.
TERMINOS_RELLENO: frozenset[str] = frozenset({
    # Geografía que el abogado da por supuesta al preguntar derecho chileno.
    "chile", "chilen", "nacional", "hombre", "mujer",
    # Marco genérico: no dice de qué materia habla. «según la ley» es la
    # fórmula con que el abogado declara su duda, no una materia.
    #
    # «legislación» NO entra, aunque se parece: una consulta que la nombra está
    # pidiendo materia concreta («en la legislación chilena» + un concepto central), y
    # tratarla como relleno dejaría un solo concepto de contenido y la
    # abstención se desactivaría sola. Se comprobó: con `legislacion` en la lista,
    # «criptomonedas en la legislación chilena» salía CUBIERTO.
    "ley",
    # Verbos y conectores de explicación: «¿cómo funciona el impuesto a las
    # criptomonedas?» pregunta lo mismo que «impuesto a las criptomonedas».
    "funcion", "como", "dice", "diga", "ser", "estar", "hacer",
})

# El corte de la cobertura de CONTENIDO. Distinto del de arriba a propósito: el
# bruto incluye el relleno (y por eso miente); el de contenido no. Con los
# valores de esta lista NO se baja ningún caso de humo: sube.
UMBRAL_COBERTURA_CONTENIDO = 0.60

# Una consulta con pocos conceptos no se juzga por fracción. «Impuesto a las
# criptomonedas en Chile» tiene 2 conceptos de contenido y le falta 1: esa es la
# mitad de lo que el abogado pidió, y responder con artículos tributarios sería
# contestando otra pregunta. Con 5 o 6 conceptos, un ausente es ruido estadístico.
CONCEPTOS_MAXIMOS_PARA_ABSTENCION = 4


def _familias_indice_y_consulta(
    indice: Any, terminos_consulta: Iterable[str]
) -> tuple[set[str], set[str]]:
    """(familias presentes en el índice, familias de la consulta).

    Se compara por FAMILIA y no por término. El índice está derivado a raíz al
    construirse (`_idf` guarda `impuest`, no `impuesto`), así que comparar la
    forma de superficie de la consulta contra las claves del índice marca como
    ausente casi todo término cuya raíz difiere de su forma — que es la mayoría.
    """
    return {_fam(t) for t in _df(indice)}, {_fam(t) for t in terminos_consulta}


def _fam(termino: str) -> str:
    try:
        from lexo_cli.starter.morfologia import familia

        return familia(termino)
    except Exception:  # noqa: BLE001 — sin morfología, la forma literal
        return termino


def _df(indice: Any) -> Iterable[str]:
    """Los términos que el índice conoce. Acepta el doble de test y el real."""
    df = getattr(indice, "df", None)
    if df is None:
        df = getattr(indice, "_idf", {}) or {}
    return list(df)


def _n_documentos(indice: Any) -> int:
    for atributo in ("total_documentos", "_n_documentos"):
        valor = getattr(indice, atributo, None)
        if isinstance(valor, int) and valor > 0:
            return valor
    largo = getattr(indice, "_largo", None)
    if isinstance(largo, dict) and largo:
        return len(largo)
    return 0


def _cuerpo_de_gid(indice: Any, gid: str) -> str | None:
    alias = getattr(indice, "alias_de_gid", None)
    if isinstance(alias, dict):
        return alias.get(gid)
    interno = getattr(indice, "_alias", None)
    if isinstance(interno, dict):
        return interno.get(gid)
    partes = str(gid or "").split(":")
    return partes[1] if len(partes) >= 2 and partes[1] else None


def _terminos_consulta(query: str) -> list[str]:
    try:
        from lexo_cli.starter.retrieval import terminos

        return list(terminos(query))
    except Exception:  # noqa: BLE001
        return [t for t in str(query).lower().split() if len(t) > 2]


def _cuerpos_de_un_termino(termino: str) -> tuple[str, ...]:
    """Cuerpos que el léxico asocia a un término. Uno o varios."""
    valor = LEXICO_MATERIA.get(termino)
    if valor is None:
        valor = LEXICO_MATERIA.get(_fam(termino))
    if valor is None:
        return ()
    return (valor,) if isinstance(valor, str) else tuple(valor)


def _materia_declarada(terminos_q: Iterable[str]) -> tuple[str | None, bool]:
    """La materia que el abogado ESCRIBE, y si hay varias en conflicto.

    Se declara solo si el abogado la nombra. Una consulta con dos materias
    explícitas («civil y laboral») NO se resuelve: declarar una sería
    inventarse una preferencia que el abogado no escribió. Por eso se devuelve
    también el flag de conflicto, y el veredicto de CUERPO se abstiene.
    """
    vistas: list[str] = []
    for termino in terminos_q:
        materia = LEXICO_MATERIA_DECLARADA.get(termino) or LEXICO_MATERIA_DECLARADA.get(
            _fam(termino)
        )
        if materia and materia not in vistas:
            vistas.append(materia)
    if not vistas:
        return None, False
    if len(vistas) > 1:
        return None, True
    return vistas[0], False


def _es_procesal(terminos_q: Iterable[str]) -> bool:
    """La consulta es de materia procesal, no sustantiva.

    Un plazo, un recurso o una apelación son materia procesal aunque el abogado
    no escriba «procesal». Es la razón por la que la materia civil espera el
    CPC y no solo el Código Civil.
    """
    return any(
        t in TERMINOS_MATERIA_COMPARTIDA or _fam(t) in TERMINOS_MATERIA_COMPARTIDA
        for t in terminos_q
    )


def _cuerpos_esperados(terminos_q: Iterable[str]) -> tuple[tuple[str, ...], str | None, bool]:
    """Cuerpos que la consulta espera, la materia declarada y si hay conflicto.

    Devuelve `(cuerpos, materia, materia_en_conflicto)`. La firma cambió en la
    3.ª ronda de H8: antes devolvía solo los cuerpos y tomaba la unión literal
    del léxico, que es lo que produjo el falso positivo.

    La regla, en orden:

    1. **Materia declarada**: manda. Si el abogado escribe «civil», los cuerpos
       esperados son los de la materia civil. El Código Penal desaparece aunque
       «sentencia» lo tuviera en su lista.
    2. **Sin materia declarada**: se usa la unión del léxico, PERO solo si algún
       término con peso propio la justifica. Si lo único que hay son términos
       compartidos («sentencia» a secas), no se afirma ningún cuerpo: no sabemos
       de qué materia habla el abogado, y decirlo sería inventarlo.
    """
    materia, en_conflicto = _materia_declarada(terminos_q)
    terminos = list(terminos_q)

    if en_conflicto:
        # Dos materias explícitas: no hay preferencia que orthonormalizar. Se
        # devuelve la unión de ambas para que la señal sea legible, y el
        # veredicto de CUERPO se abstiene aguas arriba.
        cuerpos: set[str] = set()
        return tuple(sorted(cuerpos)), None, True

    if materia:
        cuerpos = set(CUERPO_NUCLEO_POR_MATERIA.get(materia, ()))
        if _es_procesal(terminos):
            cuerpos.update(CUERPOS_PROCESALES_POR_MATERIA.get(materia, ()))
        return tuple(sorted(cuerpos)), materia, False

    # Sin materia declarada: el léxico, pero filtrado por peso propio. Un
    # término compartido («sentencia», «plazo») no levanta una afirmación sobre
    # el cuerpo; uno sustantivo («homicidio») sí.
    #
    # «pena»/`penal` se resuelven aparte: comparten familia con «causa
    # ilícita» y «cláusula penal», que son civil, así que solo deciden cuando
    # la consulta trae el CONTEXTO de sanción. Sin ese contexto no son un
    # término compartido: son otro término compartido, y por lo tanto no
    # afirman un cuerpo.
    lexico: set[str] = set()
    con_peso_propio = False
    pena_es_sancion = _pena_es_sancion(terminos)
    for termino in terminos:
        if _fam(termino) in FAMILIAS_PENA:
            # Solo decide si el contexto lo vuelve这样的人; si no, aporta
            # tanto como «sentencia»: nada.
            if pena_es_sancion:
                lexico.update(("cp", "cpp"))
                con_peso_propio = True
            continue
        candidatos = _cuerpos_de_un_termino(termino)
        if not candidatos:
            continue
        compartido = (
            termino not in TERMINOS_LEXICO_PRESERVA
            and _fam(termino) not in TERMINOS_LEXICO_PRESERVA
            and (termino in TERMINOS_MATERIA_COMPARTIDA
                 or _fam(termino) in TERMINOS_MATERIA_COMPARTIDA)
        )
        lexico.update(candidatos)
        if not compartido:
            con_peso_propio = True
    if lexico and not con_peso_propio:
        # Solo hay términos compartidos: la materia no se sabe. Se declara la
        # ambigüedad en vez de elegir un cuerpo.
        return (), None, False
    return tuple(sorted(lexico)), None, False


def _cuerpos_candidatos(terminos_q: Iterable[str]) -> tuple[tuple[str, ...], ...]:
    """Los cuerpos que la consulta DEJA entrever, sin decidir entre ellos.

    Es la función que hace existir a `AMBIGUA`. `_cuerpos_esperados` devuelve la
    lista VACÍA cuando solo hay términos compartidos, porque afirmar un cuerpo
    ahí sería inventarse la preferencia del abogado. El veredicto, en cambio,
    no necesita decidirlos: necesita NOMBRARLOS para que el abogado pueda.

    Se devuelve una tupla de tuplas — un conjunto de conjuntos — y no una unión,
    a propósito. La unión es lo que llama la atención («estos son los cuerpos»);
    lo que la honestidad exige es poder decir «esta palabra sugiere estos dos»,
    porque «medida» sugiere {cp, cpp} y «plazo» sugiere {cpp, cot}, y el sistema
    no sabe si la consulta es del uno o del otro. Aplanarlo pierde esa
    información y hace parecer que hay un cuerpo conjunto cuando no lo hay.
    """
    grupos: list[tuple[str, ...]] = []
    for termino in terminos_q:
        candidatos = _cuerpos_de_un_termino(termino)
        if candidatos and candidatos not in grupos:
            grupos.append(candidatos)
    return tuple(grupos)


def _profundidad(alias: str) -> dict[str, Any]:
    """Lo declarado de un cuerpo: artículos en el pack, total del catálogo, estado.

    Se expone como señal aparte para que la interfaz pueda pintar «2 de 674» sin
    tener que recalcularla, y para que el número que se ve sea exactamente el que
    gobierna el veredicto — no una segunda fuente de verdad que pueda divergir.
    """
    declarado = CORPUS_DECLARADO["cuerpos"].get(alias) or {}
    return {
        "articulos": declarado.get("articulos_en_pack", 0),
        "articulos_totales": declarado.get("articulos_totales"),
        "estado": _estado_cuerpo(alias),
    }


def _profundidad_texto(alias: str) -> str:
    """«2 de 674» o «550 artículos», según lo que se sepa del cuerpo."""
    declarado = CORPUS_DECLARADO["cuerpos"].get(alias) or {}
    en_pack = declarado.get("articulos_en_pack", 0)
    total = declarado.get("articulos_totales")
    return f"{en_pack} de {total}" if total else f"{en_pack} artículos"


def _estado_cuerpo(alias: str | None) -> str:
    """sustancial | minimo | ausente, según la profundidad declarada."""
    if not alias:
        return "ausente"
    declarado = CORPUS_DECLARADO["cuerpos"].get(alias)
    if declarado is None:
        return "ausente"
    en_pack = declarado["articulos_en_pack"]
    total = declarado["articulos_totales"]
    if total is None:
        # Sin total conocido no se puede llamar «mínimo»: se presume sustancial
        # solo si el cuerpo tiene volumen. Nunca se inventa una proporción.
        return "sustancial" if en_pack >= 50 else "minimo"
    return "sustancial" if (en_pack / total) >= UMBRAL_PROFUNDIDAD else "minimo"


def evaluar(query: str, indice: Any, resultados: list[dict] | None) -> dict[str, Any]:
    """Veredicto de cobertura de `query` sobre `indice` con estos `resultados`.

    Devuelve SIEMPRE un dict con `veredicto`, `mensaje` y las señales que lo
    produjeron. No lanza: la ausencia de cobertura es una respuesta.
    """
    terminos_q = _terminos_consulta(query)
    df = {t for t in _df(indice)}
    familias_indice, familias_q = _familias_indice_y_consulta(indice, terminos_q)
    familias_fuente = {_fam(t): t for t in terminos_q}
    # El término ausente se nombra por su FAMILIA (que es como está el índice),
    # no por su forma de superficie: el mensaje tiene que decir algo que el
    # abogado pueda buscar, y `impuest` es lo que existe en el índice.
    familias_ausentes = sorted(familias_q - familias_indice)
    ausentes = [familias_fuente[f] for f in familias_ausentes]

    n_conceptos = len(familias_q) or 1
    n_cubiertas = len(familias_q & familias_indice)
    cobertura = n_cubiertas / n_conceptos if familias_q else 0.0

    # ── Relleno vs. contenido (H8, 2.ª ronda) ──────────────────────────────────
    # Un concepto de relleno no es materia: el abogado lo da por supuesto. Se
    # separa ANTES de medir, y lo que se descarta se DECLARA en las señales,
    # porque si el número no cuadra con lo que el abogado escribió hay que
    # poder verlo.
    familias_relleno = {f for f in familias_q if f in TERMINOS_RELLENO}
    familias_contenido = {f for f in familias_q if f not in TERMINOS_RELLENO}
    # Una consulta que solo trae relleno («¿en Chile?») no tiene materia que
    # exigir: se mide sobre lo que hay, sin inventar un vacío.
    conceptos_medidos = familias_contenido or familias_q
    relleno_presente = familias_relleno & familias_indice
    relleno_ausente = familias_relleno - familias_indice

    n_contenido = len(conceptos_medidos) or 1
    n_contenido_cubiertas = len(conceptos_medidos & familias_indice)
    cobertura_contenido = n_contenido_cubiertas / n_contenido if conceptos_medidos else 0.0

    familias_contenido_ausentes = sorted(conceptos_medidos - familias_indice)
    # Los ausentes que se INFORMAN son los de contenido. Listar «chile» como
    # ausente cuando el abogado no estaba preguntando por Chile es ruido que
    # esconde el término que de verdad falta.
    ausentes = [familias_fuente[f] for f in familias_contenido_ausentes]
    relleno_descartado = sorted(familias_fuente[f] for f in relleno_presente)
    relleno_faltante = sorted(familias_fuente[f] for f in relleno_ausente)

    cuerpos_esperados, materia_declarada, materia_en_conflicto = _cuerpos_esperados(
        terminos_q
    )
    cuerpo_esperado = cuerpos_esperados[0] if len(cuerpos_esperados) == 1 else None
    # Un término compartido sin materia declarada deja los cuerpos vacíos a
    # propósito: el veredicto de CUERPO no se emite y esto queda declarado.
    cuerpo_ambiguo = not cuerpos_esperados and bool(
        any(t in TERMINOS_MATERIA_COMPARTIDA or _fam(t) in TERMINOS_MATERIA_COMPARTIDA
            for t in terminos_q)
    )
    # Los candidatos de la ambigüedad se calculan UNA vez y se usan para la
    # señal y para el veredicto, para que no puedan divergir: una lista de
    # candidatos que se pinta y otra distinta que decide es la forma sutil de
    # mentir dos veces.
    grupos_ambiguos = _cuerpos_candidatos(terminos_q) if cuerpo_ambiguo else ()
    candidatos_ambiguos = {c for grupo in grupos_ambiguos for c in grupo}
    # `AMBIGUA` con un candidato (ronda 6, opción (a), aprobada por Cristóbal).
    # Antes exigía MÁS DE UN cuerpo y con uno solo devolvía `CUBIERTO` en
    # silencio: «defensa» y «abuso de funciones públicas» están en
    # `TERMINOS_MATERIA_COMPARTIDA` y el léxico los resuelve a `cp`, así que el
    # abogado recibía artículos del Código Penal sin que nada dijera que la
    # materia no la había declarado él.
    #
    # Con UN candidato la ambigüedad no es «entre varios cuerpos»: es que el
    # término es de materia compartida y solo hay una lectura posible. Se
    # declara eso, con su motivo propio, para que un veredicto con un candidato
    # sea distinguible de uno con varios al auditar.
    ambigua_emisible = (
        cuerpo_ambiguo
        and len(candidatos_ambiguos) >= 1
        and not materia_declarada
        and not materia_en_conflicto
        and not cuerpos_esperados
    )
    alias_top1 = None
    if resultados:
        alias_top1 = resultados[0].get("alias") or _cuerpo_de_gid(indice, resultados[0].get("gid", ""))

    senales = {
        "terminos_consulta": list(terminos_q),
        "terminos_ausentes": sorted(ausentes),
        "cobertura_terminos": round(cobertura, 3),
        "n_conceptos": len(familias_q),
        # Señales de contenido: las que gobiernan el veredicto léxico.
        "n_conceptos_contenido": len(conceptos_medidos),
        "n_conceptos_contenido_cubiertos": n_contenido_cubiertas,
        "cobertura_contenido": round(cobertura_contenido, 3),
        "terminos_contenido_ausentes": sorted(ausentes),
        "terminos_relleno_descartados": relleno_descartado,
        "terminos_relleno_ausentes": relleno_faltante,
        "cuerpo_esperado": cuerpo_esperado,
        "cuerpos_esperados": list(cuerpos_esperados),
        "cuerpos_esperados_sin_cubrir": [
            c for c in cuerpos_esperados if _estado_cuerpo(c) == "minimo"
        ],
        # H8, 3.ª ronda: por qué se esperaba un cuerpo, o por qué no.
        "materia_declarada": materia_declarada,
        "materia_en_conflicto": materia_en_conflicto,
        "cuerpo_ambiguo": cuerpo_ambiguo,
        # H8, 5.ª ronda: qué cuerpos DEJA VER la consulta cuando no sabemos
        # cuál espera. Van como unión (para poder pintar una lista) y como
        # grupos (para poder decir qué palabra sugiere qué). Un cuerpo que sale
        # de aquí NO es un cuerpo esperado: no hay veredicto de cobertura
        # sobre él, solo el nombre.
        "cuerpos_ambiguos_candidatos":sorted(candidatos_ambiguos),
        "cuerpos_ambiguos_grupos": [list(g) for g in grupos_ambiguos],
        "cuerpos_ambiguos_profundidad": {
            a: _profundidad(a) for a in sorted(candidatos_ambiguos)
        },
        "cuerpo_top1": alias_top1,
        "estado_cuerpo_esperado": _estado_cuerpo(cuerpo_esperado) if cuerpo_esperado else None,
        "estado_cuerpo_top1": _estado_cuerpo(alias_top1),
    }

    # Un concepto de contenido ausente en una consulta CORTA ya obliga a
    # abstenerse. En una consulta larga, un ausente es ruido: se aplica la
    # fracción. La condición exige que quede materia cubierta — si el índice no
    # tiene ninguno de los conceptos de contenido, la fracción de arriba (0.00)
    # ya cae por su cuenta.
    consulta_corta = len(conceptos_medidos) <= CONCEPTOS_MAXIMOS_PARA_ABSTENCION
    corto_con_ausente = (
        consulta_corta
        and len(conceptos_medidos) >= MINIMO_CONCEPTOS_PARA_EXIGIR
        and n_contenido_cubiertas >= 1
        and familias_contenido_ausentes
    )

    # ── Veredicto 1: la consulta nombra cosas que el índice no tiene ──────────
    if (not resultados
            or corto_con_ausente
            or (ausentes and len(conceptos_medidos) >= MINIMO_CONCEPTOS_PARA_EXIGIR
                and cobertura_contenido < UMBRAL_COBERTURA_CONTENIDO)):
        faltan = ", ".join(sorted(ausentes)[:3]) or "todos los términos"
        return {
            "veredicto": "SIN_COBERTURA",
            "motivo": "terminos_ausentes_del_indice",
            "mensaje": (
                f"Mi corpus no cubre esta consulta: {faltan} no aparece en ninguno "
                f"de sus artículos. Te devuelvo lo más parecido que tengo, pero "
                f"no te puedo responder sobre eso."
            ),
            **senales,
        }

    # ── Veredicto 2: los términos existen, pero el cuerpo no está ───────────
    # Es el caso del encargo. Los términos de la consulta aparecen en artículos
    # de OTRO cuerpo: el lawyers necesita el Código Penal y el pack tiene 2 de
    # sus 674 artículos. Devolver el Código Civil sería responder otra pregunta.
    if (cuerpos_esperados
            and not materia_en_conflicto  # materia ambigua: no se afirma un cuerpo
            and senales["cuerpos_esperados_sin_cubrir"]):
        from lexo_cli.starter.materias import cuerpo_label

        # Se nombra el cuerpo no cubierto, con su profundidad. Si la consulta
        # señalaba varios, se nombran TODOS los que faltan: tapar uno con otro
        # es la forma silenciosa de mentir.
        faltan = senales["cuerpos_esperados_sin_cubrir"]
        partes = []
        for alias in faltan:
            declarado = CORPUS_DECLARADO["cuerpos"].get(alias) or {}
            en_pack = declarado.get("articulos_en_pack", 0)
            total = declarado.get("articulos_totales")
            depth = f"{en_pack} de {total}" if total else f"{en_pack} artículos"
            partes.append(f"{cuerpo_label(alias)} ({depth})")
        return {
            "veredicto": "SIN_COBERTURA",
            "motivo": "cuerpo_no_cubierto",
            "mensaje": (
                f"Sin cobertura de {' y '.join(partes)} en mi biblioteca. "
                f"Los artículos que te muestro son de "
                f"{cuerpo_label(alias_top1) if alias_top1 else 'otro cuerpo'} y no "
                f"responden tu consulta."
            ),
            **senales,
        }

    # ── Veredicto 3: cobertura parcial, declarable pero no citable ──────────
    if (cobertura_contenido < 1.0
            and len(conceptos_medidos) >= MINIMO_CONCEPTOS_PARA_EXIGIR):
        return {
            "veredicto": "PARCIAL",
            "motivo": "cobertura_parcial_de_terminos",
            "mensaje": (
                f"Cobertura parcial ({int(cobertura_contenido * 100)}% de los conceptos de tu "
                f"consulta). Faltan: {', '.join(sorted(ausentes)[:3])}."
            ),
            **senales,
        }

    # ── Veredicto 4: no sé de qué materia me hablas (H8, 5.ª ronda) ─────────
    # Va DESPUÉS de los dos `SIN_COBERTURA` y DEL `PARCIAL`, y antes de
    # `CUBIERTO`. El orden no es arbitrario y es la restricción dura del
    # encargo: si hay un término inequívocamente penal, `_cuerpos_esperados`
    # ya devolvió un cuerpo y el veredicto 2 (cuerpo_no_cubierto) cortó antes.
    # `AMBIGUA` solo existe en el hueco que queda entre «nada que afirmar» y
    # «cubierto», que es exactamente donde el sistema callaba.
    if ambigua_emisible:
        from lexo_cli.starter.materias import cuerpo_label

        # Se nombra cada candidato con su profundidad. Y si alguno está en
        # profundidad MÍNIMA, eso va en el mensaje aunque el veredicto sea de
        # ambigüedad: el abogado tiene que saber el riesgo antes de elegir
        # camino. «No sé» sin «y el riesgo es este» es media verdad.
        partes: list[str] = []
        riesgos: list[str] = []
        for alias in sorted(candidatos_ambiguos):
            texto = f"{cuerpo_label(alias)} ({_profundidad_texto(alias)})"
            partes.append(texto)
            if _estado_cuerpo(alias) == "minimo":
                riesgos.append(texto)
        # Con un SOLO candidato no se puede decir «entre varios cuerpos»: sería
        # describir una ambigüedad que no existe. Lo que sí es cierto —y es el
        # motivo del veredicto— es que el término es de materia compartida y el
        # abogado no declaró cuál. El motivo cambia para que las dos formas se
        # distingan al auditar.
        if len(candidatos_ambiguos) == 1:
            mensaje = (
                f"«{partes[0]}» es un término que varias materias usan y no me "
                f"dijiste de cuál me hablas. Te muestro artículos de "
                f"{cuerpo_label(next(iter(candidatos_ambiguos)))}, pero dime la "
                f"materia y te respondo con el cuerpo que corresponde."
            )
            motivo = "materia_compartida_declarada_por_una_sola_lectura"
        else:
            mensaje = (
                f"No sé de qué materia me hablas: tu consulta puede ser del "
                f"{' o del '.join(partes)}. Dime la materia y te respondo con el "
                f"cuerpo que corresponde."
            )
            motivo = "materia_no_declarada_entre_varios_cuerpos"
        if riesgos:
            mensaje += (
                f" Ojo con el camino que elijas: de "
                f"{', '.join(riesgos)} mi biblioteca tiene una parte mínima."
            )
        return {
            "veredicto": "AMBIGUA",
            "motivo": motivo,
            "mensaje": mensaje,
            **senales,
        }

    return {
        "veredicto": "CUBIERTO",
        "motivo": "cobertura_completa",
        "mensaje": "Mi corpus cubre los términos de esta consulta.",
        **senales,
    }


def declarar_cobertura_pack(indice: Any | None = None) -> dict[str, Any]:
    """Qué cuerpos cubre el pack y con qué profundidad. Para la interfaz.

    Con `indice` usa el recuento real del índice instalado; sin él, el declarado.
    Los dos se comparan: si discrepan, la diferencia se declara en vez de
    esconderse — un número de runtime que no cuadra con el declarado es
    justamente el tipo de cosa que hay que mostrar.
    """
    declaracion = {
        "fecha": CORPUS_DECLARADO["fecha"],
        "pack": CORPUS_DECLARADO["pack"],
        "cuerpos_catalogo": CORPUS_DECLARADO["cuerpos_catalogo"],
        "cuerpos_cubiertos": len(CORPUS_DECLARADO["cuerpos"]),
        "articulos_en_pack": CORPUS_DECLARADO["articulos_en_pack"],
        "cuerpos": {},
    }
    for alias, declarado in sorted(CORPUS_DECLARADO["cuerpos"].items()):
        en_pack = declarado["articulos_en_pack"]
        total = declarado["articulos_totales"]
        declaracion["cuerpos"][alias] = {
            "articulos": en_pack,
            "articulos_totales": total,
            "estado": _estado_cuerpo(alias),
            "cobertura": round(en_pack / total, 4) if total else None,
        }
    if indice is not None:
        por_cuerpo = getattr(indice, "por_cuerpo", None)
        if not por_cuerpo:
            por_cuerpo = getattr(indice, "_por_cuerpo", {}) or {}
        # El retriever real guarda `dict[alias, list[gid]]`; un doble puede traer
        # `dict[alias, int]`. Se aceptan las dos formas: el número es el mismo.
        real = {
            a: (len(gids) if isinstance(gids, (list, tuple, set)) else int(gids))
            for a, gids in (por_cuerpo or {}).items()
        }
        declaracion["articulos_medidos"] = sum(real.values()) or None
        declaracion["cuerpos_medidos"] = len(real) or None
        discrepancias = {
            a: {"declarado": declaracion["cuerpos"][a]["articulos"], "medido": n}
            for a, n in real.items()
            if a in declaracion["cuerpos"] and declaracion["cuerpos"][a]["articulos"] != n
        }
        declaracion["discrepancias"] = discrepancias or {}
        # Con índice, el número de cuerpos cubiertos es el MEDIDO. El declarado
        # queda a la vista para que la diferencia sea legible.
        declaracion["cuerpos_cubiertos_declarado"] = declaracion["cuerpos_cubiertos"]
        declaracion["cuerpos_cubiertos"] = len(real) or declaracion["cuerpos_cubiertos"]
    return declaracion
