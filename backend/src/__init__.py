from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import tomllib

PACKAGE_NAME = "nitrogen-leaching-agent-backend"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT_FILE = PROJECT_ROOT / "pyproject.toml"


def _load_version() -> str:
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        pass

    try:
        with PYPROJECT_FILE.open("rb") as f:
            return tomllib.load(f)["project"]["version"]
    except FileNotFoundError:
        return "0.0.0"


__version__ = _load_version()
