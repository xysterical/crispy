# tests/test_run_templates.py

from __future__ import annotations


def test_create_and_list_template(client):
    resp = client.post(
        "/run-templates",
        json={
            "name": "Dog Leash Meta Campaign",
            "workspace_name": "test_ws",
            "config_json": {
                "pipeline_mode": "full_multimodal",
                "variant_count": 8,
                "channel": "meta",
            },
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Dog Leash Meta Campaign"
    assert data["config_json"]["pipeline_mode"] == "full_multimodal"
    template_id = data["id"]

    list_resp = client.get("/run-templates?workspace_name=test_ws")
    assert list_resp.status_code == 200
    assert any(t["id"] == template_id for t in list_resp.json())


def test_update_template(client):
    resp = client.post(
        "/run-templates",
        json={"name": "Old Template", "workspace_name": "test_ws", "config_json": {"x": 1}},
    )
    template_id = resp.json()["id"]

    update = client.put(
        f"/run-templates/{template_id}",
        json={"name": "Renamed Template", "config_json": {"x": 2}},
    )
    assert update.status_code == 200
    assert update.json()["name"] == "Renamed Template"
    assert update.json()["config_json"]["x"] == 2


def test_delete_template(client):
    resp = client.post(
        "/run-templates",
        json={"name": "To Delete", "workspace_name": "test_ws", "config_json": {}},
    )
    template_id = resp.json()["id"]

    delete = client.delete(f"/run-templates/{template_id}")
    assert delete.status_code == 204

    list_resp = client.get("/run-templates?workspace_name=test_ws")
    assert not any(t["id"] == template_id for t in list_resp.json())


def test_duplicate_template_name_conflict(client):
    client.post(
        "/run-templates",
        json={"name": "Dup", "workspace_name": "test_ws", "config_json": {}},
    )
    resp = client.post(
        "/run-templates",
        json={"name": "Dup", "workspace_name": "test_ws", "config_json": {}},
    )
    assert resp.status_code == 409


def test_template_not_found(client):
    resp = client.put("/run-templates/nonexistent-id", json={"name": "X"})
    assert resp.status_code == 404
