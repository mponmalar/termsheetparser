/* Term Sheet Parser — sales review UI (vanilla JS, no build step). */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const api = async (path, opts = {}) => {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail || `${resp.status} ${resp.statusText}`);
  }
  return resp.json();
};

const state = { docs: [], activeDocId: null, doc: null, dirty: {}, notice: null };

const FIELD_GROUPS = [
  ["Identification", ["product_type", "issuer", "counterparty", "isin"]],
  ["Dates", ["trade_date", "initial_fixing_date", "issue_date", "final_fixing_date", "maturity_date"]],
  ["Economics", ["notional_amount", "notional_currency", "denomination", "coupon_rate_pa", "coupon_frequency", "strike_pct"]],
  ["Underlyings", ["basket_type", "underlyings"]],
  ["Barriers & autocall", ["knock_in_barrier_pct", "knock_in_observation", "knock_out_barrier_pct", "knock_out_observation", "autocall", "first_autocall_date"]],
  ["Settlement & legal", ["settlement_type", "settlement_currency", "business_day_convention", "calculation_agent", "governing_law"]],
];

/* ------------------------------------------------------------------ stats */
async function loadStats() {
  const s = await api("/api/stats");
  $("#statbar").innerHTML = `
    <div class="stat"><b>${s.documents}</b><span>term sheets</span></div>
    <div class="stat"><b>${s.extractions}</b><span>extractions</span></div>
    <div class="stat"><b>${s.active_lessons}</b><span>lessons learned</span></div>
    <div class="stat"><b>${s.field_accuracy_pct ?? "—"}${s.field_accuracy_pct != null ? "%" : ""}</b><span>field accuracy</span></div>
    <div class="stat"><b class="mode-${s.llm_mode}">${s.llm_mode.toUpperCase()}</b><span>LLM mode</span></div>`;
}

/* ---------------------------------------------------------------- blotter */
async function loadDocs() {
  state.docs = await api("/api/documents");
  const ul = $("#doc-list");
  ul.innerHTML = state.docs.length ? "" : `<li class="upload-hint">Nothing yet — upload a term sheet above.</li>`;
  for (const d of state.docs) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.className = "doc-item" + (d.id === state.activeDocId ? " active" : "");
    btn.innerHTML = `<span class="doc-name">${escapeHtml(d.filename)}</span>
                     <span class="pill pill-${d.status}">${d.status.replace("_", " ")}</span>`;
    btn.onclick = () => openDoc(d.id);
    li.appendChild(btn);
    ul.appendChild(li);
  }
}

async function loadLessons() {
  const lessons = await api("/api/lessons");
  const ul = $("#lesson-list");
  const active = lessons.filter(l => !l.superseded).slice(0, 8);
  ul.innerHTML = active.length ? "" :
    `<li class="upload-hint">No lessons yet. When sales corrects a field, the agents remember it here.</li>`;
  for (const l of active) {
    const li = document.createElement("li");
    li.className = "lesson-item";
    li.innerHTML = `<span class="lesson-field">${escapeHtml(l.field_name || "general")}</span>
      <div class="lesson-values"><span class="lesson-wrong">${escapeHtml(trunc(l.wrong_value, 34))}</span>
      → <span class="lesson-right">${escapeHtml(trunc(l.right_value, 34))}</span></div>
      <div class="lesson-meta">applied ${l.times_applied}× · ${l.source}</div>`;
    ul.appendChild(li);
  }
}

/* ----------------------------------------------------------------- upload */
function wireUpload() {
  const zone = $("#dropzone"), input = $("#file-input");
  $("#browse-btn").onclick = () => input.click();
  input.onchange = () => input.files.length && upload(input.files[0]);
  ["dragover", "dragenter"].forEach(ev => zone.addEventListener(ev, e => {
    e.preventDefault(); zone.classList.add("dragover");
  }));
  ["dragleave", "drop"].forEach(ev => zone.addEventListener(ev, e => {
    e.preventDefault(); zone.classList.remove("dragover");
  }));
  zone.addEventListener("drop", e => {
    const f = e.dataTransfer.files[0];
    if (f) upload(f);
  });
}

async function upload(file) {
  const status = $("#upload-status");
  status.textContent = `Uploading ${file.name}…`;
  const form = new FormData();
  form.append("file", file);
  try {
    const resp = await fetch("/api/documents", { method: "POST", body: form });
    if (!resp.ok) throw new Error((await resp.json()).detail || resp.statusText);
    const { document_id } = await resp.json();
    status.textContent = "Agents are parsing the term sheet…";
    await pollUntilDone(document_id, status);
  } catch (err) {
    status.textContent = `Upload failed: ${err.message}`;
  }
}

async function pollUntilDone(docId, statusEl) {
  for (let i = 0; i < 120; i++) {
    const d = await api(`/api/documents/${docId}`);
    if (d.status !== "PROCESSING" && d.status !== "UPLOADED") {
      statusEl.textContent = "";
      await Promise.all([loadDocs(), loadStats()]);
      return openDoc(docId);
    }
    await new Promise(r => setTimeout(r, 1000));
  }
  statusEl.textContent = "Still processing — check the blotter shortly.";
}

/* ----------------------------------------------------------------- review */
async function openDoc(docId) {
  state.activeDocId = docId;
  state.dirty = {};
  state.notice = null;
  state.doc = await api(`/api/documents/${docId}`);
  await loadDocs();
  renderReview();
}

function renderReview() {
  const d = state.doc;
  $("#empty-state").hidden = true;
  const body = $("#review-body");
  body.hidden = false;

  const e = d.extraction;
  const approvable = e && !e.approved && d.status === "PENDING_REVIEW";
  const dirtyCount = Object.keys(state.dirty).length;

  body.innerHTML = `
    <div class="review-header">
      <div>
        <div class="review-title">${escapeHtml(d.filename)}</div>
        <span class="pill pill-${d.status}">${d.status.replace("_", " ")}</span>
        ${e ? `<span class="upload-hint" style="margin-left:8px">extraction #${e.id} · ${e.llm_mode} LLM · ${e.critic_iterations} extraction pass(es)${e.lessons_used.length ? ` · ${e.lessons_used.length} lesson(s) applied` : ""}</span>` : ""}
      </div>
      <div class="review-actions">
        <button class="btn" id="reprocess-btn">Re-run agents</button>
        <button class="btn" id="save-btn" ${dirtyCount ? "" : "disabled"}>Save ${dirtyCount || ""} edit${dirtyCount === 1 ? "" : "s"}</button>
        <button class="btn btn-primary" id="approve-btn" ${approvable && !dirtyCount ? "" : "disabled"}
          title="${dirtyCount ? "Save your edits first" : ""}">Approve → queue for Murex</button>
      </div>
    </div>
    <div id="notice"></div>
    ${e ? renderLedger(e) : `<div class="notice notice-warn">No extraction yet for this document.</div>`}
    ${renderTrail(d)}
    ${renderMasked(d)}
    <div id="payload-slot"></div>`;

  if (state.notice) showNotice(state.notice.kind, state.notice.text);

  $("#reprocess-btn").onclick = reprocess;
  $("#save-btn").onclick = saveEdits;
  $("#approve-btn").onclick = approve;
  wireInputs(e);
}

function renderLedger(e) {
  const rows = FIELD_GROUPS.map(([group, names]) => {
    const rowsHtml = names.map(name => renderFieldRow(e, name)).join("");
    return `<div class="ledger-group">${group}</div>${rowsHtml}`;
  }).join("");
  return `<div class="ledger">${rows}</div>`;
}

function renderFieldRow(e, name) {
  const meta = e.field_meta[name] || {};
  const desc = (e.field_descriptions[name] || "").split(".")[0];
  const chip = meta.edited || meta.source === "manual"
    ? `<span class="chip chip-manual">EDITED</span>`
    : meta.source === "lesson"
      ? `<span class="chip chip-lesson">LESSON</span>`
      : `<span class="chip chip-llm">LLM</span>`;
  const value = e.fields[name];

  let control;
  if (name === "underlyings") {
    control = renderUnderlyings(value);
  } else {
    const display = value === null || value === undefined ? "" : String(value);
    control = `<input data-field="${name}" value="${escapeAttr(display)}"
               placeholder="null" ${e.approved ? "disabled" : ""}>`;
  }
  return `<div class="frow">
    <div class="flabel">${name}<small>${escapeHtml(desc)}</small></div>
    <div class="fvalue">${control}</div>${chip}</div>`;
}

function renderUnderlyings(unds) {
  const list = Array.isArray(unds) ? unds : [];
  const table = list.length ? `<table class="und-table">
      <tr><th>Name</th><th>Ticker</th><th>Exchange</th><th>Initial</th><th>Strike</th></tr>
      ${list.map(u => `<tr><td>${escapeHtml(u.name ?? "")}</td><td>${escapeHtml(u.ticker ?? "")}</td>
        <td>${escapeHtml(u.exchange ?? "")}</td><td>${u.initial_price ?? ""}</td><td>${u.strike_price ?? ""}</td></tr>`).join("")}
    </table>` : `<span class="null">none extracted</span>`;
  return `${table}
    <details class="und-json"><summary class="upload-hint">Edit underlyings as JSON</summary>
      <textarea data-field="underlyings" data-json="1">${escapeHtml(JSON.stringify(list, null, 2))}</textarea>
    </details>`;
}

function wireInputs(e) {
  if (!e) return;
  document.querySelectorAll("[data-field]").forEach(input => {
    const original = input.dataset.json
      ? JSON.stringify(e.fields[input.dataset.field] ?? [], null, 2)
      : (e.fields[input.dataset.field] ?? "") + "";
    input.addEventListener("input", () => {
      const name = input.dataset.field;
      if (input.value !== original) {
        state.dirty[name] = input;
        input.classList.add("dirty");
      } else {
        delete state.dirty[name];
        input.classList.remove("dirty");
      }
      const n = Object.keys(state.dirty).length;
      $("#save-btn").disabled = !n;
      $("#save-btn").textContent = n ? `Save ${n} edit${n === 1 ? "" : "s"}` : "Save edits";
      $("#approve-btn").disabled = true;
    });
  });
}

function coerce(name, raw, isJson) {
  if (isJson) {
    return JSON.parse(raw);
  }
  const trimmed = raw.trim();
  if (trimmed === "" || trimmed.toLowerCase() === "null") return null;
  if (trimmed === "true") return true;
  if (trimmed === "false") return false;
  if (/^-?\d+(\.\d+)?$/.test(trimmed) &&
      !/date|frequency|currency|type|observation/.test(name)) return Number(trimmed);
  return trimmed;
}

async function saveEdits() {
  const e = state.doc.extraction;
  const edits = {};
  try {
    for (const [name, input] of Object.entries(state.dirty)) {
      edits[name] = coerce(name, input.value, !!input.dataset.json);
    }
  } catch (err) {
    return showNotice("err", `Invalid JSON in underlyings: ${err.message}`);
  }
  try {
    const resp = await api(`/api/extractions/${e.id}/fields`, {
      method: "PATCH",
      body: JSON.stringify({ edits, edited_by: "sales" }),
    });
    state.notice = {
      kind: "ok",
      text: `Saved. ${resp.lessons_created.length} lesson(s) recorded — the agents will apply them on future term sheets.`,
    };
    await Promise.all([loadLessons(), loadStats()]);
    await openDoc(state.activeDocId);
  } catch (err) {
    showNotice("err", `Save failed: ${err.message}`);
  }
}

async function approve() {
  const e = state.doc.extraction;
  try {
    const resp = await api(`/api/extractions/${e.id}/approve`, {
      method: "POST",
      body: JSON.stringify({ approved_by: "sales" }),
    });
    state.notice = { kind: "ok", text: "Approved. Trade payload queued for Murex publication." };
    await Promise.all([loadDocs(), loadStats()]);
    state.doc = await api(`/api/documents/${state.activeDocId}`);
    renderReview();
    $("#payload-slot").innerHTML = `
      <details class="panel" open><summary>Murex trade payload (queued)</summary>
      <div class="panel-body"><pre class="payload-pre">${escapeHtml(JSON.stringify(resp.murex_payload, null, 2))}</pre></div></details>`;
  } catch (err) {
    showNotice("err", `Approve failed: ${err.message}`);
  }
}

async function reprocess() {
  await api(`/api/documents/${state.activeDocId}/reprocess`, { method: "POST" });
  showNotice("warn", "Agents re-running with the latest lessons…");
  await pollUntilDone(state.activeDocId, $("#upload-status"));
  await loadLessons();
}

/* ------------------------------------------------------------ side panels */
function renderTrail(d) {
  const items = d.agent_trace.map(t => {
    const issues = (t.detail && t.detail.issues || []).map(i => `<li>${escapeHtml(i)}</li>`).join("");
    return `<li class="agent-${t.agent}">
      <div class="agent-name">${t.agent}</div>
      <div class="agent-summary">${escapeHtml(t.summary)}</div>
      ${issues ? `<ul class="critic-issues">${issues}</ul>` : ""}</li>`;
  }).join("");
  return `<details class="panel" open><summary>Agent conversation</summary>
    <div class="panel-body"><ul class="trail">${items}</ul></div></details>`;
}

function renderMasked(d) {
  const highlighted = escapeHtml(d.masked_preview || "")
    .replace(/\[(CPTY|EMAIL|PHONE|ACCT|PERSON|BIC)_\d+\]/g, m => `<mark>${m}</mark>`);
  return `<details class="panel"><summary>Masked source sent to the LLM
      <span class="upload-hint">${d.mask_token_count} sensitive item(s) masked</span></summary>
    <div class="panel-body"><pre class="masked-pre">${highlighted}</pre></div></details>`;
}

function showNotice(kind, text) {
  const el = $("#notice");
  if (el) el.innerHTML = `<div class="notice notice-${kind}">${escapeHtml(text)}</div>`;
  state.notice = null;
}

/* ------------------------------------------------------------------- utils */
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function escapeAttr(s) { return escapeHtml(s); }
function trunc(s, n) { s = String(s ?? ""); return s.length > n ? s.slice(0, n - 1) + "…" : s; }

/* -------------------------------------------------------------------- init */
wireUpload();
$("#refresh-lessons").onclick = loadLessons;
loadStats();
loadDocs();
loadLessons();
setInterval(loadStats, 15000);

/* ================================================================ TRAINING */

const IMPORTANCE_LABELS = { 1: "Low", 2: "Medium", 3: "High" };

// --- Tab switching --------------------------------------------------------
document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-pane").forEach(p => { p.classList.remove("active"); p.hidden = true; });
    btn.classList.add("active");
    const pane = document.getElementById(btn.dataset.tab);
    pane.classList.add("active");
    pane.hidden = false;
    if (btn.dataset.tab === "training-pane") {
      loadImportanceGrid();
      loadTrainingLibrary();
    }
  });
});

// --- Training file pick ---------------------------------------------------
let trainFile = null;

function wireTrainingUpload() {
  const zone = $("#train-dropzone"), input = $("#train-file-input");
  $("#train-browse-btn").onclick = () => input.click();
  input.onchange = () => { if (input.files[0]) setTrainFile(input.files[0]); };
  ["dragover","dragenter"].forEach(ev => zone.addEventListener(ev, e => {
    e.preventDefault(); zone.classList.add("dragover"); }));
  ["dragleave","drop"].forEach(ev => zone.addEventListener(ev, e => {
    e.preventDefault(); zone.classList.remove("dragover"); }));
  zone.addEventListener("drop", e => { if (e.dataTransfer.files[0]) setTrainFile(e.dataTransfer.files[0]); });
}

function setTrainFile(f) {
  trainFile = f;
  $("#train-file-name").textContent = f.name;
  $("#train-submit-btn").disabled = false;
}

// --- Field importance grid -----------------------------------------------
let importanceState = {};

async function loadImportanceGrid() {
  const data = await api("/api/training/field-importance");
  importanceState = { ...data };
  const grid = $("#importance-grid");
  grid.innerHTML = "";
  for (const [field, imp] of Object.entries(data)) {
    const label = document.createElement("div");
    label.className = "imp-label"; label.textContent = field;
    const sel = document.createElement("select");
    sel.className = "imp-select"; sel.dataset.field = field;
    [1,2,3].forEach(v => {
      const opt = document.createElement("option");
      opt.value = v; opt.textContent = IMPORTANCE_LABELS[v];
      if (v === imp) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.onchange = () => { importanceState[field] = parseInt(sel.value); updateImpColour(sel); };
    updateImpColour(sel);
    grid.appendChild(label);
    grid.appendChild(sel);
  }
}

function updateImpColour(sel) {
  sel.classList.remove("imp-high","imp-low");
  if (sel.value === "3") sel.classList.add("imp-high");
  if (sel.value === "1") sel.classList.add("imp-low");
}

$("#save-importance-btn").onclick = async () => {
  await api("/api/training/field-importance", {
    method: "PUT", body: JSON.stringify({ ...importanceState, updated_by: "trainer" }) });
  showTrainStatus("ok", "Field importance saved.");
};

// --- Training field form --------------------------------------------------
function buildTrainFieldForm() {
  const form = $("#train-field-form");
  form.innerHTML = "";
  for (const [group, names] of FIELD_GROUPS) {
    const hdr = document.createElement("div");
    hdr.className = "tf-group-header"; hdr.textContent = group;
    form.appendChild(hdr);
    for (const name of names) {
      const lbl = document.createElement("div");
      lbl.className = "tf-label"; lbl.textContent = name;

      const inp = document.createElement("input");
      inp.className = "tf-input"; inp.dataset.field = name;
      inp.placeholder = name === "underlyings" ? '[ {"name":"AAPL","ticker":"AAPL:US",...} ]' : "";

      const imp = document.createElement("select");
      imp.className = "tf-imp"; imp.dataset.impFor = name;
      [1,2,3].forEach(v => {
        const opt = document.createElement("option");
        opt.value = v; opt.textContent = IMPORTANCE_LABELS[v];
        if (v === (importanceState[name] || 2)) opt.selected = true;
        imp.appendChild(opt);
      });

      form.appendChild(lbl);
      form.appendChild(inp);
      form.appendChild(imp);
    }
  }
}

// --- Submit training sample -----------------------------------------------
$("#train-submit-btn").onclick = async () => {
  if (!trainFile) return showTrainStatus("err", "Please choose a file first.");

  const fields = {}, fieldImp = {};
  document.querySelectorAll(".tf-input").forEach(inp => {
    const v = inp.value.trim();
    if (v) {
      try { fields[inp.dataset.field] = JSON.parse(v); }
      catch { fields[inp.dataset.field] = v; }
    }
  });
  document.querySelectorAll(".tf-imp").forEach(sel => {
    fieldImp[sel.dataset.impFor] = parseInt(sel.value);
  });

  if (Object.keys(fields).length === 0)
    return showTrainStatus("err", "Please fill in at least one field value.");

  showTrainStatus("warn", "Uploading and generating lessons…");
  const form = new FormData();
  form.append("file", trainFile);
  form.append("labelled_fields", JSON.stringify(fields));
  form.append("field_importance", JSON.stringify(fieldImp));
  form.append("notes", $("#train-notes").value);

  try {
    const resp = await fetch("/api/training/samples", { method: "POST", body: form });
    if (!resp.ok) throw new Error((await resp.json()).detail || resp.statusText);
    const data = await resp.json();
    showTrainStatus("ok",
      `✓ ${data.fields_labelled} fields labelled → ${data.lessons_created} lessons created. Agents will apply them on the next extraction.`);
    trainFile = null;
    $("#train-file-name").textContent = "";
    $("#train-submit-btn").disabled = true;
    document.querySelectorAll(".tf-input").forEach(i => i.value = "");
    $("#train-notes").value = "";
    await Promise.all([loadTrainingLibrary(), loadLessons(), loadStats()]);
  } catch (err) {
    showTrainStatus("err", `Upload failed: ${err.message}`);
  }
};

// --- Training library -----------------------------------------------------
async function loadTrainingLibrary() {
  const samples = await api("/api/training/samples");
  const tbody = $("#train-library tbody");
  tbody.innerHTML = samples.length ? "" :
    `<tr><td colspan="6" class="upload-hint" style="padding:16px">No training samples yet.</td></tr>`;
  for (const s of samples) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(s.filename)}</td>
      <td>${s.fields_labelled}</td>
      <td>${s.lessons_created}</td>
      <td>${escapeHtml(s.uploaded_by)}</td>
      <td>${new Date(s.created_at).toLocaleDateString()}</td>
      <td><button class="btn-del" data-id="${s.id}">Delete</button></td>`;
    tr.querySelector(".btn-del").onclick = () => deleteTrainingSample(s.id, s.filename);
    tbody.appendChild(tr);
  }
}

async function deleteTrainingSample(id, name) {
  if (!confirm(`Delete training sample "${name}"?\nLessons already generated will be kept.`)) return;
  await api(`/api/training/samples/${id}`, { method: "DELETE" });
  await loadTrainingLibrary();
}

function showTrainStatus(kind, text) {
  const el = $("#train-status");
  if (el) el.innerHTML = `<div class="notice notice-${kind}">${escapeHtml(text)}</div>`;
}

$("#refresh-training").onclick = loadTrainingLibrary;

// Initialise training tab on page load
wireTrainingUpload();
buildTrainFieldForm();
