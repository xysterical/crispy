# Shop & Product Category Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename Workspace→Shop and Project→Product Category across UI, add industry_code to Workspace model, wire cascading dropdowns in Create Run, and link Shop Analysis to Shop selector. All API payload fields and DB columns unchanged for backward compatibility.

**Architecture:** DB-only change is adding `industry_code` to the `workspace` table. Everything else is UI relabeling and JS cascading logic. Shop Analysis page gains Shop selector that auto-populates industry_code from the selected workspace. Create Run form replaces free-text workspace/project inputs with cascading dropdowns (Shop → Product Category), supporting both selection and inline creation.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, raw HTML/CSS/JS, pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `app/data/models.py` | Modify | Add `industry_code` to `Workspace` model |
| `app/data/session.py` | Modify | Add migration for new column |
| `app/schemas/api.py` | Modify | Add Shop/ProductCategory list schemas, workspace view with industry_code |
| `app/api/routes.py` | Modify | Add GET /shops, GET /shops/{id}/categories; relabel UI text; update Shop Analysis page |
| `app/dashboard/layout.py` | Modify | Relabel Data Source → Shop selector |
| `app/dashboard/create_run.py` | Modify | Relabel form fields, add cascading dropdown logic |
| `tests/test_shop_analysis.py` | Modify | Update tests for Shop selector field |

---

### Task 1: Add industry_code to Workspace model

**Files:**
- Modify: `app/data/models.py:82-90`
- Modify: `app/data/session.py`

- [ ] **Step 1: Add field to Workspace model**

```python
# In app/data/models.py, add after line 87 (config field):
class Workspace(Base):
    __tablename__ = "workspace"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    config: Mapped[dict] = mapped_column(json_type(), default=dict)
    industry_code: Mapped[str] = mapped_column(String(128), default="general")  # NEW
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    projects: Mapped[list["Project"]] = relationship(back_populates="workspace")
```

- [ ] **Step 2: Add migration in session.py**

Add to the `_run_migrations` function in `app/data/session.py`:

```python
_add_column_if_missing(target_engine, "workspace", "industry_code", "ALTER TABLE workspace ADD COLUMN industry_code VARCHAR(128) DEFAULT 'general'")
```

- [ ] **Step 3: Verify model loads**

```bash
uv run python -c "from app.data.models import Workspace; print(hasattr(Workspace, 'industry_code'))"
```
Expected: `True`

- [ ] **Step 4: Commit**

```bash
git add app/data/models.py app/data/session.py
git commit -m "feat: add industry_code to Workspace model"
```

---

### Task 2: Add Shop/Category list API endpoints

**Files:**
- Modify: `app/schemas/api.py` — add list schemas
- Modify: `app/api/routes.py` — add GET endpoints

- [ ] **Step 1: Add schemas to api.py**

```python
# Append to app/schemas/api.py


class ShopItem(BaseModel):
    name: str
    industry_code: str = "general"


class ShopListResponse(BaseModel):
    shops: list[ShopItem]


class CategoryItem(BaseModel):
    name: str


class CategoryListResponse(BaseModel):
    categories: list[CategoryItem]
```

- [ ] **Step 2: Add endpoints to routes.py**

Insert before the Shop Analysis section:

```python
# ── Shops & Categories ────────────────────────────────────────────

@router.get("/shops", response_model=ShopListResponse)
def list_shops(db: Session = Depends(get_db)) -> dict:
    from app.data.models import Workspace
    rows = db.scalars(select(Workspace).order_by(Workspace.name)).all()
    return {
        "shops": [
            {"name": r.name, "industry_code": r.industry_code or "general"}
            for r in rows
        ]
    }


@router.get("/shops/{shop_name}/categories", response_model=CategoryListResponse)
def list_shop_categories(shop_name: str, db: Session = Depends(get_db)) -> dict:
    from app.data.models import Project, Workspace
    workspace = db.scalar(select(Workspace).where(Workspace.name == shop_name))
    if not workspace:
        return {"categories": []}
    rows = db.scalars(
        select(Project.name).where(Project.workspace_id == workspace.id).order_by(Project.name)
    ).all()
    return {"categories": [{"name": r} for r in rows]}
```

- [ ] **Step 3: Verify endpoints**

```bash
uv run python -c "from app.main import create_app; app = create_app(); routes = [r.path for r in app.routes]; print('/shops' in str(routes), '/shops/{shop_name}/categories' in str(routes))"
```
Expected: `True True`

- [ ] **Step 4: Commit**

```bash
git add app/schemas/api.py app/api/routes.py
git commit -m "feat: add /shops and /shops/{name}/categories API endpoints"
```

---

### Task 3: Relabel Create Run form (Shop + cascading dropdowns)

**Files:**
- Modify: `app/dashboard/create_run.py` — HTML labels and JS

- [ ] **Step 1: Add Shop selector JS endpoints and cascading logic**

In `CREATE_RUN_JS`, add shop/category loading functions. Add after the existing init code in the `DOMContentLoaded` handler:

```javascript
// ── Shop & Product Category ──
let allShops = [];

async function loadShops() {
  try {
    const data = await fetch("/shops").then(r => r.json());
    allShops = data.shops || [];
    renderShopSelect();
  } catch (err) {
    console.error("Failed to load shops", err);
  }
}

function renderShopSelect() {
  const sel = document.getElementById("workspace_name");
  if (sel.tagName === "SELECT") {
    sel.innerHTML = '<option value="">-- choose or type new --</option>';
    allShops.forEach(s => {
      sel.innerHTML += `<option value="${s.name.replace(/"/g, '&quot;')}" data-industry="${s.industry_code || 'general'}">${s.name.replace(/</g, '&lt;')}</option>`;
    });
  }
}

function onShopChange() {
  const sel = document.getElementById("workspace_name");
  const selectedOption = sel.options[sel.selectedIndex];
  const industryCode = selectedOption?.dataset?.industry || "general";
  document.getElementById("industry_code").value = industryCode;
  // Load categories for selected shop
  const shopName = sel.value;
  if (shopName) loadCategories(shopName);
  else renderCategorySelect([]);
}

async function loadCategories(shopName) {
  try {
    const data = await fetch(`/shops/${encodeURIComponent(shopName)}/categories`).then(r => r.json());
    renderCategorySelect(data.categories || []);
  } catch (err) {
    console.error("Failed to load categories", err);
    renderCategorySelect([]);
  }
}

function renderCategorySelect(items) {
  const sel = document.getElementById("project_name");
  if (sel.tagName === "SELECT") {
    sel.innerHTML = '<option value="">-- choose or type new --</option>';
    items.forEach(c => {
      sel.innerHTML += `<option value="${c.name.replace(/"/g, '&quot;')}">${c.name.replace(/</g, '&lt;')}</option>`;
    });
  }
}
```

- [ ] **Step 2: Relabel HTML inputs in CREATE_RUN_HTML**

Replace the Workspace/Project row (lines 57-60) with select-based inputs:

```html
                    <div class="row">
                      <div>
                        <label>Shop</label>
                        <select id="workspace_name" onchange="onShopChange()">
                          <option value="">Loading...</option>
                        </select>
                      </div>
                      <div>
                        <label>Product Category</label>
                        <select id="project_name">
                          <option value="">-- choose or type new --</option>
                        </select>
                      </div>
                    </div>
```

Note: Keep the `id` attributes as `workspace_name` and `project_name` for backward compatibility with `collectFormConfig()` and submit logic. The JS that reads these values uses `document.getElementById(...).value` — this works whether it's an `<input>` or `<select>`. To support "type new" behavior, we'll make them editable selects or keep a hidden input fallback. For MVP simplicity, use `<input list="...">` with datalist:
- Actually, use `<input>` with `<datalist>` for the type-new-or-select pattern.

Better approach: Keep `<input>` elements but add `<datalist>` for autocomplete suggestions. This gives both selection and free-text entry:

```html
                    <div class="row">
                      <div>
                        <label>Shop</label>
                        <input id="workspace_name" list="shop-list" value="workspace_demo" onchange="onShopChange()" />
                        <datalist id="shop-list"></datalist>
                      </div>
                      <div>
                        <label>Product Category</label>
                        <input id="project_name" list="category-list" value="project_demo" />
                        <datalist id="category-list"></datalist>
                      </div>
                    </div>
```

- [ ] **Step 3: Update JS to populate datalists**

Replace the `renderShopSelect` function to populate a `<datalist>`:

```javascript
function renderShopList() {
  const datalist = document.getElementById("shop-list");
  datalist.innerHTML = allShops.map(s =>
    `<option value="${s.name.replace(/"/g, '&quot;')}" data-industry="${s.industry_code || 'general'}">${s.industry_code || 'general'}</option>`
  ).join("");
}

function renderCategoryList(items) {
  const datalist = document.getElementById("category-list");
  datalist.innerHTML = items.map(c =>
    `<option value="${c.name.replace(/"/g, '&quot;')}"></option>`
  ).join("");
}
```

- [ ] **Step 4: Wire onShopChange to fetch categories and set industry_code**

```javascript
function onShopChange() {
  const shopName = document.getElementById("workspace_name").value;
  // Find matching shop in cache to get industry_code
  const shop = allShops.find(s => s.name === shopName);
  if (shop) {
    document.getElementById("industry_code").value = shop.industry_code || "general";
  }
  if (shopName) loadCategories(shopName);
  else renderCategoryList([]);
}
```

- [ ] **Step 5: Call loadShops on DOMContentLoaded**

Add `loadShops();` to the existing init block in the `DOMContentLoaded` handler.

- [ ] **Step 6: Verify form renders**

```bash
uv run python -c "from app.dashboard.create_run import CREATE_RUN_HTML; print('Shop' in CREATE_RUN_HTML, 'Product Category' in CREATE_RUN_HTML)"
```
Expected: `True True`

- [ ] **Step 7: Commit**

```bash
git add app/dashboard/create_run.py
git commit -m "feat: relabel Create Run form to Shop/Product Category with cascading datalists"
```

---

### Task 4: Relabel dashboard layout and Data Source

**Files:**
- Modify: `app/dashboard/layout.py`

- [ ] **Step 1: Change Data Source label**

Rename "Data Source" label to reflect the Shop context:

```python
# In layout.py, find the data-source-block label (around line 718):
<label style="margin-bottom:0;white-space:nowrap;">Shop</label>
```

And update the select's style hint:
```python
<select id="data-source-select" onchange="switchDataSource()" style="width:auto;min-width:160px;font-size:12px;padding:5px 8px;"></select>
```

The "Data Source" concept is now implicitly "Shop" since the data source selector populates available workspace databases which map 1:1 to shops.

- [ ] **Step 2: Verify layout renders**

```bash
uv run python -c "from app.dashboard.layout import render_shell_top; html = render_shell_top(); print('Shop' in html)"
```
Expected: `True`

- [ ] **Step 3: Commit**

```bash
git add app/dashboard/layout.py
git commit -m "feat: relabel Data Source to Shop in dashboard layout"
```

---

### Task 5: Update Shop Analysis page with Shop selector

**Files:**
- Modify: `app/api/routes.py` — in `_shop_analysis_page_html()`

- [ ] **Step 1: Add Shop selector form row**

In the "New Analysis" form card, add a Shop selector before the Store URL input:

```html
            <div class="form-row" style="margin-bottom:10px;">
              <div>
                <label>Shop</label>
                <input id="shop-name" list="shop-analysis-list" placeholder="Select or type shop name" onchange="onShopAnalysisShopChange()" />
                <datalist id="shop-analysis-list"></datalist>
              </div>
              <div>
                <label>Industry Code</label>
                <input id="industry-code" value="general" placeholder="Auto-filled from shop" />
              </div>
            </div>
```

- [ ] **Step 2: Add JS to load shops and handle change**

```javascript
async function loadShopAnalysisShops() {
  try {
    const data = await api("/shops");
    const shops = data.shops || [];
    const datalist = document.getElementById("shop-analysis-list");
    datalist.innerHTML = shops.map(s =>
      '<option value="' + s.name.replace(/"/g, '&quot;') + '" data-industry="' + (s.industry_code || 'general') + '">'
    ).join("");
  } catch (err) { /* silently ignore */ }
}

function onShopAnalysisShopChange() {
  const shopName = document.getElementById("shop-name").value;
  // Find matching shop
  fetch("/shops").then(r => r.json()).then(data => {
    const shop = (data.shops || []).find(s => s.name === shopName);
    if (shop) {
      document.getElementById("industry-code").value = shop.industry_code || "general";
    }
  }).catch(() => {});
}
```

- [ ] **Step 3: Update runAnalysis() to send shop_name**

Modify `runAnalysis()` to include the shop name in the POST body:

```javascript
body: JSON.stringify({
  store_url: storeUrl,
  description: document.getElementById("store-description").value.trim(),
  industry_code: document.getElementById("industry-code").value.trim() || "general",
  workspace_name: document.getElementById("shop-name").value.trim() || "workspace_demo",
  project_name: document.getElementById("shop-name").value.trim() || "workspace_demo",
}),
```

- [ ] **Step 4: Call loadShopAnalysisShops on init**

Add `loadShopAnalysisShops();` to the `DOMContentLoaded` handler.

- [ ] **Step 5: Verify page loads**

```bash
uv run python -c "
from app.main import create_app
from fastapi.testclient import TestClient
c = TestClient(create_app())
r = c.get('/dashboard/shop-analysis')
print(r.status_code, 'shop-name' in r.text, 'shop-analysis-list' in r.text)
"
```
Expected: `200 True True`

- [ ] **Step 6: Commit**

```bash
git add app/api/routes.py
git commit -m "feat: add Shop selector to Shop Analysis page with auto industry_code"
```

---

### Task 6: Update Shop Analysis history to accept shop param

**Files:**
- Modify: `app/api/routes.py` — in `shop_analysis_history` endpoint

- [ ] **Step 1: Rewrite history endpoint to use workspace name for filtering**

The current endpoint already uses `workspace_name` and `project_name`. The Shop Analysis page now sends the shop name as `workspace_name`. Update the JS `loadHistory()` to accept an optional shop filter:

In the page JS, update `loadHistory()`:

```javascript
async function loadHistory() {
  try {
    const shopName = document.getElementById("shop-name").value.trim() || "workspace_demo";
    const data = await api("/shop-analysis/history?workspace_name=" + encodeURIComponent(shopName) + "&project_name=" + encodeURIComponent(shopName));
    // ... rest unchanged
```

This ensures history is filtered to the selected shop.

- [ ] **Step 2: Verify history loads with shop filter**

Already covered by existing tests — no new test needed.

- [ ] **Step 3: Commit**

```bash
git add app/api/routes.py
git commit -m "feat: filter Shop Analysis history by selected shop"
```

---

### Task 7: Write tests

**Files:**
- Modify: `tests/test_shop_analysis.py`
- Create: `tests/test_shop_workspace.py`

- [ ] **Step 1: Add tests for shops/categories endpoints**

Create `tests/test_shop_workspace.py`:

```python
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
```

- [ ] **Step 2: Update existing shop_analysis test**

The `test_v2_page_loads_with_three_mode_rows` test checks for "Shop Analysis" in the HTML — this still passes. No changes needed.

- [ ] **Step 3: Run all tests**

```bash
uv run pytest tests/test_shop_workspace.py tests/test_shop_analysis.py -v --tb=short
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_shop_workspace.py
git commit -m "test: add Shop/Workspace API and UI tests"
```

---

### Task 8: Final integration and verification

- [ ] **Step 1: Verify app starts**

```bash
uv run python -c "from app.main import create_app; app = create_app(); print('App OK, routes:', len(app.routes))"
```

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest tests/ -v --tb=short
```

- [ ] **Step 3: Manual QA checklist**

```
[ ] Create Run form: "Shop" label, "Product Category" label visible
[ ] Shop input has datalist suggestions from /shops endpoint
[ ] Selecting a shop auto-fills industry_code
[ ] Selecting a shop loads categories into datalist
[ ] Shop Analysis page: Shop selector visible above store URL
[ ] Selecting a shop on Shop Analysis page auto-fills industry_code
[ ] Dashboard: Data Source / Runs section shows "Shop" label
[ ] Existing runs still display correctly (backward compat)
[ ] Submitting a run with old workspace_name/project_name values still works
```

- [ ] **Step 4: Final commit (if any fixes)**

```bash
git add -A
git commit -m "feat: complete Shop/Product Category rename with cascading selectors"
```
