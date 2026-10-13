def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_field_is_rejected(client):
    response = client.post(
        "/api/v1/students",
        json={"email": "a@example.com", "display_name": "A", "unexpected": True},
    )
    assert response.status_code == 422

