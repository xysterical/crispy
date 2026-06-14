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


def test_dtc_site_image_preset_is_available(client):
    resp = client.get("/creative-presets?workspace_name=test_ws")
    assert resp.status_code == 200
    system = {p["key"]: p for p in resp.json()["system"]}

    preset = system["dtc_site_image_pack"]
    assert preset["image_size"] == "4:5"
    assert preset["resolution"] == "1600px"
    assert preset["video_duration_seconds"] == 5
    assert preset["platform_targets"] == ["shopify"]


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


def test_storyboard_candidate_count_round_trips_for_user_preset(client):
    resp = client.post(
        "/creative-presets",
        json={
            "name": "Storyboard Heavy Video",
            "workspace_name": "test_ws",
            "image_size": "9:16",
            "video_size": "9:16",
            "resolution": "720p",
            "video_duration_seconds": 12,
            "storyboard_candidate_count": 3,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["storyboard_candidate_count"] == 3

    list_resp = client.get("/creative-presets?workspace_name=test_ws")
    assert list_resp.status_code == 200
    user_presets = {p["id"]: p for p in list_resp.json()["user"]}
    assert user_presets[data["id"]]["storyboard_candidate_count"] == 3


def test_mode_specific_preset_fields_round_trip_for_user_preset(client):
    resp = client.post(
        "/creative-presets",
        json={
            "name": "TikTok Shop Styled",
            "workspace_name": "test_ws",
            "image_size": "9:16",
            "video_size": "9:16",
            "resolution": "720p",
            "video_duration_seconds": 12,
            "storyboard_candidate_count": 2,
            "tiktok_video_style": "direct_response_ad",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["tiktok_video_style"] == "direct_response_ad"

    dtc_resp = client.post(
        "/creative-presets",
        json={
            "name": "DTC Hero",
            "workspace_name": "test_ws",
            "image_size": "4:5",
            "video_size": "4:5",
            "resolution": "1600px",
            "video_duration_seconds": 5,
            "site_surface": "homepage_hero",
        },
    )
    assert dtc_resp.status_code == 201
    dtc_data = dtc_resp.json()
    assert dtc_data["site_surface"] == "homepage_hero"

    list_resp = client.get("/creative-presets?workspace_name=test_ws")
    assert list_resp.status_code == 200
    user_presets = {p["id"]: p for p in list_resp.json()["user"]}
    assert user_presets[data["id"]]["tiktok_video_style"] == "direct_response_ad"
    assert user_presets[dtc_data["id"]]["site_surface"] == "homepage_hero"


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


def test_update_preset_can_change_mode_specific_fields(client):
    resp = client.post(
        "/creative-presets",
        json={"name": "Mode Preset", "workspace_name": "test_ws", "image_size": "9:16"},
    )
    preset_id = resp.json()["id"]

    update = client.put(
        f"/creative-presets/{preset_id}",
        json={"tiktok_video_style": "shop_account_content", "site_surface": "homepage_hero"},
    )
    assert update.status_code == 200
    assert update.json()["tiktok_video_style"] == "shop_account_content"
    assert update.json()["site_surface"] == "homepage_hero"


def test_update_preset_can_change_storyboard_candidate_count(client):
    resp = client.post(
        "/creative-presets",
        json={"name": "Candidate Count Preset", "workspace_name": "test_ws", "image_size": "1:1"},
    )
    preset_id = resp.json()["id"]

    update = client.put(
        f"/creative-presets/{preset_id}",
        json={"storyboard_candidate_count": 4},
    )
    assert update.status_code == 200
    assert update.json()["storyboard_candidate_count"] == 4


def test_duplicate_preset_name_update_conflict(client):
    first = client.post(
        "/creative-presets",
        json={"name": "First", "workspace_name": "test_ws", "image_size": "1:1"},
    )
    second = client.post(
        "/creative-presets",
        json={"name": "Second", "workspace_name": "test_ws", "image_size": "1:1"},
    )
    assert first.status_code == 201
    assert second.status_code == 201

    conflict = client.put(
        f"/creative-presets/{second.json()['id']}",
        json={"name": "First"},
    )
    assert conflict.status_code == 409

    unchanged = client.get("/creative-presets?workspace_name=test_ws").json()["user"]
    names = {row["id"]: row["name"] for row in unchanged}
    assert names[first.json()["id"]] == "First"
    assert names[second.json()["id"]] == "Second"


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
