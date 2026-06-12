from fastapi.testclient import TestClient


def test_public_latest_predictions_guest_shows_limited_access(fastapi_app):
    client = TestClient(fastapi_app)
    resp = client.get("/api/v1/public/predictions/latest", params={"limit": 10})
    assert resp.status_code == 200
    data = resp.json()
    # For guest users, access is restricted to 1 unlocked + locked placeholders
    assert "predictions" in data
    assert data["accessible_count"] == 1
    assert data["total_count"] >= 1


def test_public_recent_draws_with_prize_aggregation(fastapi_app):
    client = TestClient(fastapi_app)
    resp = client.get("/api/v1/public/recent-draws", params={"limit": 2})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] in ("success", "no_data")
    if payload["status"] == "success":
        assert payload["count"] == len(payload["draws"]) >= 1
        # Each draw entry has total_prize computed
        assert all("total_prize" in d for d in payload["draws"])


def test_public_register_visit_and_counters(fastapi_app):
    client = TestClient(fastapi_app)
    fp = "test-device-123"
    # First visit
    r1 = client.post("/api/v1/public/register-visit", json={"fingerprint": fp})
    assert r1.status_code == 200
    assert r1.json()["status"] == "success"
    assert r1.json()["new_visit"] is True
    # Second visit should not be new
    r2 = client.post("/api/v1/public/register-visit", json={"fingerprint": fp})
    assert r2.status_code == 200
    assert r2.json()["new_visit"] is False

    counters = client.get("/api/v1/public/counters").json()
    assert counters["visits"] >= 1
    assert "installs" in counters


def test_public_winners_stats(fastapi_app):
    client = TestClient(fastapi_app)
    resp = client.get("/api/v1/public/winners-stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("success", "error")
    # Should always include string dollars
    assert "total_won" in data and isinstance(data["total_won"], str)


def test_public_best_match_all_time(fastapi_app):
    client = TestClient(fastapi_app)
    resp = client.get("/api/v1/public/best-match")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["period"] == "all time"
    assert data["best_match"]["draw_date"] == "2025-09-03"
    assert data["best_match"]["total_prize"] >= 100_000_000
    assert data["best_match"]["has_predictions"] is True


def test_public_predictions_by_draw_with_freemium(fastapi_app):
    # Ensure endpoint formats predictions and applies freemium
    client = TestClient(fastapi_app)
    resp = client.get("/api/v1/public/predictions/by-draw/2025-09-01", params={"limit": 50})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["draw_date"] == "2025-09-01"
    assert "predictions" in body
    # Guest should have 1 accessible
    assert body["accessible_count"] == 1
    assert body["total_count"] >= 1
