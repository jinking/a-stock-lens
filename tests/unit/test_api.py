from fastapi.testclient import TestClient

from astock_lens.api.app import create_app


def test_health_route() -> None:
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "A-Stock Lens"}
