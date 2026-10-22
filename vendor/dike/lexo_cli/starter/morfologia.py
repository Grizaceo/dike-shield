"""Morfología del castellano jurídico para la recuperación de normas.

BM25 sobre formas de superficie falla en castellano legal por dos razones que
se miden: el corpus está redactado en una morfología y la consulta en otra.

1. **Flexión.** El art. 1698 dice «probar las *obligaciones*» y el abogado
   escribe «probar la *obligación*». Son el mismo término.
2. **Derivación.** El art. 1489 dice «condición *resolutoria* de no
   *cumplirse* lo pactado»; el abogado escribe «*resolución* del contrato por
   *incumplimiento*». Ninguna de las tres palabras coincide, y el artículo
   central de la resolución contractual chilena no aparecía ni en el top 8.

Aquí se separan los dos problemas a propósito:

- La flexión se resuelve con una regla mecánica y conservadora (`lema`):
  plural y género, nada más. Es predecible y no necesita revisión jurídica.
- La derivación se resuelve con una **tabla curada** (`FAMILIAS`), no con un
  stemmer. En una herramienta jurídica una tabla que un abogado puede leer y
  corregir vale más que un algoritmo opaco: cada familia es una afirmación
  revisable sobre qué palabras nombran la misma institución.

Ninguna de las dos borra la distinción en el índice. `retrieval` puntúa la
coincidencia exacta con todo su peso y la variante con un peso menor, y deja
dicho en la evidencia por qué recuperó el artículo. Un índice que conflara los
términos haría desaparecer esa traza.
"""

from __future__ import annotations

import unicodedata

# Longitud mínima de la raíz tras podar. Debajo de esto la poda destruye el
# término en vez de normalizarlo («mora» -> «mor»).
_MINIMO = 5


def sin_acentos(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def lema(termino: str) -> str:
    """Forma flexiva canónica: singular y sin marca de género.

    Solo plural y género. No toca la derivación: «prescripción» y
    «prescribir» siguen siendo términos distintos aquí, y se relacionan —si
    corresponde— por `FAMILIAS`.
    """
    t = sin_acentos(termino)
    # Plural. Se poda una sola «s» y luego, si queda, la vocal final: así
    # «contratantes» y «contratante» llegan ambos a «contratant», que es el
    # objetivo — coincidir entre sí, no acertar la forma del diccionario.
    if t.endswith("ces") and len(t) >= 6:                 # jueces -> juez
        t = t[:-3] + "z"
    elif t.endswith("s") and len(t) - 1 >= 4:
        t = t[:-1]
    # Vocal final (género o «-e» de la flexión anterior), con cuerpo mínimo.
    if t[-1:] in ("o", "a", "e") and len(t) - 1 >= _MINIMO:
        t = t[:-1]
    return t


# Familias de la misma institución jurídica. Cada línea es una afirmación
# revisable: las palabras de un grupo nombran lo mismo para efectos de
# encontrar la norma, aunque no signifiquen lo mismo para resolver el caso
# («cumplimiento» e «incumplimiento» apuntan al mismo artículo; cuál de los
# dos ocurrió lo decide el abogado, no el buscador).
_GRUPOS: tuple[tuple[str, ...], ...] = (
    # -- obligaciones y contratos --------------------------------------------
    ("resolucion", "resolutoria", "resolutorio", "resolver", "resuelto", "resuelve", "resciliacion"),
    ("cumplimiento", "incumplimiento", "cumplir", "cumplirse", "cumplida", "incumplir", "incumplida", "incumplido"),
    ("obligacion", "obligar", "obligado", "obliga", "obligan", "deuda", "debitoria"),
    ("acreedor", "acreedora", "credito"),
    ("deudor", "deudora"),
    ("contrato", "contratar", "contratacion", "convencion", "pacto", "pactado"),
    ("contratante", "parte", "contraparte", "otorgante", "comparecientes"),
    ("mora", "moroso", "morosa", "constituido", "retardo", "atraso"),
    ("indemnizacion", "indemnizar", "resarcimiento", "reparacion"),
    ("perjuicio", "dano", "detrimento", "menoscabo"),
    ("culpa", "negligencia", "negligente", "descuido", "imprudencia", "culposa", "culposo"),
    ("dolo", "doloso", "dolosa", "malicia", "malicioso"),
    ("nulidad", "nulo", "nula", "anular", "anulacion", "invalidar", "invalidado", "rescision", "rescindir", "rescindirse", "vicio", "viciado"),
    ("lesion", "lesionar", "enorme"),
    ("prescripcion", "prescribir", "prescriben", "prescribiran", "prescrita", "prescrito", "prescripta"),
    ("caducidad", "caducar", "caduca"),
    ("extincion", "extinguir", "extinguirse", "extinguen", "extintiva"),
    ("interpretacion", "interpretar", "intencion", "sentido"),
    ("buena", "lealtad", "probidad"),
    ("promesa", "prometer", "prometido", "prometiente"),
    ("clausula", "estipulacion", "estipulado", "estipular"),
    ("pena", "penal", "multa", "sancion"),
    ("compraventa", "venta", "vender", "vendedor", "comprador", "comprar"),
    ("arrendamiento", "arriendo", "arrendar", "arrendador", "arrendatario"),
    ("renta", "canon", "alquiler"),
    ("consentimiento", "consentir", "voluntad", "asentimiento"),
    ("error", "erroneo", "erronea", "equivocacion"),
    ("fuerza", "violencia", "intimidacion"),
    ("solidaridad", "solidario", "solidaria"),
    ("condicion", "condicional", "modalidad"),
    ("plazo", "termino", "periodo"),
    ("precario", "precaria", "restitucion", "restituir"),
    # -- prueba y proceso -----------------------------------------------------
    ("prueba", "probar", "probatorio", "probatoria", "acreditar", "acreditado", "probanza"),
    ("carga", "incumbe", "corresponde", "peso"),
    ("accion", "demanda", "demandar", "demandante", "accionar", "pretension"),
    ("excepcion", "excepcionar", "defensa"),
    ("sentencia", "fallo", "fallar"),
    ("notificacion", "notificar", "emplazamiento", "emplazar"),
    ("recurso", "recurrir", "apelacion", "apelar", "casacion"),
    ("juicio", "procedimiento", "proceso", "litigio"),
    ("competencia", "competente", "jurisdiccion"),
    # -- laboral --------------------------------------------------------------
    ("despido", "despedir", "despedido", "desvinculacion"),
    # «término» se deja en la familia de «plazo»: en el Código es tanto el
    # fin de una relación como el vencimiento de un lapso, y desambiguar
    # sin contexto haría más daño que el que repara.
    ("terminacion", "terminar", "expiracion", "expirar", "cesacion", "cesar"),
    ("trabajador", "trabajadora", "dependiente", "asalariado"),
    ("empleador", "empleadora", "patron", "empresa"),
    ("remuneracion", "sueldo", "salario", "estipendio"),
    ("cotizacion", "previsional", "imposicion", "prevision"),
    ("finiquito", "finiquitar"),
    ("injustificado", "injustificada", "indebido", "indebida", "improcedente"),
    ("necesidad", "necesidades", "reestructuracion"),
    ("laboral", "trabajo", "laborales"),
    ("fuero", "aforado", "inamovilidad"),
    ("tutela", "vulneracion", "vulnerar", "garantia"),
    # -- responsabilidad extracontractual -------------------------------------
    ("delito", "cuasidelito", "ilicito", "ilicita"),
    ("responsabilidad", "responsable", "responder", "responde"),
    # -- consumo, sociedades, concursal ---------------------------------------
    ("consumidor", "consumo", "proveedor"),
    ("sociedad", "societario", "socio", "accionista"),
    ("quiebra", "insolvencia", "concursal", "liquidacion", "reorganizacion"),
    # -- familia --------------------------------------------------------------
    ("alimentos", "alimentario", "alimentante", "pension"),
    ("filiacion", "paternidad", "maternidad", "hijo"),
    ("matrimonio", "conyuge", "conyugal", "divorcio"),
    # -- sucesorio y bienes ---------------------------------------------------
    ("herencia", "heredero", "sucesion", "hereditaria", "hereditario"),
    ("posesion", "poseedor", "poseer", "tenencia"),
    ("dominio", "propiedad", "propietario", "dueno"),
    ("hipoteca", "hipotecario", "prenda", "caucion"),
    ("servidumbre", "predio", "predial"),
)


def _construir() -> dict[str, str]:
    tabla: dict[str, str] = {}
    for grupo in _GRUPOS:
        clave = "fam:" + lema(grupo[0])
        for palabra in grupo:
            # Un término que ya pertenece a otra familia conserva la primera:
            # las familias se leen en orden y el orden es parte de la tabla.
            tabla.setdefault(lema(palabra), clave)
    return tabla


_FAMILIA_POR_LEMA = _construir()


def familia(termino: str) -> str:
    """Clave de familia de un término: la curada si existe, si no su lema.

    Devolver el lema como clave por defecto hace que la flexión y la
    derivación se consulten con un solo diccionario, sin que un término fuera
    de la tabla quede sin agrupar.
    """
    raiz = lema(termino)
    return _FAMILIA_POR_LEMA.get(raiz, raiz)
