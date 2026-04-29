# tests/test_creative_presets.py

from __future__ import annotations


def test_list_presets_includes_system(client):
    resp = client.get("/creative-presets?workspace_name=test_ws")
    assert resp.status_code == 200
    body = resp.json()
    assert "system" in body
    assert "user" in body
    system_keys = [p["key"] for p in body["system"]]
    assert "meta_square_5s" in system_keys
    assert "meta_vertical_5s" in system_keys


def test_tiktok_shop_conversion_preset_is_available(client):
    resp = client.get("/creative-presets?workspace_name=test_ws")
    assert resp.status_code == 200
    system = {p["key"]: p for p in resp.json()["system"]}

    preset = system["tiktok_shop_conversion_12s"]
    assert preset["image_size"] == "9:16"
    assert preset["video_size"] == "9:16"
    assert preset["resolution"] == "720p"
    assert preset["video_duration_seconds"] == 12
    assert preset["platform_targets"] == ["tiktok", "tiktok_shop"]


def test_create_and_list_user_preset(client):
    resp = client.post(
        "/creative-presets",
        json={
            "name": "TikTok Vertical",
            "workspace_name": "test_ws",
            "image_size": "9:16",
            "video_size": "9:16",
            "resolution": "720p",
            "video_duration_seconds": 30,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "TikTok Vertical"
    assert data["image_size"] == "9:16"
    preset_id = data["id"]

    list_resp = client.get("/creative-presets?workspace_name=test_ws")
    assert list_resp.status_code == 200
    user_presets = list_resp.json()["user"]
    assert any(p["id"] == preset_id for p in user_presets)


def test_update_preset(client):
    resp = client.post(
        "/creative-presets",
        json={"name": "Old Name", "workspace_name": "test_ws", "image_size": "1:1"},
    )
    preset_id = resp.json()["id"]

    update = client.put(
        f"/creative-presets/{preset_id}",
        json={"name": "New Name", "resolution": "1080p"},
    )
    assert update.status_code == 200
    assert update.json()["name"] == "New Name"
    assert update.json()["resolution"] == "1080p"


def test_delete_preset(client):
    resp = client.post(
        "/creative-presets",
        json={"name": "To Delete", "workspace_name": "test_ws", "image_size": "1:1"},
    )
    preset_id = resp.json()["id"]

    delete = client.delete(f"/creative-presets/{preset_id}")
    assert delete.status_code == 204

    list_resp = client.get("/creative-presets?workspace_name=test_ws")
    assert not any(p["id"] == preset_id for p in list_resp.json()["user"])


def test_duplicate_preset_name_conflict(client):
    client.post(
        "/creative-presets",
        json={"name": "Unique", "workspace_name": "test_ws", "image_size": "1:1"},
    )
    resp = client.post(
        "/creative-presets",
        json={"name": "Unique", "workspace_name": "test_ws", "image_size": "9:16"},
    )
    assert resp.status_code == 409


def test_preset_not_found(client):
    resp = client.put(
        "/creative-presets/nonexistent-id",
        json={"name": "X"},
    )
    assert resp.status_code == 404
