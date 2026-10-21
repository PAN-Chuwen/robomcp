# Type stubs for MuJoCo's compiled bindings, which ship without type information.
# The private modules are generated with mypy's stubgen; regenerate after upgrading mujoco:
#   uv run --with mypy stubgen -p mujoco._functions -p mujoco._structs -p mujoco._enums -p mujoco._constants \
#     -p mujoco._errors -p mujoco._callbacks -p mujoco._specs -p mujoco._render -o typings
# This file mirrors the public re-exports of mujoco/__init__.py.
from typing import IO

import numpy as np

from mujoco import _specs as _specs
from mujoco import _structs as _structs
from mujoco._callbacks import *
from mujoco._constants import *
from mujoco._enums import *
from mujoco._errors import *
from mujoco._functions import *
from mujoco._render import *
from mujoco._specs import *
from mujoco._structs import *
from mujoco.rendering.classic.gl_context import *
from mujoco.rendering.classic.renderer import Renderer as Renderer

MJTNUM_DTYPE: type[np.floating]
HEADERS_DIR: str
PLUGINS_DIR: str
__version__: str

def to_zip(spec: _specs.MjSpec, file: str | IO[bytes]) -> None: ...
def from_zip(file: str | IO[bytes]) -> _specs.MjSpec: ...
