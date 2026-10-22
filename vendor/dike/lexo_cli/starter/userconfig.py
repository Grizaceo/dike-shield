"""Config de usuario Diké: `~/.lexo/config.yaml` y la clave `starter.user`.

El dolor #2 (error "hay N workspaces con starter instalado") nace de que el
resolver no sabe qué usuario elegir. Este módulo escribe la elección de forma
persistente: `dike onboard` y `dike web` la fijan, y `resolve_corpus_roots`
la lee vía `load_config()`.

Reglas:
- `set_active_user(user_id)` escribe/actualiza `starter.user` en el primer
  archivo de config existente, o crea `~/.lexo/config.yaml` si no hay ninguno.
- `active_user(cfg=None)` devuelve el usuario activo: `cfg` explícito > env
  `DIKE_USER` > `starter.user` de disco > None. El `cfg` solo invierte la
  precedencia si viene dado; sin él, la variable global manda como antes.
- Nunca toca `starter.roots` ni otras claves: solo la selección de usuario.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from lexo_cli.config import CONFIG_PATHS, DEFAULT_CONFIG, load_config

_USER_KEY = ("starter", "user")

DEFAULT_USERS_ROOT = Path.home() / ".dike" / "users"
# La raíz de casos que trae la configuración por defecto. Si el valor efectivo
# sigue siendo este, nadie la eligió: se deriva del usuario activo.
DEFAULT_CASES_ROOT = Path(DEFAULT_CONFIG["cases"]["root"]).expanduser()


def _config_path() -> Path:
    """Primer archivo de config existente, o el default `~/.lexo/config.yaml`.

    Respeta `LEXO_CONFIG` (variable de entorno del propio load_config): si
    está definida, la config efectiva es esa, y es ahí donde se escribe.
    """
    env_path = os.environ.get("LEXO_CONFIG")
    if env_path:
        return Path(env_path).expanduser().resolve()
    for path in CONFIG_PATHS:
        if path.exists():
            return path
    return Path.home() / ".lexo" / "config.yaml"


def set_active_user(user_id: str) -> Path:
    """Persiste `starter.user` en la config y devuelve la ruta escrita."""
    path = _config_path()
    data: dict = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            data = loaded
    starter = dict(data.get("starter") or {})
    starter["user"] = user_id
    data["starter"] = starter
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def set_users_root(users_root: str | Path) -> Path:
    """Persiste `starter.users_root` cuando el abogado eligió otra ubicación.

    `dike onboard --users-root /datos/dike` creaba el workspace ahí y no lo
    escribía en ninguna parte: los comandos siguientes buscaban en
    `~/.dike/users`, no encontraban corpus, y el abogado veía búsquedas
    vacías sin ningún error que explicara por qué.
    """
    path = _config_path()
    data: dict = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            data = loaded
    starter = dict(data.get("starter") or {})
    starter["users_root"] = str(Path(users_root).expanduser())
    data["starter"] = starter
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def active_user(cfg: dict | None = None) -> str | None:
    """Usuario activo: `cfg` explícito > env `DIKE_USER` > config > None.

    Acepta `cfg` por la misma razón que `active_users_root`: si el caller tiene
    una configuración point-to-point, el entorno no debe poder sustituirla. Sin
    este parámetro, `resolve_cases_root(cfg)` resolvía la raíz por el `cfg` y el
    usuario por el entorno, y componía una ruta que no era de nadie —
    `<raíz-del-cfg>/<usuario-del-entorno>/cases`. La instrucción point-to-point
    llegaba a medias.

    El matiz que importa: la precedencia se invierte SOLO cuando hay `cfg`. Sin
    él, `DIKE_USER` sigue ganando a la config de disco, y no es un detalle. La
    config persistida trae el usuario real del abogado (`tu-nombre` en una
    instalación nueva), así que darle prioridad haría que `DIKE_USER=maria` fuera
    ignorado y el operador acabara en el workspace de otra persona — el mismo
    veredicto falso, en la dirección contraria. `dike --user` por entorno y los
    tests que fijan el usuario así dependen de esto.

    O sea: el global se acota cuando hay una instrucción point-to-point que lo
    contradiga, y manda cuando no la hay.
    """
    if cfg is not None:
        configured = (cfg.get("starter") or {}).get("user")
        if configured:
            return str(configured)
    env = os.environ.get("DIKE_USER")
    if env:
        return env
    configured = ((cfg if cfg is not None else load_config()).get("starter") or {}).get("user")
    return str(configured) if configured else None


def active_users_root(cfg: dict | None = None) -> Path:
    """Raíz de workspaces: cfg explícito > env > default.

    El `cfg` que un caller pasa es una instrucción POINT-TO-POINT: ese caller
    sabe dónde está su workspace y lo dice. `DIKE_USERS_ROOT` es un valor
    GLOBAL de la máquina: existe para ejecutar `dike` contra otro workspace
    desde la shell, y sin `cfg` sigue mandando — ese es su propósito y no se
    elimina.

    Antes el orden era env > cfg, lo que dejaba el `cfg` sin efecto posible: un
    caller que recibía un workspace explícito veía cómo lo descartaba una
    variable del entorno, y el síntoma era un veredicto FALSO — `CASE_NOT_FOUND`
    para un caso que sí existía, con un error que no señalaba la causa real.
    Costó 19 tests de custodia en una sola corrida antes de poder diagnosticarlo.

    El hermano `resolve_cases_root()` ya aplicaba esta misma regla para su
    parámetro `users_root` explícito («gana a DIKE_USERS_ROOT/configuración»).
    Acotar el global para que no pise al point-to-point es, además, hacer que
    las dos funciones respondan lo mismo a «¿dónde está mi workspace?».
    """
    cfg = cfg if cfg is not None else load_config()
    configured = (cfg.get("starter") or {}).get("users_root")
    if configured:
        return Path(str(configured)).expanduser()
    env = os.environ.get("DIKE_USERS_ROOT")
    if env:
        return Path(env).expanduser()
    return DEFAULT_USERS_ROOT


def resolve_cases_root(
    cfg: dict | None = None,
    *,
    explicit: str | Path | None = None,
    user_id: str | None = None,
    users_root: str | Path | None = None,
) -> Path:
    """Carpeta de casos del usuario activo.

    El default de configuración era el literal `~/.dike/users/default/cases`,
    con el usuario `default` incrustado. Como `dike onboard` crea el
    workspace del abogado real (`maria`), la web escribía los casos en
    `~/.dike/users/maria/cases` mientras `dike nif status`, `dike status` y
    NIF Studio los buscaban en `.../default/cases`: el mismo caso existía y
    no existía según por dónde se entrara. Aquí la raíz se deriva del usuario
    activo, salvo que la configuración fije una ruta propia.

    Deuda E-10 saldada: `users_root` explícito (flag `--users-root`) gana a
    `DIKE_USERS_ROOT`/configuración; `user_id` (flag `--user`) gana al usuario
    persistido. Sin ambos, comportamiento idéntico al anterior.

    `cfg` se propaga a las dos mitades de la ruta. Antes solo alcanzaba la raíz: el
    usuario se pedía con `active_user()` sin `cfg`, que volvía a leer el entorno,
    y un caller que declaraba usuario y raíz veía composición mixta
    (`<raíz-del-cfg>/<usuario-del-entorno>/cases`) — una ruta que no le
    pertenece a nadie. Con la propagación, la instrucción point-to-point se
    respeta completa o no se respeta.
    """
    if explicit:
        return Path(explicit).expanduser()
    # Distinguir «el caller trajo cfg» de «lo cargué yo» no es un detalle: es lo
    # que separa una instrucción point-to-point de la config de disco. Si se
    # trataran igual, la config persistida del abogado se volvería
    # point-to-point y pisaría a `DIKE_USER`, que es un override deliberado
    # del operador. Pasar hacia abajo la config cargada aquí, en vez de None,
    # producía `DIKE_USER=otro` + casos en `tu-nombre/cases`: el usuario
    # pedido y el directorio real, distintos.
    caller_cfg = cfg is not None
    cfg = cfg if cfg is not None else load_config()
    configured = str((cfg.get("cases") or {}).get("root") or "")
    if configured and Path(configured).expanduser() != DEFAULT_CASES_ROOT:
        return Path(configured).expanduser()
    if users_root is None:
        base = active_users_root(cfg if caller_cfg else None)
    else:
        base = Path(users_root).expanduser()
    user = user_id or active_user(cfg if caller_cfg else None) or "default"
    return base / user / "cases"
