# app/dashboard/create_run.py

from __future__ import annotations


CREATE_RUN_HTML = """
            <!-- Template Bar -->
            <div class="template-bar" id="template-bar">
              <span style="font-weight:600;font-size:12px;">Run Template:</span>
              <select id="template-selector" onchange="loadTemplate()" style="font-size:12px;padding:6px 8px;">
                <option value="">-- choose --</option>
              </select>
              <button onclick="applyTemplate()" style="font-size:12px;padding:6px 10px;">Apply</button>
              <button onclick="saveAsTemplate()" style="font-size:12px;padding:6px 10px;">Save</button>
              <button onclick="renameTemplate()" id="btn-rename-tpl" disabled style="font-size:12px;padding:6px 10px;">Rename</button>
              <button onclick="deleteTemplate()" id="btn-delete-tpl" disabled style="font-size:12px;padding:6px 10px;color:var(--danger);">Delete</button>
            </div>

            <!-- Mode Toggle -->
            <div class="action-row" style="margin-bottom:12px;justify-content:flex-end;">
              <span style="font-size:12px;color:var(--muted);">Mode:</span>
              <button class="tab-btn active" id="mode-guided" onclick="switchMode('guided')">Guided</button>
              <button class="tab-btn" id="mode-expert" onclick="switchMode('expert')">Expert</button>
            </div>

            <!-- Wizard Sidebar + Accordion Container -->
            <div style="display:flex;gap:16px;">
              <div class="wizard-sidebar" id="wizard-sidebar" style="display:flex;flex-direction:column;gap:4px;">
                <div class="wizard-step active" data-step="1" onclick="goToStep(1)"><span class="step-badge">1</span> Product & Assets</div>
                <div class="wizard-step pending" data-step="2" onclick="goToStep(2)"><span class="step-badge">2</span> Platform & Creative</div>
                <div class="wizard-step pending" data-step="3" onclick="goToStep(3)"><span class="step-badge">3</span> Campaign & Targeting</div>
                <div class="wizard-step pending" data-step="4" onclick="goToStep(4)"><span class="step-badge">4</span> Research & Context</div>
              </div>

              <div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:10px;">

                <!-- Section 1: Product & Assets -->
                <div class="accordion" data-section="1">
                  <div class="accordion-header open" onclick="toggleSection(this)">
                    <span>1. Product & Assets</span>
                    <span class="chevron">&#x25b8;</span>
                  </div>
                  <div class="accordion-body open">
                    <div class="file-drop-zone" id="file-drop-zone" ondragover="event.preventDefault()" ondrop="handleDrop(event)">
                      <div style="font-size:22px;margin-bottom:4px;">&#128247;</div>
                      <div style="font-weight:600;font-size:13px;">Drop product images & videos here</div>
                      <div class="hint muted">PNG, JPG, WebP, MP4, MOV &middot; Max 10 files &middot; 50MB each</div>
                      <input id="input_files" type="file" multiple accept=".csv,.xlsx,.png,.jpg,.jpeg,.webp,.mp4,.mov,.m4v" style="display:none;" onchange="refreshFilePreviews()" />
                      <button onclick="document.getElementById('input_files').click(); return false;" style="margin-top:8px;">Browse Files</button>
                    </div>
                    <div class="file-preview-grid" id="file-preview-grid"></div>
                    <div class="row" style="margin-top:10px;">
                      <div><label>Product Code (required)</label><input id="product_code" value="" placeholder="e.g. PRD-001" required onblur="checkProductHint()" /></div>
                      <div><label>Product Name</label><input id="product_name" value="" placeholder="Enter product name" /></div>
                    </div>
                    <div id="product-hint" class="hint" style="display:none;"></div>
                    <div class="row">
                      <div>
                        <label>Shop</label>
                        <select id="workspace_name" onchange="onShopChange()">
                          <option value="">Loading...</option>
                        </select>
                      </div>
                      <div>
                        <label>Product Category</label>
                        <input id="project_name" list="category-list" value="" placeholder="e.g. summer-collection" />
                        <datalist id="category-list"></datalist>
                      </div>
                    </div>
                    <div class="row">
                      <div><label>Campaign</label><input id="campaign_name" value="" placeholder="e.g. spring-launch" /></div>
                      <div><label>Industry Code (required)</label><input id="industry_code" value="general_merchandise" required /></div>
                    </div>
                    <div class="action-row" style="justify-content:flex-end;margin-top:8px;">
                      <button class="primary" onclick="nextStep(1)">Next &#8594;</button>
                    </div>
                  </div>
                </div>

                <!-- Section 2: Platform & Creative -->
                <div class="accordion" data-section="2">
                  <div class="accordion-header" onclick="toggleSection(this)">
                    <span>2. Platform & Creative</span>
                    <span class="chevron">&#x25b8;</span>
                  </div>
                  <div class="accordion-body">
                    <div class="row">
                      <div><label>Pipeline Mode</label><select id="pipeline_mode" onchange="refreshPipelineFields()"></select></div>
                      <div><label>Approval Mode</label><select id="approval_mode"><option value="manual" selected>Manual</option><option value="semi_auto">Semi-Auto</option><option value="full_auto">Full-Auto</option></select></div>
                    </div>
                    <div class="row">
                      <div><label>Variant Count</label><input id="variant_count" type="number" min="1" max="16" value="8" /></div>
                      <div>
                        <label>Channel</label>
                        <select id="channel">
                          <option value="meta" selected>Meta Ads</option>
                          <option value="tiktok">TikTok</option>
                          <option value="youtube">YouTube</option>
                          <option value="amazon">Amazon</option>
                          <option value="shopify">Shopify</option>
                          <option value="other">Other</option>
                        </select>
                      </div>
                    </div>
                    <div class="hint muted">Channel is passed to campaign context for agent strategy and creative recommendations.</div>
                    <div id="mode-summary" class="hint muted">Loading pipeline modes...</div>

                    <!-- Creative Specs -->
                    <div style="margin-top:8px;">
                      <div class="quick-fill-bar">
                        <span style="font-weight:600;font-size:13px;">Creative Specs Preset</span>
                        <select id="quick-fill-preset" onchange="applyQuickFill()" style="width:auto;min-width:200px;">
                          <option value="">Choose specs preset...</option>
                        </select>
                        <button onclick="saveCurrentAsCreativePreset()" title="Save as preset">+ Save</button>
                        <button onclick="manageCreativePresets()" title="Manage presets">&#9881;</button>
                      </div>
                      <div class="spec-row">
                        <div class="spec-field" id="field-image-size">
                          <label>Image Size</label>
                          <select id="image_size">
                            <option value="1:1" selected>1:1</option>
                            <option value="16:9">16:9</option>
                            <option value="9:16">9:16</option>
                            <option value="4:3">4:3</option>
                            <option value="3:4">3:4</option>
                            <option value="3:2">3:2</option>
                            <option value="2:3">2:3</option>
                            <option value="5:4">5:4</option>
                            <option value="4:5">4:5</option>
                            <option value="2:1">2:1</option>
                            <option value="1:2">1:2</option>
                            <option value="21:9">21:9</option>
                            <option value="9:21">9:21</option>
                          </select>
                        </div>
                        <div class="spec-field" id="field-video-size">
                          <label>Video Size</label>
                          <select id="video_size">
                            <option value="16:9">16:9</option>
                            <option value="9:16">9:16</option>
                            <option value="1:1" selected>1:1</option>
                            <option value="4:3">4:3</option>
                            <option value="3:4">3:4</option>
                            <option value="21:9">21:9</option>
                            <option value="adaptive">adaptive</option>
                          </select>
                        </div>
                        <div class="spec-field">
                          <label>Resolution</label>
                          <select id="resolution">
                            <option value="480p">480p</option>
                            <option value="720p" selected>720p</option>
                            <option value="1080p">1080p</option>
                            <option value="1600px">1600px</option>
                            <option value="2000px">2000px</option>
                          </select>
                        </div>
                        <div class="spec-field" id="field-video-duration">
                          <label>Duration (s)</label>
                          <input id="video_duration_seconds" type="number" min="4" max="15" value="5" />
                          <div class="hint muted">4-15 seconds for Seedance-compatible video runs.</div>
                        </div>
                        <div class="spec-field" id="field-dtc-site-surface" style="display:none;">
                          <label>DTC Site Surface</label>
                          <select id="dtc_site_surface">
                            <option value="pdp_primary" selected>PDP Primary</option>
                            <option value="homepage_hero">Homepage Hero</option>
                          </select>
                        </div>
                        <div class="spec-field" id="field-tiktok-video-style" style="display:none;">
                          <label>TikTok Video Style</label>
                          <select id="tiktok_video_style">
                            <option value="ugc_demo" selected>UGC Demo</option>
                            <option value="direct_response_ad">Direct Response Ad</option>
                            <option value="shop_account_content">Shop Account Content</option>
                          </select>
                        </div>
                      </div>
                      <div class="spec-row">
                        <div class="spec-field" id="field-image-reference-urls">
                          <label>Image Reference URLs</label>
                          <textarea id="image_reference_urls" rows="3" placeholder="https://example.com/ref-a.png&#10;data:image/png;base64,..."></textarea>
                          <div class="hint muted">Up to 16 reference images for GPT-Image-2. One per line.</div>
                        </div>
                        <div class="spec-field" id="field-image-official-fallback">
                          <label>Image Official Fallback</label>
                          <label style="display:flex;align-items:center;gap:8px;margin-top:8px;">
                            <input id="image_official_fallback" type="checkbox" />
                            <span>Allow apimart official fallback for GPT-Image-2.</span>
                          </label>
                        </div>
                      </div>
                      <div id="field-video-advanced" style="display:none;margin-top:8px;">
                        <div class="spec-row">
                          <div class="spec-field">
                            <label>Video Audio Options</label>
                            <label style="display:flex;align-items:center;gap:8px;margin-top:8px;"><input id="generate_audio" type="checkbox" /> <span>Generate audio</span></label>
                            <label style="display:flex;align-items:center;gap:8px;margin-top:8px;"><input id="return_last_frame" type="checkbox" /> <span>Return last frame</span></label>
                          </div>
                          <div class="spec-field">
                            <label>Seed</label>
                            <input id="seed" type="number" step="1" placeholder="Optional integer seed" />
                          </div>
                        </div>
                        <div class="spec-row">
                          <div class="spec-field">
                            <label>Video Image URLs</label>
                            <textarea id="video_image_reference_urls" rows="3" placeholder="https://example.com/frame-a.png"></textarea>
                            <div class="hint muted">Up to 9 reference images. Cannot be combined with first/last frame mode.</div>
                          </div>
                          <div class="spec-field">
                            <label>First Frame URL</label>
                            <input id="video_first_frame_url" type="url" placeholder="https://example.com/first-frame.png" />
                            <label style="margin-top:8px;">Last Frame URL</label>
                            <input id="video_last_frame_url" type="url" placeholder="https://example.com/last-frame.png" />
                          </div>
                        </div>
                        <div class="spec-row">
                          <div class="spec-field">
                            <label>Reference Video URLs</label>
                            <textarea id="video_reference_urls" rows="2" placeholder="https://example.com/reference.mp4"></textarea>
                            <div class="hint muted">Up to 3 videos. Not allowed with first/last frame mode.</div>
                          </div>
                          <div class="spec-field">
                            <label>Reference Audio URLs</label>
                            <textarea id="audio_reference_urls" rows="2" placeholder="https://example.com/reference.wav"></textarea>
                            <div class="hint muted">Up to 3 audio URLs. First/last frame mode cannot be combined with video or audio references.</div>
                          </div>
                        </div>
                      </div>
                      <div id="marketplace-fields" style="display:none;margin-top:6px;">
                        <label>Marketplace Targets</label>
                        <div class="action-row" style="gap:6px;flex-wrap:wrap;">
                          <label style="display:flex;align-items:center;gap:4px;font-weight:600;font-size:12px;"><input id="platform_tiktok_shop" type="checkbox" checked /> TikTok Shop</label>
                          <label style="display:flex;align-items:center;gap:4px;font-weight:600;font-size:12px;"><input id="platform_shopify" type="checkbox" checked /> Shopify</label>
                          <label style="display:flex;align-items:center;gap:4px;font-weight:600;font-size:12px;"><input id="platform_alibaba" type="checkbox" checked /> Alibaba</label>
                          <label style="display:flex;align-items:center;gap:4px;font-weight:600;font-size:12px;"><input id="platform_amazon" type="checkbox" checked /> Amazon</label>
                        </div>
                      </div>
                    </div>

                    <div class="action-row" style="justify-content:space-between;margin-top:8px;">
                      <button onclick="prevStep(2)">&#8592; Back</button>
                      <button class="primary" onclick="nextStep(2)">Next &#8594;</button>
                    </div>
                  </div>
                </div>

                <!-- Section 3: Campaign & Targeting -->
                <div class="accordion" data-section="3">
                  <div class="accordion-header" onclick="toggleSection(this)">
                    <span>3. Campaign & Targeting</span>
                    <span class="chevron">&#x25b8;</span>
                  </div>
                  <div class="accordion-body">
                    <div class="row">
                      <div><label>Objective</label><input id="objective" value="conversions" /></div>
                      <div></div>
                    </div>
                    <label>Product Description</label>
                    <textarea id="product_description" rows="3" placeholder="What is the product, who uses it, and why it matters."></textarea>
                    <div class="row">
                      <div><label>Target Audience</label><input id="target_audience" value="" placeholder="e.g. young professionals in urban areas" /></div>
                      <div><label>Price Range</label><input id="price_range" placeholder="$19.99 - $29.99" /></div>
                    </div>
                    <label>Key Value Props (comma separated)</label>
                    <input id="key_value_props" value="" placeholder="e.g. lightweight, waterproof, ergonomic" />
                    <div class="row">
                      <div><label>Primary CTA</label><input id="primary_cta" value="Shop Now" /></div>
                      <div><label>Campaign Goal</label><input id="campaign_goal" value="purchase" /></div>
                    </div>
                    <label>Category Tags (comma separated)</label>
                    <input id="category_tags" value="" placeholder="e.g. electronics, headphones" />
                    <div class="action-row" style="justify-content:space-between;margin-top:8px;">
                      <button onclick="prevStep(3)">&#8592; Back</button>
                      <button class="primary" onclick="nextStep(3)">Next &#8594;</button>
                    </div>
                  </div>
                </div>

                <!-- Section 4: Research & Context -->
                <div class="accordion" data-section="4">
                  <div class="accordion-header" onclick="toggleSection(this)">
                    <span>4. Research & Context</span>
                    <span class="chevron">&#x25b8;</span>
                  </div>
                  <div class="accordion-body">
                    <label>Research Source</label>
                    <select id="research_mode" onchange="refreshResearchHint()">
                      <option value="manual_validated" selected>Use my validated research (Default)</option>
                      <option value="autonomous_web">Run autonomous web research</option>
                    </select>
                    <div id="research-hint" class="hint muted"></div>
                    <label>Validated Research Notes (optional)</label>
                    <textarea id="manual_research_brief" rows="3" placeholder="Paste your manually validated market notes..."></textarea>
                    <label>Reference URLs (one per line)</label>
                    <textarea id="url_references" rows="2" placeholder="https://example.com/product"></textarea>
                    <label>Advanced Business Context JSON (optional)</label>
                    <textarea id="business_context_extra" rows="3" placeholder='{"landing_page_angle":"premium utility","seasonality":"spring"}'></textarea>
                    <div class="action-row" style="justify-content:space-between;margin-top:8px;">
                      <button onclick="prevStep(4)">&#8592; Back</button>
                      <button class="primary" onclick="submitCreateRun()">Create Run</button>
                    </div>
                  </div>
                </div>

              </div>
            </div>
"""

# JavaScript for the Create Run form
CREATE_RUN_JS = """
<script>
  // -- Drawer --
  function toggleFabCreate() {
    const panel = document.getElementById('drawer-panel');
    if (panel.classList.contains('open')) { closeDrawer(); }
    else { openDrawer(); }
  }
  function openDrawer() {
    document.getElementById('drawer-overlay').classList.add('open');
    document.getElementById('drawer-panel').classList.add('open');
    document.getElementById('fab-icon-swap').setAttribute('data-state', 'b');
  }
  function closeDrawer() {
    document.getElementById('drawer-overlay').classList.remove('open');
    document.getElementById('drawer-panel').classList.remove('open');
    document.getElementById('fab-icon-swap').setAttribute('data-state', 'a');
  }

  // -- State --
  let currentMode = localStorage.getItem('crispy_create_mode') || 'guided';
  let currentStep = 1;
  let lastProductConfig = null;

  // -- Mode Switching --
  function switchMode(mode) {
    currentMode = mode;
    localStorage.setItem('crispy_create_mode', mode);
    document.getElementById('mode-guided').classList.toggle('active', mode === 'guided');
    document.getElementById('mode-expert').classList.toggle('active', mode === 'expert');
    document.getElementById('wizard-sidebar').style.display = mode === 'guided' ? 'flex' : 'none';
    if (mode === 'expert') {
      document.querySelectorAll('.accordion-body').forEach(b => b.classList.add('open'));
      document.querySelectorAll('.accordion-header').forEach(h => h.classList.add('open'));
    } else {
      document.querySelectorAll('.accordion-body').forEach(b => b.classList.remove('open'));
      document.querySelectorAll('.accordion-header').forEach(h => h.classList.remove('open'));
      document.querySelector('[data-section="1"] .accordion-body').classList.add('open');
      document.querySelector('[data-section="1"] .accordion-header').classList.add('open');
      updateWizardSteps(1);
    }
  }

  // -- Accordion --
  function toggleSection(header) {
    if (currentMode === 'guided') return; // no manual toggle in guided mode
    const body = header.nextElementSibling;
    const isOpen = body.classList.contains('open');
    if (isOpen) { body.classList.remove('open'); header.classList.remove('open'); }
    else { body.classList.add('open'); header.classList.add('open'); }
  }

  // -- Wizard Navigation --
  function updateWizardSteps(step) {
    currentStep = step;
    document.querySelectorAll('.wizard-step').forEach(el => {
      const s = parseInt(el.dataset.step);
      el.classList.remove('active', 'done', 'pending');
      if (s === step) el.classList.add('active');
      else if (s < step) el.classList.add('done');
      else el.classList.add('pending');
    });
    // open target section, close others
    document.querySelectorAll('.accordion-body').forEach((b, i) => {
      const isTarget = (i + 1) === step;
      b.classList.toggle('open', isTarget);
      b.previousElementSibling.classList.toggle('open', isTarget);
    });
  }

  function goToStep(step) { if (currentMode === 'guided') updateWizardSteps(step); }
  function nextStep(from) { if (currentMode === 'guided') updateWizardSteps(Math.min(from + 1, 4)); }
  function prevStep(from) { if (currentMode === 'guided') updateWizardSteps(Math.max(from - 1, 1)); }

  // -- Pipeline-Creative Coupling --
  const PIPELINE_FIELD_MAP = {
    'full_multimodal': ['field-image-size', 'field-image-reference-urls', 'field-image-official-fallback', 'field-video-size', 'field-video-duration', 'field-video-advanced'],
    'video_only': ['field-video-size', 'field-video-duration', 'field-video-advanced'],
    'copy_image_only': ['field-image-size', 'field-image-reference-urls', 'field-image-official-fallback'],
    'dtc_site_image': ['field-image-size', 'field-image-reference-urls', 'field-image-official-fallback', 'field-dtc-site-surface'],
    'marketplace_main_image': ['field-image-size', 'field-image-reference-urls', 'field-image-official-fallback'],
    'tiktok_shop_video': ['field-video-size', 'field-video-duration', 'field-tiktok-video-style', 'field-video-advanced'],
  };

  const DTC_SITE_IMAGE_SPEC = {
    image_size: '4:5',
    video_size: '4:5',
    resolution: '1600px',
    video_duration_seconds: 5,
    site_surface: 'pdp_primary',
    dtcSite: true,
  };

  const MARKETPLACE_MAIN_IMAGE_SPEC = {
    image_size: '1:1',
    video_size: '1:1',
    resolution: '2000px',
    video_duration_seconds: 5,
    marketplace: true,
  };

  function refreshPipelineFields() {
    const mode = document.getElementById('pipeline_mode').value;
    const visible = PIPELINE_FIELD_MAP[mode] || [];
    ['field-image-size', 'field-image-reference-urls', 'field-image-official-fallback', 'field-video-size', 'field-video-duration', 'field-dtc-site-surface', 'field-tiktok-video-style', 'field-video-advanced'].forEach(id => {
      document.getElementById(id).style.display = visible.includes(id) ? 'block' : 'none';
    });
    if (mode === 'dtc_site_image') {
      applySpecs(DTC_SITE_IMAGE_SPEC);
      document.getElementById('channel').value = 'shopify';
      const quickFill = document.getElementById('quick-fill-preset');
      if (quickFill) quickFill.value = 'sys_dtc_site_image_pack';
      document.getElementById('marketplace-fields').style.display = 'none';
    } else if (mode === 'marketplace_main_image') {
      applySpecs(MARKETPLACE_MAIN_IMAGE_SPEC);
      const quickFill = document.getElementById('quick-fill-preset');
      if (quickFill) quickFill.value = 'sys_marketplace_main_image_pack';
    } else if (mode === 'tiktok_shop_video') {
      document.getElementById('channel').value = 'tiktok';
      document.getElementById('image_size').value = '9:16';
      document.getElementById('video_size').value = '9:16';
      document.getElementById('resolution').value = document.getElementById('resolution').value || '720p';
      document.getElementById('video_duration_seconds').value = '12';
      const quickFill = document.getElementById('quick-fill-preset');
      if (quickFill) quickFill.value = 'sys_tiktok_shop_conversion_12s';
      document.getElementById('marketplace-fields').style.display = 'none';
    } else {
      const quickFill = document.getElementById('quick-fill-preset');
      if (quickFill?.value === 'sys_dtc_site_image_pack') quickFill.value = '';
      if (quickFill?.value === 'sys_marketplace_main_image_pack') quickFill.value = '';
      if (quickFill?.value === 'sys_tiktok_shop_conversion_12s') quickFill.value = '';
      document.getElementById('marketplace-fields').style.display = 'none';
    }
    // also call shared refreshModeHint to update the mode summary text
    refreshModeSpecificConstraints();
    if (typeof refreshModeHint === 'function') refreshModeHint();
  }

  function refreshModeSpecificConstraints() {
    const mode = document.getElementById('pipeline_mode').value;
    const durationInput = document.getElementById('video_duration_seconds');
    const isVideoMode = ['full_multimodal', 'video_only', 'tiktok_shop_video'].includes(mode);
    durationInput.min = isVideoMode ? '4' : '1';
    durationInput.max = isVideoMode ? '15' : '60';
    if (isVideoMode) {
      const current = parseInt(durationInput.value || '0', 10);
      if (!Number.isFinite(current) || current < 4) durationInput.value = '4';
      if (current > 15) durationInput.value = '15';
    }
  }

  // -- Quick Fill Creative Specs --
  function buildQuickFillOptions() {
    const sel = document.getElementById('quick-fill-preset');
    sel.innerHTML = '<option value="">Choose specs preset...</option>';
    // Recent (auto) -- stored in localStorage
    const recent = JSON.parse(localStorage.getItem('crispy_recent_specs') || '[]');
    if (recent.length) {
      sel.appendChild(createOptgroup('Recent (auto)', recent.map((s, i) => ({
        value: 'recent_' + i,
        label: s.image_size + ' / ' + s.video_size + ' / ' + s.resolution + ' / ' + s.video_duration_seconds + 's',
        spec: s,
      }))));
    }
    // My Presets -- fetch from API
    fetch('/creative-presets?workspace_name=' + (document.getElementById('workspace_name').value || 'workspace_demo'))
      .then(r => r.json()).then(data => {
        if (data.user && data.user.length) {
          const group = createOptgroup('My Presets', data.user.map(p => ({
            value: 'user_' + p.id,
            label: p.name + ' \u00b7 ' + (p.image_size || '?') + ' / ' + (p.video_size || '?') + ' / ' + (p.resolution || '?') + ' / ' + (p.video_duration_seconds || '?') + 's',
            spec: { image_size: p.image_size, video_size: p.video_size, resolution: p.resolution, video_duration_seconds: p.video_duration_seconds, platform_targets: p.platform_targets },
          })));
          sel.appendChild(group);
        }
      });
    // System Defaults
    sel.appendChild(createOptgroup('System Defaults', [
      { value: 'sys_meta_square_5s', label: '1:1 Square 720p 5s', spec: { image_size: '1:1', video_size: '1:1', resolution: '720p', video_duration_seconds: 5 } },
      { value: 'sys_meta_vertical_5s', label: '9:16 Vertical 720p 5s', spec: { image_size: '9:16', video_size: '9:16', resolution: '720p', video_duration_seconds: 5 } },
      { value: 'sys_youtube_landscape_6s', label: '16:9 Landscape 1080p 6s', spec: { image_size: '16:9', video_size: '16:9', resolution: '1080p', video_duration_seconds: 6 } },
      { value: 'sys_dtc_site_image_pack', label: 'DTC Site Image · 4:5 1600px', spec: DTC_SITE_IMAGE_SPEC },
      { value: 'sys_marketplace_main_image_pack', label: 'Studio Main Image · 1:1 Marketplace 2000px', spec: MARKETPLACE_MAIN_IMAGE_SPEC },
      { value: 'sys_tiktok_shop_conversion_12s', label: 'TikTok Shop · 9:16 720p 12s', spec: { image_size: '9:16', video_size: '9:16', resolution: '720p', video_duration_seconds: 12, platform: 'tiktok', creative_goal: 'shop_conversion_video', tiktok_video_style: 'ugc_demo', platform_targets: ['tiktok', 'tiktok_shop'] } },
    ]));
  }

  function createOptgroup(label, items) {
    const g = document.createElement('optgroup');
    g.label = label;
    items.forEach(item => {
      const opt = document.createElement('option');
      opt.value = item.value;
      opt.textContent = item.label;
      opt._spec = item.spec;
      g.appendChild(opt);
    });
    return g;
  }

  function applyQuickFill() {
    const sel = document.getElementById('quick-fill-preset');
    const opt = sel.selectedOptions[0];
    if (!opt || !opt._spec) return;
    applySpecs(opt._spec);
    if (opt._spec.marketplace) {
      document.getElementById('pipeline_mode').value = 'marketplace_main_image';
      refreshPipelineFields();
    } else if (opt._spec.dtcSite) {
      document.getElementById('pipeline_mode').value = 'dtc_site_image';
      refreshPipelineFields();
    }
  }

  function applySpecs(s) {
    document.getElementById('image_size').value = s.image_size || '';
    document.getElementById('video_size').value = s.video_size || '';
    document.getElementById('resolution').value = s.resolution || '';
    document.getElementById('video_duration_seconds').value = s.video_duration_seconds || '';
    document.getElementById('dtc_site_surface').value = s.site_surface || 'pdp_primary';
    document.getElementById('marketplace-fields').style.display = s.marketplace ? 'block' : 'none';
  }

  function saveCurrentAsCreativePreset() {
    const name = prompt('Preset name:');
    if (!name) return;
    const payload = {
      name: name,
      workspace_name: document.getElementById('workspace_name').value || 'workspace_demo',
      image_size: document.getElementById('image_size').value,
      video_size: document.getElementById('video_size').value,
      resolution: document.getElementById('resolution').value,
      video_duration_seconds: parseInt(document.getElementById('video_duration_seconds').value) || 5,
    };
    fetch('/creative-presets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      .then(r => { if (!r.ok) return r.text().then(d => { throw new Error(d); }); return r.json(); })
      .then(() => { buildQuickFillOptions(); })
      .catch(e => alert('Error: ' + e.message));
  }

  function manageCreativePresets() {
    alert('Preset management panel coming. For now, use the API directly or delete/recreate.');
    buildQuickFillOptions();
  }

  // -- Product Code Hint --
  function checkProductHint() {
    const code = document.getElementById('product_code').value.trim();
    if (!code) return;
    fetch('/product-config-hint?product_code=' + encodeURIComponent(code))
      .then(r => r.json()).then(hint => {
        if (!hint) return;
        lastProductConfig = hint;
        const el = document.getElementById('product-hint');
        el.style.display = 'block';
        el.innerHTML = code + ' last used: <b>' + (hint.pipeline_mode || '?') + '</b>, '
          + (hint.creative_specs ? (hint.creative_specs.image_size || '?') + '/' + (hint.creative_specs.resolution || '?') + '/' + (hint.creative_specs.video_duration_seconds || '?') + 's' : '?')
          + ', ' + (hint.channel || '?') + '. '
          + '<button onclick="applyLastConfig()" style="font-size:11px;padding:4px 8px;">Apply</button> '
          + '<button onclick="document.getElementById(\\'product-hint\\').style.display=\\'none\\'" style="font-size:11px;padding:4px 8px;">Dismiss</button>';
      });
  }

  function applyLastConfig() {
    if (!lastProductConfig) return;
    document.getElementById('pipeline_mode').value = lastProductConfig.pipeline_mode || 'full_multimodal';
    document.getElementById('approval_mode').value = lastProductConfig.approval_mode || 'manual';
    document.getElementById('channel').value = lastProductConfig.channel || 'meta';
    document.getElementById('objective').value = lastProductConfig.objective || 'conversions';
    if (lastProductConfig.creative_specs) {
      document.getElementById('image_size').value = lastProductConfig.creative_specs.image_size || '';
      document.getElementById('video_size').value = lastProductConfig.creative_specs.video_size || '';
      document.getElementById('resolution').value = lastProductConfig.creative_specs.resolution || '';
      document.getElementById('video_duration_seconds').value = lastProductConfig.creative_specs.video_duration_seconds || '';
      if (lastProductConfig.creative_specs.tiktok_video_style) {
        document.getElementById('tiktok_video_style').value = lastProductConfig.creative_specs.tiktok_video_style;
      }
      document.getElementById('image_reference_urls').value = (lastProductConfig.creative_specs.reference_image_urls || []).join('\\n');
      document.getElementById('image_official_fallback').checked = !!lastProductConfig.creative_specs.official_fallback;
      document.getElementById('generate_audio').checked = !!lastProductConfig.creative_specs.generate_audio;
      document.getElementById('return_last_frame').checked = !!lastProductConfig.creative_specs.return_last_frame;
      document.getElementById('seed').value = lastProductConfig.creative_specs.seed || '';
      document.getElementById('video_image_reference_urls').value = (lastProductConfig.creative_specs.video_image_urls || []).join('\\n');
      const roles = lastProductConfig.creative_specs.image_with_roles || [];
      document.getElementById('video_first_frame_url').value = (roles.find(r => r.role === 'first_frame') || {}).url || '';
      document.getElementById('video_last_frame_url').value = (roles.find(r => r.role === 'last_frame') || {}).url || '';
      document.getElementById('video_reference_urls').value = (lastProductConfig.creative_specs.video_urls || []).join('\\n');
      document.getElementById('audio_reference_urls').value = (lastProductConfig.creative_specs.audio_urls || []).join('\\n');
    }
    refreshPipelineFields();
    document.getElementById('product-hint').style.display = 'none';
  }

  // -- Template CRUD --
  function loadTemplates() {
    const ws = document.getElementById('workspace_name').value || 'workspace_demo';
    fetch('/run-templates?workspace_name=' + encodeURIComponent(ws))
      .then(r => r.json()).then(templates => {
        const sel = document.getElementById('template-selector');
        sel.innerHTML = '<option value="">-- choose template --</option>';
        templates.forEach(t => {
          const opt = document.createElement('option');
          opt.value = t.id;
          opt.textContent = t.name;
          opt._config = t.config_json;
          sel.appendChild(opt);
        });
      });
  }

  function loadTemplate() {
    const sel = document.getElementById('template-selector');
    const opt = sel.selectedOptions[0];
    document.getElementById('btn-rename-tpl').disabled = !opt || !opt.value;
    document.getElementById('btn-delete-tpl').disabled = !opt || !opt.value;
  }

  function applyTemplate() {
    const sel = document.getElementById('template-selector');
    const opt = sel.selectedOptions[0];
    if (!opt || !opt._config) return;
    const cfg = opt._config;
    // Apply all fields from template config
    for (const [key, value] of Object.entries(cfg)) {
      const el = document.getElementById(key);
      if (el && el.type !== 'file') {
        if (el.type === 'checkbox') el.checked = !!value;
        else el.value = value;
      }
    }
    refreshPipelineFields();
    buildQuickFillOptions();
  }

  function saveAsTemplate() {
    const name = prompt('Template name:');
    if (!name) return;
    const config = collectFormConfig();
    fetch('/run-templates', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: name,
        workspace_name: document.getElementById('workspace_name').value || 'workspace_demo',
        config_json: config,
      }),
    })
      .then(r => { if (!r.ok) return r.text().then(d => { throw new Error(d); }); return r.json(); })
      .then(() => loadTemplates())
      .catch(e => alert('Error: ' + e.message));
  }

  function renameTemplate() {
    const sel = document.getElementById('template-selector');
    const id = sel.value;
    if (!id) return;
    const newName = prompt('New name:', sel.selectedOptions[0].textContent);
    if (!newName) return;
    fetch('/run-templates/' + id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: newName }) })
      .then(r => { if (!r.ok) return r.text().then(d => { throw new Error(d); }); return r.json(); })
      .then(() => loadTemplates())
      .catch(e => alert('Error: ' + e.message));
  }

  function deleteTemplate() {
    const sel = document.getElementById('template-selector');
    const id = sel.value;
    if (!id) return;
    if (!confirm('Delete template "' + sel.selectedOptions[0].textContent + '"?')) return;
    fetch('/run-templates/' + id, { method: 'DELETE' })
      .then(r => { if (!r.ok) return r.text().then(d => { throw new Error(d); }); loadTemplates(); })
      .catch(e => alert('Error: ' + e.message));
  }

  function collectFormConfig() {
    const fields = [
      'workspace_name', 'project_name', 'product_name', 'product_code', 'industry_code',
      'campaign_name', 'channel', 'objective', 'pipeline_mode', 'approval_mode',
      'variant_count', 'image_size', 'video_size', 'resolution', 'video_duration_seconds', 'tiktok_video_style',
      'image_reference_urls', 'image_official_fallback', 'generate_audio', 'return_last_frame', 'seed',
      'video_image_reference_urls', 'video_first_frame_url', 'video_last_frame_url', 'video_reference_urls', 'audio_reference_urls',
      'target_audience', 'price_range', 'key_value_props', 'primary_cta', 'campaign_goal',
      'category_tags', 'research_mode', 'manual_research_brief', 'url_references', 'business_context_extra',
    ];
    const config = {};
    fields.forEach(id => {
      const el = document.getElementById(id);
      if (el) config[id] = el.type === 'checkbox' ? el.checked : el.value;
    });
    return config;
  }

  // -- File Upload & Preview --
  function handleDrop(event) {
    event.preventDefault();
    const files = event.dataTransfer.files;
    document.getElementById('input_files').files = files;
    refreshFilePreviews();
  }

  function refreshFilePreviews() {
    const files = document.getElementById('input_files').files;
    const grid = document.getElementById('file-preview-grid');
    grid.innerHTML = '';
    for (let i = 0; i < Math.min(files.length, 10); i++) {
      const f = files[i];
      if (f.type.startsWith('image/')) {
        const img = document.createElement('img');
        img.src = URL.createObjectURL(f);
        img.className = 'file-preview-thumb';
        grid.appendChild(img);
      } else {
        const div = document.createElement('div');
        div.className = 'file-preview-thumb video';
        div.textContent = f.name.substring(0, 4);
        div.title = f.name;
        grid.appendChild(div);
      }
    }
  }

  // -- Form Submit --
  function parseLineSeparatedUrls(value) {
    return (value || '').split('\\n').map(v => v.trim()).filter(Boolean);
  }

  function buildImageWithRoles() {
    const rows = [];
    const first = document.getElementById('video_first_frame_url').value.trim();
    const last = document.getElementById('video_last_frame_url').value.trim();
    if (first) rows.push({ url: first, role: 'first_frame' });
    if (last) rows.push({ url: last, role: 'last_frame' });
    return rows;
  }

  function validateCreateRunForm() {
    const mode = document.getElementById('pipeline_mode').value;
    const isVideoMode = ['full_multimodal', 'video_only', 'tiktok_shop_video'].includes(mode);
    const duration = parseInt(document.getElementById('video_duration_seconds').value || '0', 10);
    const imageRefs = parseLineSeparatedUrls(document.getElementById('image_reference_urls').value);
    const videoImageRefs = parseLineSeparatedUrls(document.getElementById('video_image_reference_urls').value);
    const imageWithRoles = buildImageWithRoles();
    const videoRefs = parseLineSeparatedUrls(document.getElementById('video_reference_urls').value);
    const audioRefs = parseLineSeparatedUrls(document.getElementById('audio_reference_urls').value);

    if (imageRefs.length > 16) return 'Image Reference URLs supports at most 16 entries.';
    if (isVideoMode && (!Number.isFinite(duration) || duration < 4 || duration > 15)) {
      return 'Duration must stay within 4-15 seconds for Seedance-compatible video runs.';
    }
    if (videoImageRefs.length > 9) return 'Video Image URLs supports at most 9 entries.';
    if (videoRefs.length > 3) return 'Reference Video URLs supports at most 3 entries.';
    if (audioRefs.length > 3) return 'Reference Audio URLs supports at most 3 entries.';
    if (videoImageRefs.length && imageWithRoles.length) {
      return 'Video Image URLs cannot be combined with first/last frame mode.';
    }
    if (imageWithRoles.length && (videoRefs.length || audioRefs.length)) {
      return 'First/last frame mode cannot be combined with video or audio references.';
    }
    return '';
  }

  function buildCreativeSpecsJSON() {
    const imageSize = document.getElementById('image_size').value.trim();
    const videoSize = document.getElementById('video_size').value.trim();
    const resolution = document.getElementById('resolution').value.trim();
    const duration = parseInt(document.getElementById('video_duration_seconds').value) || 5;
    const spec = { image_size: imageSize, video_size: videoSize, resolution, video_duration_seconds: duration };
    const imageRefs = parseLineSeparatedUrls(document.getElementById('image_reference_urls').value);
    const videoImageRefs = parseLineSeparatedUrls(document.getElementById('video_image_reference_urls').value);
    const imageWithRoles = buildImageWithRoles();
    const videoRefs = parseLineSeparatedUrls(document.getElementById('video_reference_urls').value);
    const audioRefs = parseLineSeparatedUrls(document.getElementById('audio_reference_urls').value);
    const seedRaw = document.getElementById('seed').value.trim();
    if (imageRefs.length) spec.reference_image_urls = imageRefs;
    if (document.getElementById('image_official_fallback').checked) spec.official_fallback = true;
    const isMarketplace = document.getElementById('pipeline_mode').value === 'marketplace_main_image'
      || document.getElementById('marketplace-fields').style.display === 'block';
    if (isMarketplace) {
      spec.asset_goal = 'marketplace_main_image';
      spec.platform_targets = ['tiktok_shop', 'shopify', 'alibaba', 'amazon'].filter(p => document.getElementById('platform_' + p)?.checked);
      spec.export_size_px = 2000;
      spec.background_policy = 'pure_white';
    }
    if (document.getElementById('pipeline_mode').value === 'tiktok_shop_video') {
      spec.platform = 'tiktok';
      spec.creative_goal = 'shop_conversion_video';
      spec.tiktok_video_style = document.getElementById('tiktok_video_style').value || 'ugc_demo';
      spec.platform_targets = ['tiktok', 'tiktok_shop'];
    }
    if (['full_multimodal', 'video_only', 'tiktok_shop_video'].includes(document.getElementById('pipeline_mode').value)) {
      if (document.getElementById('generate_audio').checked) spec.generate_audio = true;
      if (document.getElementById('return_last_frame').checked) spec.return_last_frame = true;
      if (seedRaw) spec.seed = parseInt(seedRaw, 10);
      if (videoImageRefs.length) spec.video_image_urls = videoImageRefs;
      if (imageWithRoles.length) spec.image_with_roles = imageWithRoles;
      if (videoRefs.length) spec.video_urls = videoRefs;
      if (audioRefs.length) spec.audio_urls = audioRefs;
    }
    if (document.getElementById('pipeline_mode').value === 'dtc_site_image') {
      spec.asset_goal = 'dtc_site_image';
      spec.site_surface = document.getElementById('dtc_site_surface').value || 'pdp_primary';
      spec.platform_targets = ['shopify'];
    }
    return spec;
  }

  function escapeCreateRunHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function preflightRowsHtml(preflight) {
    const rows = ((preflight && preflight.checks) || []).filter(function(row) {
      return row.severity !== 'ok';
    });
    if (!rows.length) {
      return '<div>' + escapeCreateRunHtml((preflight && preflight.summary) || 'No compatibility risk detected.') + '</div>';
    }
    return '<ul style="margin:8px 0 0 18px;padding:0;">' + rows.map(function(row) {
      const scope = [row.stage_name, row.agent_name].filter(Boolean).join(' / ');
      return '<li style="margin-bottom:6px;">'
        + '<b>' + escapeCreateRunHtml(String(row.severity || '').toUpperCase()) + '</b> '
        + (scope ? '<span class="muted">' + escapeCreateRunHtml(scope) + ':</span> ' : '')
        + escapeCreateRunHtml(row.message || '')
        + '</li>';
    }).join('') + '</ul>';
  }

  function renderCreateRunMessage(kind, title, detailHtml) {
    const msg = document.getElementById('create-msg');
    const color = kind === 'error' ? 'var(--danger)' : kind === 'warn' ? 'var(--warning)' : 'var(--accent)';
    const bg = kind === 'error' ? 'var(--danger-light)' : kind === 'warn' ? 'var(--warning-light)' : '#ecfdf5';
    msg.className = 'status-msg';
    msg.style.color = color;
    msg.style.background = bg;
    msg.style.border = '1px solid ' + (kind === 'error' ? '#fecaca' : kind === 'warn' ? '#fde68a' : '#bbf7d0');
    msg.style.borderRadius = '8px';
    msg.style.padding = '10px 12px';
    msg.style.overflowWrap = 'anywhere';
    msg.style.lineHeight = '1.45';
    msg.innerHTML = '<div style="font-weight:700;">' + escapeCreateRunHtml(title) + '</div>' + (detailHtml || '');
  }

  function submitCreateRun() {
    const msg = document.getElementById('create-msg');
    msg.textContent = 'Creating run...';
    msg.className = 'status-msg';
    msg.removeAttribute('style');

    const validationError = validateCreateRunForm();
    if (validationError) {
      renderCreateRunMessage('error', validationError, '');
      return;
    }

    const creativeSpecs = buildCreativeSpecsJSON();

    // Track recent usage
    const recent = JSON.parse(localStorage.getItem('crispy_recent_specs') || '[]');
    recent.unshift(creativeSpecs);
    if (recent.length > 5) recent.length = 5;
    localStorage.setItem('crispy_recent_specs', JSON.stringify(recent));

    const fd = new FormData();
    fd.set('workspace_name', document.getElementById('workspace_name').value);
    fd.set('project_name', document.getElementById('project_name').value);
    fd.set('product_name', document.getElementById('product_name').value);
    fd.set('product_code', document.getElementById('product_code').value);
    fd.set('industry_code', document.getElementById('industry_code').value);
    fd.set('campaign_name', document.getElementById('campaign_name').value);
    fd.set('channel', document.getElementById('channel').value);
    fd.set('objective', document.getElementById('objective').value);
    fd.set('pipeline_mode', document.getElementById('pipeline_mode').value);
    fd.set('approval_mode', document.getElementById('approval_mode').value);
    fd.set('variant_count', document.getElementById('variant_count').value);
    const pipelineMode = document.getElementById('pipeline_mode').value;
    fd.set('creative_preset',
      pipelineMode === 'dtc_site_image'
        ? 'dtc_site_image_pack'
        : pipelineMode === 'marketplace_main_image'
          ? 'marketplace_main_image_pack'
          : pipelineMode === 'tiktok_shop_video'
            ? 'tiktok_shop_conversion_12s'
            : 'custom'
    );
    fd.set('creative_specs', JSON.stringify(creativeSpecs));
    fd.set('manual_research_brief', document.getElementById('manual_research_brief').value);
    fd.set('url_references', JSON.stringify(
      (document.getElementById('url_references').value || '').split('\\n').filter(Boolean)
    ));
    fd.set('business_context', JSON.stringify(
      (function() { try { return JSON.parse(document.getElementById('business_context_extra').value || '{}'); } catch(e) { return {}; } })()
    ));
    fd.set('category_tags', JSON.stringify(
      (document.getElementById('category_tags').value || '').split(',').map(function(s) { return s.trim(); }).filter(Boolean)
    ));
    fd.set('enable_research', document.getElementById('research_mode').value === 'autonomous_web' ? 'true' : 'false');

    const fileInput = document.getElementById('input_files');
    for (const f of fileInput.files) {
      fd.append('files', f);
    }

    fetch('/runs/rich', { method: 'POST', body: fd })
      .then(function(r) { return r.json().then(function(data) { return { status: r.status, data: data }; }); })
      .then(function(result) {
        if (result.status >= 400) {
          const detail = result.data.detail || {};
          if (detail.preflight) {
            renderCreateRunMessage(
              'error',
              'Run creation blocked by preflight checks.',
              '<div class="muted" style="margin-top:4px;">Fix the items below, then create the run again.</div>' + preflightRowsHtml(detail.preflight)
            );
          } else {
            renderCreateRunMessage('error', typeof detail === 'string' ? detail : 'Run creation failed.', '');
          }
          return;
        }
        // Show preflight warnings inline if any
        const pf = result.data._preflight;
        if (pf && pf.checks && pf.checks.some(function(c) { return c.severity !== 'ok'; })) {
          renderCreateRunMessage(
            pf.severity === 'error' ? 'error' : 'warn',
            'Run created with preflight notes: ' + result.data.id,
            preflightRowsHtml(pf)
          );
        } else {
          renderCreateRunMessage('ok', 'Run created: ' + result.data.id, '');
        }
        setTimeout(closeDrawer, 1400);
        if (typeof refreshRuns === 'function') refreshRuns();
      })
      .catch(function(err) {
        renderCreateRunMessage('error', 'Run creation failed.', '<div>' + escapeCreateRunHtml(err.message) + '</div>');
      });
  }

          // ── Shop & Product Category ──
          let allShops = [];

          async function loadShops() {
            try {
              const data = await fetch("/shops").then(r => r.json());
              allShops = data.shops || [];
              const sel = document.getElementById("workspace_name");
              sel.innerHTML = allShops.map(s =>
                '<option value="' + s.name.replace(/"/g, '&quot;') + '" data-industry="' + (s.industry_code || 'general') + '">' + s.name.replace(/</g, '&lt;') + '</option>'
              ).join("");
              if (allShops.length > 0) {
                sel.value = allShops[0].name;
                onShopChange();
              }
            } catch (err) {
              console.error("Failed to load shops", err);
            }
          }

          function onShopChange() {
            const sel = document.getElementById("workspace_name");
            const shopName = sel.value;
            const selectedOpt = sel.options[sel.selectedIndex];
            if (selectedOpt && selectedOpt.dataset.industry) {
              document.getElementById("industry_code").value = selectedOpt.dataset.industry;
            }
            const shop = allShops.find(s => s.name === shopName);
            if (shop) {
              document.getElementById("industry_code").value = shop.industry_code || "general";
            }
            if (shopName) loadCategories(shopName);
            else {
              document.getElementById("category-list").innerHTML = "";
            }
          }

          async function loadCategories(shopName) {
            try {
              const data = await fetch("/shops/" + encodeURIComponent(shopName) + "/categories").then(r => r.json());
              const datalist = document.getElementById("category-list");
              datalist.innerHTML = (data.categories || []).map(c =>
                '<option value="' + c.name.replace(/"/g, '&quot;') + '"></option>'
              ).join("");
            } catch (err) {
              console.error("Failed to load categories", err);
            }
          }

  // -- Init --
  document.addEventListener('DOMContentLoaded', function() {
    switchMode(currentMode);
    buildQuickFillOptions();
    loadTemplates();
    loadShops();
    // loadPipelineModes, refreshResearchHint, data source loading, and polling
    // are handled by the shared JS init which runs immediately on page load
    refreshResearchHint();
  });
</script>
"""
