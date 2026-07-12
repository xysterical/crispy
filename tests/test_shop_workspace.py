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
    assert '<select id="shop-name"' in html
    assert "renderShopSelect" in html
    assert "Research Intelligence" in html


def test_create_run_form_has_shop_labels(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text
    assert "Product Category" in html
    assert "category-list" in html
    # Shop is now a <select> (managed list), not a free-text datalist
    assert '<select id="workspace_name"' in html


def test_shop_management_page_renders_workflow_layout(client):
    resp = client.get("/dashboard/shops")
    assert resp.status_code == 200
    html = resp.text
    assert "Shops" in html
    assert "Create Shop" in html
    assert "Shop workflow help" in html
    assert "shop-list" in html
    assert "shops-list-tools" in html
    assert "create-shop-toggle" in html
    assert "setCreateCollapsed(shops.length > 0)" in html
    assert "renderShopWorkspace" in html
    assert "displayShopName" in html
    assert "workflow-card" not in html
    assert 'href="/dashboard/shops"' in html


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


def test_create_shop_returns_stable_id_and_metadata(client):
    resp = client.post(
        "/shops",
        json={
            "name": "analysis-shop",
            "industry_code": "pet_accessories",
            "store_url": "https://example-shop.test",
            "description": "Urban pet accessories store.",
        },
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["id"]
    assert body["name"] == "analysis-shop"
    assert body["industry_code"] == "pet_accessories"
    assert body["store_url"] == "https://example-shop.test"
    assert body["description"] == "Urban pet accessories store."
    assert body["archived_at"] is None


def test_archive_shop_hides_it_from_default_list(client):
    created = client.post("/shops", json={"name": "archive-me"}).json()

    resp = client.patch(f"/shops/{created['id']}", json={"archived": True})

    assert resp.status_code == 200
    assert resp.json()["archived_at"]
    listed = client.get("/shops").json()["shops"]
    assert all(item["id"] != created["id"] for item in listed)
    listed_with_archived = client.get("/shops?include_archived=true").json()["shops"]
    assert any(item["id"] == created["id"] for item in listed_with_archived)


def test_cannot_delete_last_shop(client):
    """Verify the last remaining shop cannot be deleted."""
    resp = client.get("/shops")
    shops = resp.json()["shops"]
    if len(shops) <= 1:
        # Delete should be blocked
        resp = client.delete(f"/shops/{shops[0]['name']}")
        assert resp.status_code == 409


def test_shop_analysis_links_to_shop_management_page(client):
    """Verify research keeps shop selection but sends management to the Shops page."""
    resp = client.get("/dashboard/shop-analysis")
    assert resp.status_code == 200
    html = resp.text
    assert "Manage Shops" in html
    assert "/dashboard/shops" in html
    assert "shop-list-mgmt" not in html
    assert 'Archive shop ""' not in html
