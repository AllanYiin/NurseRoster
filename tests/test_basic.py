from fastapi.testclient import TestClient

from app.main import create_app


def test_health():
    app = create_app()
    c = TestClient(app)
    r = c.get('/api/health')
    assert r.status_code == 200
    assert r.json()['ok'] is True
