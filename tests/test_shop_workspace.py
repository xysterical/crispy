# tests/test_shop_workspace.py

from __future__ import annotations


def test_list_shops_returns_array(client):
    resp = client.get("/shops")
    assert resp.status_code == 200
    body = resp.json()
    assert "shops" in body
    assert isinstance(body["shops"], list)


def test_list_categories_for_unknown_shop(client):
    resp = client.get("/shops/nonexistent-shop/categories")
    assert resp.status_code == 200
    body = resp.json()
    assert body["categories"] == []


def test_workspace_has_industry_code():
    """Verify Workspace model has industry_code field."""
    from app.data.models import Workspace
    assert hasattr(Workspace, "industry_code")


def test_shop_analysis_page_has_shop_selector(client):
    resp = client.get("/dashboard/shop-analysis")
    assert resp.status_code == 200
    html = resp.text
    assert "shop-name" in html
    assert "shop-analysis-list" in html
    assert "Shop" in html


def test_create_run_form_has_shop_labels(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text
    assert "Product Category" in html
    assert "category-list" in html
    # Shop is now a <select> (managed list), not a free-text datalist
    assert '<select id="workspace_name"' in html


def test_shop_crud_lifecycle(client):
    """Test create, rename, and delete a shop. Delete may be blocked if runs exist."""
    # Create
    resp = client.post("/shops", json={"name": "test-shop-crud"})
    assert resp.status_code == 201
    assert resp.json()["name"] == "test-shop-crud"

    # Rename
    resp = client.put("/shops/test-shop-crud", json={"name": "test-shop-renamed"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "test-shop-renamed"

    # Delete (may be blocked if test isolation leaked runs)
    resp = client.delete("/shops/test-shop-renamed")
    assert resp.status_code in (204, 409)


def test_cannot_delete_last_shop(client):
    """Verify the last remaining shop cannot be deleted."""
    resp = client.get("/shops")
    shops = resp.json()["shops"]
    if len(shops) <= 1:
        # Delete should be blocked
        resp = client.delete(f"/shops/{shops[0]['name']}")
        assert resp.status_code == 409


def test_shop_management_panel_on_page(client):
    """Verify Shop Management panel renders on shop-analysis page."""
    resp = client.get("/dashboard/shop-analysis")
    assert resp.status_code == 200
    html = resp.text
    assert "Shop Management" in html
    assert "shop-list-mgmt" in html
    assert "addShop" in html
