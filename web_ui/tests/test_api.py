import pytest
import httpx
from pydantic import ValidationError
from ark_engine.core.models import ArkModule

# Припускаємо, що client та mock_ark_module існують (з conftest.py)

def test_root_endpoint_loads_html(client: httpx.Client):
    """Перевіряє, чи завантажується головна HTML-сторінка."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Kovcheg" in response.text # Перевіряємо заголовок

def test_modules_endpoint_returns_list(client: httpx.Client):
    """Перевіряє, чи ендпоінт /modules повертає коректний JSON-список."""
    response = client.get("/api/v1/modules")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

    # Якщо модулі знайдені, перевіряємо їхню структуру
    if response.json():
        module_data = response.json()[0]
        assert "id" in module_data
        assert "title" in module_data
        assert "version" == module_data.get("version") # Перевіряємо, що версія повертається

def test_ask_endpoint_valid_request(client: httpx.Client, mocker):
    """
    Перевіряє ендпоінт POST /ask, використовуючи заглушки для RAG-рушія.
    """
    # 1. Створення заглушок для ArkRAG
    mocker.patch('web_ui.backend.rag_router.get_rag_engine', autospec=True)
    
    mock_rag = web_ui.backend.rag_router.get_rag_engine.return_value
    
    mock_rag.search.return_value = [
        ("Citations are crucial.", 0.99),
        ("Offline mode enforced.", 0.85)
    ]
    mock_rag.ask.return_value = "[STUB] The answer is obvious."
    
    # 2. Викликаємо запит
    dummy_module_id = "d110a675-5c9e-4247-af80-15156258879c"
    
    response = client.post("/api/v1/ask", json={
        "query": "Why should I use Kovcheg?",
        "module_id": dummy_module_id
    })

    assert response.status_code == 200
    data = response.json()
    
    # 3. Перевірка схеми відповіді
    assert data['answer'] == "[STUB] The answer is obvious."
    assert len(data['sources']) == 2
    assert data['sources'][0]['chunk'] == "Citations are crucial."
    assert data['sources'][0]['score'] == pytest.approx(0.99) # Використовуємо pytest.approx для float

def test_ask_endpoint_missing_module(client: httpx.Client):
    """Перевіряє, чи повертає 404, якщо модуль не знайдено."""
    response = client.post("/api/v1/ask", json={
        "query": "Test",
        "module_id": "0000-dead-beef-0000"
    })
    assert response.status_code == 404
    assert "Module ID 0000-dead-beef-0000 not found." in response.json()['detail']
