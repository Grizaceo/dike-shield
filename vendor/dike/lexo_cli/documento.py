"""Lectura de los documentos que un abogado realmente tiene: .docx y .pdf.

`resolve_document` trataba cualquier argumento como texto plano: leía el
archivo con `read_text(encoding="utf-8")` y solo capturaba `OSError`. Eso
producía dos fallos graves:

1. `dike analizar demanda.docx` reventaba con `UnicodeDecodeError` y un
   traceback de Python, porque un .docx es un ZIP.
2. `dike analizar deamnda.md` (con el nombre mal escrito) devolvía la cadena
   `"deamnda.md"` **como si fuera el documento**, y el juez emitía un
   veredicto —con nota sobre 10— sobre doce caracteres. El abogado recibía una
   evaluación jurídica de un documento que nunca se leyó, sin ninguna señal de
   que algo hubiera fallado.

Aquí la regla es fail-closed: si el argumento parece un archivo, tiene que
existir y tiene que poder leerse; si no, es un error con reparación, no un
texto.
"""

from __future__ import annotations

from pathlib import Path

# Extensiones que un abogado usa. Si el argumento termina en una de estas, es
# una referencia a un archivo: no puede reinterpretarse como el texto mismo.
DOCUMENT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst",
    ".docx", ".doc", ".pdf", ".rtf", ".odt", ".html", ".htm",
}
PLAIN_EXTENSIONS = {".txt", ".md", ".markdown", ".rst", ".html", ".htm"}


class DocumentoIlegible(ValueError):
    """El documento existe pero no se pudo leer, o no existe."""


def looks_like_path(arg: str) -> bool:
    """¿El argumento es una referencia a un archivo y no el texto mismo?

    Solo un argumento SIN espacios se trata como ruta por su sola forma. Es lo
    que distingue el error que importa —`demanda.docx` mal escrito, un único
    token— de una frase pegada que termina nombrando un archivo («Adjunto
    demanda.pdf»), que antes de esta comprobación habría abortado el análisis.
    Una ruta con espacios sigue funcionando: la resuelve la comprobación de
    existencia en `resolve_document`, no la forma.
    """
    if "\n" in arg or len(arg) >= 256 or not arg.strip():
        return False
    if any(char.isspace() for char in arg.strip()):
        return False
    return Path(arg).suffix.lower() in DOCUMENT_EXTENSIONS


def _read_docx(path: Path) -> str:
    try:
        import docx  # python-docx
    except ImportError as exc:
        raise DocumentoIlegible(
            f"No puedo abrir documentos Word (.docx) en este equipo: falta la "
            f"librería python-docx.\n  Solución rápida: abre «{path.name}» en Word "
            "y usa «Guardar como → Texto sin formato (.txt)».\n"
            "  O instálala con: pip install python-docx"
        ) from exc
    document = docx.Document(str(path))
    partes = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            celdas = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if celdas:
                partes.append(" | ".join(celdas))
    return "\n".join(partes)


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DocumentoIlegible(
            f"No puedo abrir documentos PDF en este equipo: falta la librería "
            f"pypdf.\n  Solución rápida: exporta «{path.name}» a texto o a Word.\n"
            "  O instálala con: pip install pypdf"
        ) from exc
    reader = PdfReader(str(path))
    paginas = [(page.extract_text() or "").strip() for page in reader.pages]
    texto = "\n\n".join(p for p in paginas if p)
    if not texto.strip():
        raise DocumentoIlegible(
            f"«{path.name}» no tiene texto extraíble: probablemente es un PDF "
            "escaneado (una imagen del documento).\n  Necesitas pasarlo por OCR "
            "o usar la versión editable del escrito."
        )
    return texto


def read_document(path: str | Path) -> str:
    """Lee un documento local y devuelve su texto. Nunca devuelve la ruta."""
    p = Path(path).expanduser()
    if not p.exists():
        raise DocumentoIlegible(
            f"No encontré el documento «{p}».\n"
            "  Revisa el nombre y la carpeta, o arrastra el archivo a la terminal "
            "para pegar su ruta completa."
        )
    if p.is_dir():
        raise DocumentoIlegible(
            f"«{p}» es una carpeta, no un documento. Indica el archivo del escrito."
        )
    suffix = p.suffix.lower()
    if suffix == ".docx":
        return _read_docx(p)
    if suffix == ".pdf":
        return _read_pdf(p)
    if suffix in (".doc", ".rtf", ".odt"):
        raise DocumentoIlegible(
            f"El formato «{suffix}» no se puede leer directamente.\n"
            f"  Abre «{p.name}» y guárdalo como .docx, .txt o .pdf."
        )
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Word y LibreOffice guardan .txt en latin-1 con frecuencia.
        try:
            return p.read_text(encoding="latin-1")
        except Exception as exc:  # noqa: BLE001 — se reporta, no se propaga cruda
            raise DocumentoIlegible(
                f"«{p.name}» no parece un documento de texto: no pude leerlo ({exc})."
            ) from exc
    except OSError as exc:
        raise DocumentoIlegible(f"No pude leer «{p}»: {exc}") from exc
