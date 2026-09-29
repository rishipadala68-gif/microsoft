from fastapi.testclient import TestClient

from api.index import app


def test_api_index_import_and_app():
    assert app is not None
    assert app.title == "Incident Response Agent"


def test_api_index_client():
    client = TestClient(app)
    # Testing that root returns status ok and links to docs
    root_resp = client.get("/")
    assert root_resp.status_code == 200
    root_data = root_resp.json()
    assert root_data["status"] == "ok"
    assert root_data["docs"] == "/docs"

    # Testing that openapi spec works
    response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert data["info"]["title"] == "Incident Response Agent"

