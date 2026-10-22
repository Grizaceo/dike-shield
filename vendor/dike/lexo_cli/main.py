"""Diké — punto de entrada de esta distribución.

Esta distribución trae el motor de verificación de citas y nada más: los
comandos que dependen de un agente, de un índice de búsqueda o de un taller de
casos no vienen aquí, y por eso este archivo no es el del repositorio de
origen. Registra los dos comandos que sí están:

    dike starter install <paquete> --name <nombre>   instala un corpus normativo
    dike constancia <escrito>                        verifica las citas de un escrito
"""

from __future__ import annotations

import argparse
import sys

from lexo_cli.commands import constancia, starter

VERSION = "0.1.0"


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="dike",
        description=(
            "Diké — verifica las citas normativas de un escrito contra un corpus "
            "local, y se niega a certificar lo que no puede probar."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Ejemplos:
  dike starter --user demo install ./paquete --name chile-base
  dike constancia escrito.md
  dike constancia escrito.md --json
  dike constancia escrito.md --emit-commitment salida/ --sign""",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    subparsers = parser.add_subparsers(dest="command", help="Comando a ejecutar")
    starter.register(subparsers)
    constancia.register(subparsers)

    args = parser.parse_args()
    handler = getattr(args, "func", None)
    if handler is None:
        parser.print_help()
        sys.exit(1)
    # El código de retorno del comando es el del proceso: 0, 1 o 2 en
    # `constancia` significan cosas distintas y quien llama los necesita.
    code = handler(args)
    if code:
        sys.exit(code)


if __name__ == "__main__":
    main()
