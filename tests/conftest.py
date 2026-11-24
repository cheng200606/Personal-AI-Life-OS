from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from personal_ai_life_os.config import Settings
from personal_ai_life_os.main import create_app


@pytest.fixture
def app(tmp_path) -> FastAPI:
    config = Settings(
        _env_file=None,
        app_env="test",
        api_host="127.0.0.1",
        data_dir=tmp_path / "data",
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'lifeos.sqlite3').as_posix()}",
        auto_create_schema=True,
        access_token_secret="test-only-secret-value-with-at-least-32-characters",
        registration_mode="open",
        object_store_backend="local",
        model_provider="none",
    )
    return create_app(config)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
