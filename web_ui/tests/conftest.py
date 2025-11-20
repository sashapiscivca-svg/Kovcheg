import pytest
from fastapi.testclient import TestClient
from web_ui.backend.app import app

@pytest.fixture(scope="module")
def client():
    # Використовуємо TestClient для тестування FastAPI
    with TestClient(app) as c:
        yield c
