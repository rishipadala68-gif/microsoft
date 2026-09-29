from fastapi.testclient import TestClient

from api.index import app


def test_api_index_import_and_app():
    assert app is not None
    assert app.title == "Incident Response Agent"


def test_api_index_client():
    client = TestClient(app)
    # Testing that app can handle requests (e.g. openapi spec or 404 for unknown route)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert data["info"]["title"] == "Incident Response Agent"
