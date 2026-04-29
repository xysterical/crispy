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
    assert "shop-list" in html
    assert "category-list" in html
