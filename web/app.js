/* Local UI. Every request stays on this origin. */
(function () {
  const $ = (id) => document.getElementById(id);
  const state = {
    card: null,
    path: "",
    dirty: false,
    filling: false,
    busy: false,
    mode: "html",
    html: "",
    markdown: "",
    previewToken: 0,
    timer: 0,
    spdx: ["unknown"],
    browsePath: "",
    browseParent: null,
  };

  const fields = ["name", "version", "description", "created", "intended", "out-of-scope", "gaps"];

  document.addEventListener("DOMContentLoaded", init);

  async function init() {
    $("scan-button").addEventListener("click", () => guarded(() => scan($("path-input").value)));
    $("rescan-button").addEventListener("click", () => guarded(() => scan(state.path || $("path-input").value)));
    $("discard-button").addEventListener("click", () => guarded(discard));
    $("save-button").addEventListener("click", () => guarded(save));
    $("export-md").addEventListener("click", () => guarded(() => exportAs("md")));
    $("export-html").addEventListener("click", () => guarded(() => exportAs("html")));
    $("export-json").addEventListener("click", () => guarded(() => exportAs("json")));
    $("browse-button").addEventListener("click", () => guarded(() => openBrowse($("path-input").value)));
    $("modal-close").addEventListener("click", closeBrowse);
    $("modal-up").addEventListener("click", () => guarded(() => openBrowse(state.browseParent || "")));
    $("modal-scan").addEventListener("click", () => guarded(async () => {
      closeBrowse();
      await scan(state.browsePath);
    }));
    $("add-source").addEventListener("click", () => {
      $("user-sources").append(sourceRow(""));
      onEdit();
    });
    $("show-html").addEventListener("click", () => setMode("html"));
    $("show-md").addEventListener("click", () => setMode("md"));
    $("path-input").addEventListener("keydown", (event) => {
      if (event.key === "Enter") guarded(() => scan($("path-input").value));
    });
    fields.forEach((id) => $(id).addEventListener("input", onEdit));
    $("license").addEventListener("change", onEdit);
    document.querySelectorAll("[data-revert]").forEach((button) => {
      button.addEventListener("click", () => revert(button.dataset.revert));
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeBrowse();
    });
    try {
      const meta = await api("GET", "/api/meta");
      state.spdx = meta.spdx || state.spdx;
      fillLicenseOptions("");
      $("host-line").textContent = `${meta.host}:${meta.port} · offline`;
      renderSamples(meta.samples || []);
    } catch (error) {
      setStatus(error.message, "error");
    }
  }

  function renderSamples(samples) {
    const box = $("samples");
    box.textContent = "";
    samples.forEach((sample) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "sample";
      const title = document.createElement("strong");
      title.textContent = sample.name;
      const kind = document.createElement("span");
      kind.textContent = sample.kind;
      button.append(title, kind);
      button.addEventListener("click", () => guarded(() => scan(sample.path)));
      box.append(button);
    });
  }

  async function scan(path, discard) {
    if (state.card && state.dirty && !discard) await save();
    clearTimeout(state.timer);
    state.previewToken += 1;
    const result = await api("POST", "/api/scan", {
      path: path,
      discard_edits: Boolean(discard),
    });
    state.card = result.card;
    state.path = result.card.dataset_path;
    $("path-input").value = state.path;
    state.dirty = false;
    fillEditor(result.card);
    showPreview(result);
    showWorkspace();
    const outputs = result.outputs || {};
    $("output-line").textContent = outputs.markdown
      ? `Wrote ${outputs.markdown}`
      : "Card written beside the dataset.";
    setStatus(
      `Scanned ${result.card.kind} dataset. DATACARD.md, DATACARD.html, and datacard.json are up to date.`,
      "ok"
    );
  }

  async function save() {
    if (!state.path) throw new Error("Scan a folder first.");
    const result = await api("POST", "/api/save", { path: state.path, edits: readEdits() });
    state.card = result.card;
    state.dirty = false;
    updatePills(result.card);
    showPreview(result);
    $("dirty-label").hidden = true;
    setStatus("Saved edits and rewrote the card files.", "ok");
    return result;
  }

  async function discard() {
    if (!state.path) return;
    if (!window.confirm("Discard your edits and scan this folder again?")) return;
    state.dirty = false;
    await scan(state.path, true);
    setStatus("Edits discarded. The card was rebuilt from the folder.", "ok");
  }

  async function exportAs(fmt) {
    await save();
    const response = await fetch(`/api/export?path=${encodeURIComponent(state.path)}&format=${fmt}`);
    if (!response.ok) {
      let message = "Export failed.";
      try {
        const data = await response.json();
        message = data.error || message;
      } catch (_error) {
        /* The body was not JSON. */
      }
      throw new Error(message);
    }
    const blob = await response.blob();
    const href = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = href;
    link.download = { md: "DATACARD.md", html: "DATACARD.html", json: "datacard.json" }[fmt];
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(href);
    setStatus(`Exported ${link.download}.`, "ok");
  }

  function fillEditor(card) {
    state.filling = true;
    $("dataset-title").textContent = card.overview.name.value || "Card";
    $("kind-badge").textContent = card.kind;
    setValue("name", card.overview.name.value);
    setValue("version", card.overview.version.value);
    setValue("description", card.overview.description.value);
    setValue("created", card.overview.created.value);
    setValue("intended", card.intended_use.value);
    setValue("out-of-scope", card.out_of_scope_use.value);
    setValue("gaps", card.known_gaps.user || "");
    fillLicenseOptions(card.license.value);
    renderUserSources((card.sources.user || []).map((item) => item.text));
    renderSize(card);
    renderSchema(card);
    renderBalance(card);
    renderMissing(card);
    renderDupes(card);
    renderPii(card);
    renderAutoSources(card);
    renderGaps(card);
    renderErrors(card);
    updatePills(card);
    $("dirty-label").hidden = true;
    $("rescan-button").hidden = false;
    $("discard-button").hidden = false;
    state.filling = false;
  }

  function renderSize(card) {
    const size = card.size;
    const specs = [
      ["Rows", String(size.rows)],
      ["Columns", String(size.columns)],
      ["Files", String(size.files)],
      ["On disk", formatBytes(size.bytes)],
      ["Images", String(size.images)],
      ["Tables", String(size.tables)],
    ];
    const box = $("size-tiles");
    box.textContent = "";
    specs.forEach(([label, value]) => {
      const tile = el("div", { class: "tile" });
      tile.append(el("span", { text: label }), el("strong", { text: value }));
      box.append(tile);
    });
    const resolution = size.resolution || {};
    $("resolution-line").textContent = size.images
      ? `Resolution ${resolution.min_width}–${resolution.max_width} × ${resolution.min_height}–${resolution.max_height} px, mean ${resolution.mean_width} × ${resolution.mean_height}. Shortest side ${resolution.min_side} px. ${resolution.small_image_count} under ${resolution.small_image_threshold} px.`
      : "";
  }

  function renderSchema(card) {
    const box = $("schema-box");
    box.textContent = "";
    if (!card.schema.length) {
      box.append(el("p", { class: "note", text: "This dataset has no tabular columns." }));
      return;
    }
    box.append(table(
      ["Table", "Column", "Type", "Examples", "Unique", "Nulls"],
      card.schema.map((column) => [
        column.table,
        column.column,
        column.dtype,
        (column.examples || []).join(", ") || "—",
        String(column.unique_count),
        String(column.null_count),
      ])
    ));
  }

  function renderBalance(card) {
    const balance = card.class_balance;
    const box = $("balance-box");
    box.textContent = "";
    if (!balance.total) {
      $("balance-summary").textContent = "No label column or image classes found.";
      return;
    }
    const ratio = balance.imbalance_ratio == null ? "n/a" : Number(balance.imbalance_ratio).toFixed(3);
    $("balance-summary").textContent = `Source ${balance.source}. Total ${balance.total}. Imbalance ratio ${ratio}.`;
    balance.counts.forEach((row) => box.append(barRow(row.label, row.count, row.percent)));
    (balance.warnings || []).forEach((warning) => {
      box.append(el("p", { class: "warn", text: warning }));
    });
  }

  function renderMissing(card) {
    const missing = card.missingness;
    const box = $("missing-box");
    box.textContent = "";
    if (!missing.rows) {
      $("missing-summary").textContent = "No tabular rows.";
      return;
    }
    $("missing-summary").textContent = `Rows with any missing value: ${missing.rows_with_any_missing} of ${missing.rows} (${Number(missing.rows_with_any_missing_percent).toFixed(2)}%).`;
    box.append(table(
      ["Table", "Column", "Nulls", "Null %"],
      missing.columns.map((column) => [
        column.table,
        column.column,
        String(column.null_count),
        Number(column.null_percent).toFixed(2),
      ])
    ));
  }

  function renderDupes(card) {
    const rows = card.duplicates.rows;
    const images = card.duplicates.images;
    const box = $("dupe-box");
    box.textContent = "";
    box.append(el("p", {
      text: `Exact duplicate rows (copies beyond the first): ${rows.extra_duplicate_rows}. Groups: ${rows.duplicate_groups}.`,
    }));
    box.append(el("p", {
      text: `Exact extra image files: ${images.exact_extra_files}. Near-duplicate extra files: ${images.near_extra_files}.`,
    }));
    box.append(el("p", { class: "note", text: images.method || "" }));
    appendGroups(box, "Exact image groups", images.exact_groups, (group) => `${group.count} files`);
    appendGroups(box, "Near image groups", images.near_groups, (group) => `${group.distinct_files} distinct files`);
  }

  function appendGroups(box, title, groups, summary) {
    box.append(el("h4", { text: title }));
    if (!groups || !groups.length) {
      box.append(el("p", { class: "note", text: "None." }));
      return;
    }
    groups.forEach((group) => {
      const item = el("div");
      item.append(el("p", { text: summary(group) }));
      const list = el("ul");
      group.paths.forEach((file) => list.append(el("li", { text: file })));
      item.append(list);
      box.append(item);
    });
  }

  function renderPii(card) {
    const box = $("pii-box");
    box.textContent = "";
    if (!card.pii_hints.length) {
      box.append(el("p", { class: "note", text: "No columns looked like emails, phone numbers, or personal names." }));
      return;
    }
    box.append(table(
      ["Table", "Column", "Hint", "Match %", "Why"],
      card.pii_hints.map((hint) => [
        hint.table,
        hint.column,
        hint.kind,
        Number(hint.match_percent).toFixed(2),
        hint.reason,
      ])
    ));
  }

  function renderAutoSources(card) {
    const box = $("auto-sources");
    box.textContent = "";
    const autos = card.sources.auto || [];
    if (!autos.length) {
      box.append(el("p", { class: "note", text: "No README, LICENSE, or source.txt in this folder." }));
      return;
    }
    autos.forEach((item) => {
      const paragraph = el("p", { class: "auto-source" });
      const code = el("code", { text: item.path });
      paragraph.append(code, ` (${item.kind}): ${item.excerpt || "empty"}`);
      box.append(paragraph);
    });
  }

  function renderGaps(card) {
    const box = $("auto-gaps");
    box.textContent = "";
    const autos = card.known_gaps.auto || [];
    if (!autos.length) {
      box.append(el("p", { class: "note", text: "No gaps suggested from the scan." }));
    } else {
      const list = el("ul", { class: "gap-list" });
      autos.forEach((item) => list.append(el("li", { text: item })));
      box.append(list);
    }
    const rules = card.thresholds || {};
    $("threshold-line").textContent = `Thresholds: rare class under ${rules.rare_class_percent}%, imbalance ratio above ${rules.imbalance_ratio}, missing above ${rules.high_missing_percent}%, images under ${rules.small_image_min_side}px.`;
  }

  function renderErrors(card) {
    const box = $("error-box");
    box.textContent = "";
    (card.errors || []).forEach((message) => box.append(el("p", { class: "warn", text: message })));
  }

  function renderUserSources(notes) {
    const box = $("user-sources");
    box.textContent = "";
    (notes.length ? notes : [""]).forEach((note) => box.append(sourceRow(note)));
  }

  function sourceRow(text) {
    const row = el("div", { class: "source-row" });
    const input = document.createElement("input");
    input.type = "text";
    input.className = "user-source";
    input.placeholder = "A source note";
    input.value = text;
    input.addEventListener("input", onEdit);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => {
      row.remove();
      onEdit();
    });
    row.append(input, remove);
    return row;
  }

  function readEdits() {
    return {
      name: $("name").value,
      version: $("version").value,
      description: $("description").value,
      created: $("created").value,
      license: $("license").value,
      intended_use: $("intended").value,
      out_of_scope_use: $("out-of-scope").value,
      known_gaps_user: $("gaps").value,
      sources_user: Array.from(document.querySelectorAll(".user-source")).map((input) => input.value),
    };
  }

  function updatePills(card) {
    const pairs = {
      name: card.overview.name,
      version: card.overview.version,
      description: card.overview.description,
      created: card.overview.created,
      license: card.license,
    };
    Object.entries(pairs).forEach(([key, field]) => {
      const pill = document.querySelector(`[data-pill="${key}"]`);
      if (!pill || !field) return;
      pill.textContent = field.source === "user" ? "edited" : "scanned";
      pill.classList.toggle("user", field.source === "user");
    });
  }

  function revert(key) {
    if (!state.card) return;
    const map = {
      name: ["name", state.card.overview.name],
      version: ["version", state.card.overview.version],
      description: ["description", state.card.overview.description],
      created: ["created", state.card.overview.created],
      license: ["license", state.card.license],
    };
    const pair = map[key];
    if (!pair) return;
    $(pair[0]).value = pair[1].auto_value || "";
    onEdit();
  }

  function onEdit() {
    if (state.filling) return;
    state.dirty = true;
    $("dirty-label").hidden = false;
    clearTimeout(state.timer);
    state.timer = setTimeout(runPreview, 250);
  }

  async function runPreview() {
    if (!state.path || !state.card) return;
    const token = ++state.previewToken;
    try {
      const result = await api("POST", "/api/preview", { path: state.path, edits: readEdits() });
      if (token !== state.previewToken) return;
      updatePills(result.card);
      showPreview(result);
    } catch (error) {
      if (token === state.previewToken) setStatus(error.message, "error");
    }
  }

  function showPreview(result) {
    state.html = result.html || "";
    state.markdown = result.markdown || "";
    paintPreview();
  }

  function setMode(mode) {
    state.mode = mode;
    $("show-html").classList.toggle("primary", mode === "html");
    $("show-md").classList.toggle("primary", mode === "md");
    paintPreview();
  }

  function paintPreview() {
    const frame = $("preview");
    const markdown = $("markdown-preview");
    if (state.mode === "md") {
      markdown.textContent = state.markdown;
      markdown.hidden = false;
      frame.hidden = true;
    } else {
      frame.srcdoc = state.html;
      frame.hidden = false;
      markdown.hidden = true;
    }
  }

  function showWorkspace() {
    $("welcome").hidden = true;
    $("editor").hidden = false;
  }

  async function openBrowse(path) {
    const data = await api("GET", `/api/browse?path=${encodeURIComponent(path || "")}`);
    state.browsePath = data.path;
    state.browseParent = data.parent;
    $("modal-path").textContent = data.path;
    $("modal-up").hidden = !data.parent;
    const list = $("modal-list");
    list.textContent = "";
    data.directories.forEach((entry) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = entry.name;
      button.addEventListener("click", () => guarded(() => openBrowse(entry.path)));
      item.append(button);
      list.append(item);
    });
    if (!data.directories.length) {
      list.append(el("li", { text: "No subfolders." }));
    }
    $("modal").hidden = false;
  }

  function closeBrowse() {
    $("modal").hidden = true;
  }

  function fillLicenseOptions(selected) {
    const select = $("license");
    const options = state.spdx.slice();
    if (selected && !options.includes(selected)) options.unshift(selected);
    select.textContent = "";
    options.forEach((license) => {
      const option = document.createElement("option");
      option.value = license;
      option.textContent = license;
      select.append(option);
    });
    if (selected) select.value = selected;
  }

  function barRow(label, count, percent) {
    const row = el("div", { class: "bar-row" });
    const track = el("div", { class: "bar-track" });
    const fill = el("div", { class: "bar-fill" });
    fill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
    track.append(fill);
    row.append(
      el("span", { class: "bar-label", text: label }),
      track,
      el("span", { class: "bar-num", text: `${count} · ${Number(percent).toFixed(2)}%` })
    );
    return row;
  }

  function table(headers, rows) {
    const node = document.createElement("table");
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    headers.forEach((header) => headRow.append(el("th", { text: header })));
    head.append(headRow);
    const body = document.createElement("tbody");
    rows.forEach((cells) => {
      const row = document.createElement("tr");
      cells.forEach((cell) => row.append(el("td", { text: cell })));
      body.append(row);
    });
    node.append(head, body);
    return node;
  }

  function el(tag, attrs) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value == null ? "" : String(value);
      else node.setAttribute(key, value);
    });
    return node;
  }

  function setValue(id, value) {
    $(id).value = value == null ? "" : value;
  }

  function formatBytes(size) {
    let value = Number(size) || 0;
    const units = ["B", "KB", "MB", "GB"];
    let index = 0;
    while (value >= 1024 && index < units.length - 1) {
      value /= 1024;
      index += 1;
    }
    return index === 0 ? `${value} ${units[index]}` : `${value.toFixed(1)} ${units[index]}`;
  }

  async function guarded(work) {
    if (state.busy) return;
    state.busy = true;
    document.body.classList.add("busy");
    try {
      await work();
    } catch (error) {
      setStatus(error.message || "Something went wrong.", "error");
    } finally {
      state.busy = false;
      document.body.classList.remove("busy");
    }
  }

  function setStatus(message, kind) {
    const node = $("status");
    node.textContent = message || "";
    node.className = kind ? `status ${kind}` : "status";
  }

  async function api(method, url, body) {
    const options = { method, headers: {} };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    const response = await fetch(url, options);
    const text = await response.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch (_error) {
      data = { error: text };
    }
    if (!response.ok) throw new Error((data && data.error) || response.statusText);
    return data;
  }
})();
