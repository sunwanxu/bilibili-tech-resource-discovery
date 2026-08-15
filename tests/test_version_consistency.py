import tomllib
from pathlib import Path

import bhka

ROOT = Path(__file__).resolve().parents[1]


def _project_version(path: Path) -> str:
    return tomllib.loads(path.read_text(encoding="utf-8"))["project"]["version"]


def test_cli_and_bundled_runtime_versions_match_release_metadata():
    project_version = _project_version(ROOT / "pyproject.toml")
    runtime_version = _project_version(
        ROOT / "skills" / "bilibili-tech-resource-discovery" / "runtime" / "pyproject.toml"
    )
    bundled_init = (
        ROOT
        / "skills"
        / "bilibili-tech-resource-discovery"
        / "runtime"
        / "src"
        / "bhka"
        / "__init__.py"
    ).read_text(encoding="utf-8")

    assert bhka.__version__ == project_version == runtime_version
    assert f'__version__ = "{project_version}"' in bundled_init
