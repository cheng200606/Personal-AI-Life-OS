"""Release metadata consistency for the Windows desktop product version."""

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAURI_CONFIG = ROOT / "desktop/src-tauri/tauri.conf.json"
CARGO_MANIFEST = ROOT / "desktop/src-tauri/Cargo.toml"
CARGO_LOCK = ROOT / "desktop/src-tauri/Cargo.lock"
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"
SMOKE_INSTALLER = ROOT / "desktop/smoke-installer.ps1"
PACKAGE_INIT = ROOT / "src/personal_ai_life_os/__init__.py"


def read_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def product_version() -> str:
    return json.loads(TAURI_CONFIG.read_text(encoding="utf-8"))["version"]


def test_product_version_is_consistent() -> None:
    version = product_version()

    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version
    assert read_toml(CARGO_MANIFEST)["package"]["version"] == version
    assert read_toml(PYPROJECT)["project"]["version"] == version

    init_source = PACKAGE_INIT.read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', init_source, re.MULTILINE)
    assert match, "package __version__ is missing"
    assert match.group(1) == version


def test_lockfiles_record_product_version() -> None:
    version = product_version()

    cargo_lock = read_toml(CARGO_LOCK)
    cargo_package = next(item for item in cargo_lock["package"] if item["name"] == "lifeos")
    assert cargo_package["version"] == version

    uv_lock = read_toml(UV_LOCK)
    uv_package = next(item for item in uv_lock["package"] if item["name"] == "personal-ai-life-os")
    assert uv_package["version"] == version


def test_smoke_installer_reads_product_version() -> None:
    source = SMOKE_INSTALLER.read_text(encoding="utf-8")

    assert "src-tauri/tauri.conf.json" in source
    assert "$config.version" in source
    assert not re.search(r"Personal AI Life OS_0\.1\.0_x64-setup\.exe", source)
    assert not re.search(r"_\d+\.\d+\.\d+_x64-setup\.exe", source)


def test_web_openapi_reports_package_version(tmp_path: Path) -> None:
    from personal_ai_life_os import __version__
    from personal_ai_life_os.config import Settings
    from personal_ai_life_os.main import create_app

    config = Settings(
        _env_file=None,
        app_env="test",
        data_dir=tmp_path / "data",
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'release.sqlite3').as_posix()}",
        auto_create_schema=True,
        access_token_secret="release-test-secret-value-with-at-least-32-characters",
        registration_mode="open",
        object_store_backend="local",
        model_provider="none",
    )
    app = create_app(config)

    assert app.openapi()["info"]["version"] == __version__
    assert __version__ == product_version()