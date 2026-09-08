import { api } from "./api.js";
import { hydrateIcons, icon } from "./icons.js";

const BOARDS = [
  { id: "upload", label: "Upload", icon: "upload", count: null },
  { id: "crf-book", label: "CRF Book", icon: "grid", count: "CRF_Book" },
  { id: "forms", label: "Forms", icon: "forms", count: "Forms" },
  { id: "fields", label: "Fields", icon: "fields", count: "Fields" },
  { id: "folders", label: "Folders", icon: "folders", count: "Folders" },
  { id: "dictionary-entries", label: "Data Dictionary Entries", icon: "dictionary", count: "DataDictionaryEntries" },
  { id: "checks", label: "Checks", icon: "checks", count: "Checks" }
];

const BOARD_COPY = {
  "crf-book": ["CRF Book", "Review where forms are collected across study folders."],
  forms: ["Forms", "Search form definitions, labels, and active state."],
  fields: ["Fields", "Inspect field structure, display text, coding, and configuration."],
  folders: ["Folders", "Review folder definitions and parent relationships."],
  "dictionary-entries": ["Data Dictionary Entries", "Search coded values and their user-facing labels."],
  checks: ["Checks", "Review edit check names, expressions, and active state."]
};

const LABELS = {
  OID: "OID",
  FormOID: "Form OID",
  FieldOID: "Field OID",
  FolderOID: "Folder OID",
  DraftFormName: "Form name",
  DraftFormActive: "Active",
  DraftFieldActive: "Active",
  FolderName: "Folder name",
  ParentFolderOID: "Parent folder OID",
  DataDictionaryName: "Data dictionary",
  CodedData: "Coded data",
  UserDataString: "User value",
  CodingDictionary: "Coding dictionary",
  ControlType: "Control type",
  CheckName: "Check name",
  CheckActive: "Active",
  PreText: "Pre-text / label",
  Infix: "Infix expression"
};

const WRAP_COLUMNS = new Set([
  "PreText", "HeaderText", "HelpText", "Infix", "ViewRestrictions", "EntryRestrictions"
]);
const BOOLEAN_COLUMNS = new Set([
  "DraftFormActive", "DraftFieldActive", "CheckActive", "IsLog", "IsVisible",
  "IsRequired", "QueryNonConformance", "QueryFutureDate", "CanSetRecordDate",
  "CanSetDataPageDate", "CanSetInstanceDate", "CanSetSubjectDate",
  "DoesNotBreakSignature", "IsReusable", "Specify", "BypassDuringMigration"
]);
const IDENTIFIER_PATTERN = /(^OID$|OID$|DictionaryName$|CodedData$)/;

const state = {
  board: "upload",
  schema: null,
  status: { ready: false, counts: {}, warnings: [] },
  filters: {},
  active: "",
  exactMatch: false,
  page: 1,
  pageSize: 50,
  sort: "",
  direction: "asc",
  result: null,
  loading: false,
  uploadState: "idle",
  uploadError: "",
  optionalGroups: new Set(),
  conversion: {
    open: false,
    loading: false,
    data: null,
    error: "",
    checkName: "",
    originalInfix: ""
  }
};

const main = document.querySelector("#main-content");
const nav = document.querySelector("#board-nav");
const sidebar = document.querySelector("#sidebar");
const scrim = document.querySelector("#sidebar-scrim");
let filterTimer;
let requestSequence = 0;
let conversionTrigger = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatCount(value) {
  return Number(value || 0).toLocaleString();
}

function showToast(message, type = "success") {
  const toast = document.createElement("div");
  toast.className = `toast ${type === "error" ? "error" : ""}`;
  toast.setAttribute("role", type === "error" ? "alert" : "status");
  toast.innerHTML = `${icon(type === "error" ? "warning" : "check")}<span>${escapeHtml(message)}</span>`;
  document.querySelector("#toast-region").append(toast);
  window.setTimeout(() => toast.remove(), 4500);
}

function closeSidebar() {
  sidebar.classList.remove("open");
  scrim.hidden = true;
  document.querySelector("#mobile-menu").setAttribute("aria-expanded", "false");
}

function updateChrome() {
  const ready = state.status.ready;
  const identity = [state.status.project, state.status.draft].filter(Boolean).join(" · ");
  document.querySelector("#study-name").textContent = ready ? (identity || state.status.filename) : "Awaiting workbook";
  document.querySelector("#sidebar-status").textContent = ready ? "Workbook ready" : "No workbook loaded";
  document.querySelector("#sidebar-status-dot").classList.toggle("ready", ready);
  renderNavigation();
}

function renderNavigation() {
  nav.innerHTML = BOARDS.map((board) => {
    const count = board.count && state.status.ready
      ? `<span class="nav-count">${formatCount(state.status.counts[board.count])}</span>`
      : "";
    return `
      <button class="nav-button ${state.board === board.id ? "active" : ""}" type="button"
        data-board="${board.id}" ${state.board === board.id ? 'aria-current="page"' : ""}>
        ${icon(board.icon)}<span>${escapeHtml(board.label)}</span>${count}
      </button>`;
  }).join("");
}

function resetBoardState() {
  state.filters = {};
  state.active = "";
  state.exactMatch = false;
  state.page = 1;
  state.sort = "";
  state.direction = "asc";
  state.result = null;
  state.optionalGroups.clear();
}

async function navigate(board, presetFilters = null) {
  state.board = board;
  resetBoardState();
  if (presetFilters) state.filters = { ...presetFilters };
  updateChrome();
  closeSidebar();
  renderCurrentBoard();
  main.focus({ preventScroll: true });
  if (board !== "upload" && state.status.ready) await loadBoard();
}

function pageHeading(title, description, action = "") {
  return `
    <div class="page-head">
      <div><h1>${escapeHtml(title)}</h1><p>${escapeHtml(description)}</p></div>
      ${action}
    </div>`;
}

function uploadView() {
  const parsing = state.uploadState === "parsing";
  const counts = state.status.counts || {};
  const parseItems = [
    ["Forms", counts.Forms],
    ["Fields", counts.Fields],
    ["Folders", counts.Folders],
    ["Dictionary entries", counts.DataDictionaryEntries],
    ["Checks", counts.Checks],
    ["CRF Book forms", counts.CRF_Book],
    ["CRF Book folders", counts.CRF_BookFolders],
    ["Collected cells", counts.CRF_BookCollected]
  ];
  const parsePanel = state.status.ready ? `
    <section class="parse-panel" aria-labelledby="parse-title">
      <div class="panel-title"><h2 id="parse-title">Latest parse</h2><span class="success-tag">${icon("check")}Ready</span></div>
      <ul class="parse-list">${parseItems.map(([label, count]) =>
        `<li><span>${escapeHtml(label)}</span><strong>${formatCount(count)}</strong></li>`).join("")}</ul>
      ${state.status.warnings.map((warning) =>
        `<p class="notice warning">${icon("warning")}<span>${escapeHtml(warning)}</span></p>`).join("")}
      <p class="notice">${icon("info")}<span>${escapeHtml(
        [state.status.filename, state.status.project, state.status.draft].filter(Boolean).join(" · ")
      )}. A successful upload replaces the current local study; failed uploads leave it unchanged.</span></p>
    </section>` : `
    <section class="parse-panel" aria-labelledby="parse-title">
      <div class="panel-title"><h2 id="parse-title">Parse log</h2></div>
      <div class="empty-state">${icon("file")}<div><h3>No workbook parsed</h3><p>Sheet counts and CRF Book dimensions will appear here after a successful upload.</p></div></div>
    </section>`;

  main.innerHTML = `
    ${pageHeading("Upload workbook", "Load one Rave Architect Loader Specification workbook for local, read-only review.")}
    <div class="upload-layout">
      <section class="upload-panel">
        <div class="drop-zone" id="drop-zone">
          <div>
            <span class="drop-icon">${icon("cloud-upload")}</span>
            <h2>${parsing ? "Parsing workbook…" : "Drop an ALS workbook here"}</h2>
            <p>${parsing ? "Validating sheets and preparing the current study." : "Choose one .xlsx file or drag it into this area."}</p>
            <input id="workbook-input" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" hidden>
            <button class="button button-primary" id="choose-workbook" type="button" ${parsing ? "disabled" : ""}>
              ${icon("upload")}Choose workbook
            </button>
            <div class="file-rules"><span>${icon("check")}XLSX only</span><span>${icon("check")}100 MB maximum</span></div>
            ${parsing ? '<div class="upload-progress" aria-label="Parsing workbook"><div class="progress-track"><div class="progress-bar"></div></div></div>' : ""}
            ${state.uploadError ? `<p class="notice warning" role="alert">${icon("warning")}<span>${escapeHtml(state.uploadError)}</span></p>` : ""}
          </div>
        </div>
      </section>
      ${parsePanel}
    </div>`;
  bindUpload();
}

function bindUpload() {
  const input = document.querySelector("#workbook-input");
  const dropZone = document.querySelector("#drop-zone");
  document.querySelector("#choose-workbook").addEventListener("click", () => input.click());
  input.addEventListener("change", () => input.files[0] && uploadFile(input.files[0]));
  ["dragenter", "dragover"].forEach((eventName) => dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    if (state.uploadState !== "parsing") dropZone.classList.add("dragging");
  }));
  ["dragleave", "drop"].forEach((eventName) => dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove("dragging");
  }));
  dropZone.addEventListener("drop", (event) => {
    if (state.uploadState !== "parsing" && event.dataTransfer.files[0]) uploadFile(event.dataTransfer.files[0]);
  });
}

async function uploadFile(file) {
  if (!file.name.toLowerCase().endsWith(".xlsx")) {
    state.uploadError = "Choose an .xlsx workbook. Legacy .xls and other formats are not supported.";
    uploadView();
    return;
  }
  state.uploadState = "parsing";
  state.uploadError = "";
  uploadView();
  try {
    state.status = await api.upload(file);
    state.uploadState = "success";
    updateChrome();
    uploadView();
    showToast("Workbook parsed and activated.");
  } catch (error) {
    state.uploadState = "error";
    state.uploadError = error.message;
    uploadView();
    showToast(error.message, "error");
  }
}

function selectedColumns() {
  if (state.board !== "fields") return null;
  const columns = [...state.schema.fieldFixedColumns];
  for (const [group, groupColumns] of Object.entries(state.schema.fieldOptionalGroups)) {
    if (state.optionalGroups.has(group)) columns.push(...groupColumns);
  }
  return columns;
}

function filterControls() {
  if (state.board === "crf-book") {
    return [
      ["FormOID", "Form OID", "e.g. PE, PK"],
      ["FolderOID", "Folder OID", "e.g. SCREEN, BASELINE"]
    ];
  }
  const config = state.schema.boards[state.board];
  return config.filters.map((column) => [column, LABELS[column] || column, `Search ${LABELS[column] || column}`]);
}

function fieldsColumnPicker() {
  if (state.board !== "fields") return "";
  return `
    <div class="column-picker">
      <button class="button button-secondary" id="column-picker-button" type="button" aria-expanded="false">
        ${icon("columns")}Columns
      </button>
      <div class="column-menu" id="column-menu" hidden>
        <h3>Add optional column groups</h3>
        ${Object.entries(state.schema.fieldOptionalGroups).map(([group, columns]) => `
          <label class="column-option">
            <input type="checkbox" value="${escapeHtml(group)}" ${state.optionalGroups.has(group) ? "checked" : ""}>
            <span>${escapeHtml(group)}<small>${columns.map((column) => escapeHtml(LABELS[column] || column)).join(", ")}</small></span>
          </label>`).join("")}
      </div>
    </div>`;
}

function toolbarView() {
  const controls = filterControls().map(([column, label, placeholder]) => `
    <div class="field">
      <label for="filter-${escapeHtml(column)}">${escapeHtml(label)}</label>
      <div class="input-wrap">${icon("search")}
        <input id="filter-${escapeHtml(column)}" data-filter="${escapeHtml(column)}" value="${escapeHtml(state.filters[column] || "")}"
          placeholder="${escapeHtml(placeholder)}" autocomplete="off">
      </div>
    </div>`).join("");
  const activeColumn = state.board !== "crf-book" && state.schema.boards[state.board].activeColumn;
  return `
    <section class="data-toolbar" aria-label="Search and table controls">
      <div class="filter-grid">
        ${controls}
        ${activeColumn ? `
          <div class="field"><label for="active-filter">Active state</label>
            <select id="active-filter">
              <option value="">All states</option>
              <option value="TRUE" ${state.active === "TRUE" ? "selected" : ""}>Active</option>
              <option value="FALSE" ${state.active === "FALSE" ? "selected" : ""}>Inactive</option>
            </select>
          </div>` : ""}
      </div>
      <div class="toolbar-foot">
        <div class="filter-guidance">
          <span class="filter-hint" id="match-mode-help">Comma-separated values use OR. Matching is case-insensitive.</span>
          <label class="match-toggle" for="exact-match">
            <input id="exact-match" type="checkbox" role="switch" aria-describedby="match-mode-help" ${state.exactMatch ? "checked" : ""}>
            <span class="switch-control" aria-hidden="true"><span></span></span>
            <span>Exact match</span>
          </label>
        </div>
        <div class="toolbar-actions">
          <button class="button button-quiet" id="reset-filters" type="button">${icon("rotate")}Reset</button>
          ${fieldsColumnPicker()}
          <a class="button button-secondary" id="download-csv" href="${escapeHtml(csvUrl())}" download>${icon("download")}Download CSV</a>
        </div>
      </div>
    </section>`;
}

function cellView(column, rawValue, row) {
  const value = String(rawValue ?? "");
  if (state.board === "crf-book" && column !== "FormOID") {
    return value === "X" ? '<span class="matrix-x">X</span>' : "";
  }
  if (state.board === "fields" && column === "DataDictionaryName" && value) {
    return `<button class="dictionary-link" type="button" data-dictionary="${escapeHtml(value)}">${escapeHtml(value)}${icon("arrow")}</button>`;
  }
  if (BOOLEAN_COLUMNS.has(column) && value) {
    const isTrue = ["TRUE", "1", "YES"].includes(value.trim().toUpperCase());
    return `<span class="boolean ${isTrue ? "true" : ""}">${isTrue ? "TRUE" : "FALSE"}</span>`;
  }
  if (state.board === "checks" && column === "Infix" && value && row._check_row_id) {
    return `
      <button class="infix-link" type="button" data-check-conversion="${escapeHtml(row._check_row_id)}"
        data-check-name="${escapeHtml(row.CheckName || "")}" aria-label="Convert ${escapeHtml(row.CheckName || "check")} Infix to YAML">
        <span>${escapeHtml(value)}</span>${icon("external")}
      </button>`;
  }
  return escapeHtml(value);
}

function tableView() {
  if (state.loading && !state.result) {
    return `<section class="table-panel"><div class="empty-state">${icon("rotate")}<div><h3>Loading results</h3><p>Retrieving the current filtered dataset.</p></div></div></section>`;
  }
  if (!state.result) return "";
  const { columns, rows, total, page, page_size: pageSize } = state.result;
  const first = total ? (page - 1) * pageSize + 1 : 0;
  const last = Math.min(page * pageSize, total);
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const tableClass = state.board === "crf-book" ? "crf-table" : "";
  return `
    <section class="table-panel" aria-live="polite" aria-busy="${state.loading}">
      <div class="table-meta">
        <span class="result-count">${formatCount(total)} results <span>· showing ${formatCount(first)}–${formatCount(last)}</span></span>
        <span class="loading-text">${state.loading ? "Updating…" : ""}</span>
      </div>
      ${rows.length ? `
        <div class="table-scroll">
          <table class="${tableClass}">
            <thead><tr>${columns.map((column) => `
              <th scope="col">${state.board === "crf-book" ? escapeHtml(LABELS[column] || column) : `
                <button type="button" data-sort="${escapeHtml(column)}">
                  <span>${escapeHtml(LABELS[column] || column)}</span>
                  ${state.sort === column ? icon(state.direction === "asc" ? "arrow-up" : "arrow-down") : ""}
                </button>`}</th>`).join("")}</tr></thead>
            <tbody>${rows.map((row) => `<tr>${columns.map((column) => {
              const classes = [
                WRAP_COLUMNS.has(column) ? "wrap" : "",
                IDENTIFIER_PATTERN.test(column) ? "identifier" : ""
              ].filter(Boolean).join(" ");
              return `<td class="${classes}">${cellView(column, row[column], row)}</td>`;
            }).join("")}</tr>`).join("")}</tbody>
          </table>
        </div>` : `
        <div class="empty-state">${icon("search")}<div><h3>No matching results</h3><p>Adjust or reset the current filters to see more records.</p></div></div>`}
      <div class="pagination">
        <span class="pagination-info">Page ${formatCount(page)} of ${formatCount(pageCount)}</span>
        <div class="pagination-actions">
          <button class="button button-secondary" type="button" data-page="${page - 1}" ${page <= 1 ? "disabled" : ""}>Previous</button>
          <button class="button button-secondary" type="button" data-page="${page + 1}" ${page >= pageCount ? "disabled" : ""}>Next</button>
        </div>
      </div>
    </section>`;
}

function conversionModalView() {
  const conversion = state.conversion;
  const data = conversion.data;
  const status = conversion.loading ? "loading" : (data?.status || "error");
  const statusLabel = {
    loading: "Converting",
    success: "Converted",
    warning: "Converted with warnings",
    error: "Conversion unavailable"
  }[status];
  const diagnostics = data?.diagnostics || [];
  const originalInfix = data?.original_infix || conversion.originalInfix;
  const checkName = data?.check_name || conversion.checkName || "Edit check";
  const yaml = data?.yaml || "";

  return `
    <div class="modal-backdrop" id="conversion-modal">
      <section class="conversion-dialog" role="dialog" aria-modal="true" aria-labelledby="conversion-title"
        aria-describedby="conversion-summary">
        <header class="conversion-head">
          <div>
            <span class="eyebrow">Infix to YAML</span>
            <h2 id="conversion-title" tabindex="-1">${escapeHtml(checkName)}</h2>
            <p id="conversion-summary">Read-only explanation of the current study edit check.</p>
          </div>
          <button class="icon-button modal-close" type="button" data-close-conversion aria-label="Close conversion dialog">
            ${icon("close")}
          </button>
        </header>
        <div class="conversion-status ${escapeHtml(status)}" role="status">
          ${icon(status === "error" ? "warning" : status === "success" ? "check" : "info")}
          <span><strong>${escapeHtml(statusLabel)}</strong>${data?.cached ? " · saved conversion" : ""}</span>
        </div>
        <div class="conversion-body">
          ${conversion.loading ? `
            <div class="conversion-loading" aria-live="polite">
              <span class="loading-spinner" aria-hidden="true"></span>
              <div><h3>Reading the expression</h3><p>Resolving study Forms, Fields, and Folders and building the Boolean structure.</p></div>
            </div>` : ""}
          ${conversion.error ? `
            <p class="conversion-error" role="alert">${icon("warning")}<span>${escapeHtml(conversion.error)}</span></p>` : ""}
          ${diagnostics.length ? `
            <section class="diagnostics" aria-labelledby="diagnostics-title">
              <h3 id="diagnostics-title">Conversion diagnostics</h3>
              <ul>${diagnostics.map((item) => `
                <li class="${escapeHtml(item.severity)}">
                  <strong>${escapeHtml(item.code.replaceAll("_", " "))}</strong>
                  <span>${escapeHtml(item.message)}</span>
                  ${item.source_text ? `<code>${escapeHtml(item.source_text)}</code>` : ""}
                </li>`).join("")}</ul>
            </section>` : ""}
          ${yaml ? `
            <section class="yaml-panel" aria-labelledby="yaml-title">
              <div class="yaml-head">
                <div><span class="eyebrow">Normalized output</span><h3 id="yaml-title">YAML</h3></div>
                <button class="button button-secondary" id="copy-yaml" type="button">${icon("copy")}Copy YAML</button>
              </div>
              <pre tabindex="0"><code>${escapeHtml(yaml)}</code></pre>
            </section>` : ""}
          <details class="infix-source" ${!yaml && !conversion.loading ? "open" : ""}>
            <summary>Original Infix</summary>
            <pre><code>${escapeHtml(originalInfix)}</code></pre>
          </details>
        </div>
        <footer class="conversion-foot">
          <p>This conversion is for review only and cannot be uploaded to Rave.</p>
          <button class="button button-primary" type="button" data-close-conversion>Close</button>
        </footer>
      </section>
    </div>`;
}

function closeConversionModal() {
  if (!state.conversion.open) return;
  state.conversion.open = false;
  document.querySelector("#conversion-modal")?.remove();
  document.body.classList.remove("modal-open");
  const trigger = conversionTrigger;
  conversionTrigger = null;
  if (trigger?.isConnected) trigger.focus();
}

async function copyYaml(yaml) {
  try {
    await navigator.clipboard.writeText(yaml);
  } catch {
    const field = document.createElement("textarea");
    field.value = yaml;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.append(field);
    field.select();
    document.execCommand("copy");
    field.remove();
  }
  showToast("YAML copied to the clipboard.");
}

function bindConversionModal() {
  const backdrop = document.querySelector("#conversion-modal");
  const dialog = backdrop?.querySelector(".conversion-dialog");
  if (!backdrop || !dialog) return;
  backdrop.querySelectorAll("[data-close-conversion]").forEach((button) => {
    button.addEventListener("click", closeConversionModal);
  });
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) closeConversionModal();
  });
  backdrop.querySelector("#copy-yaml")?.addEventListener("click", () => {
    if (state.conversion.data?.yaml) copyYaml(state.conversion.data.yaml);
  });
  dialog.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    const focusable = [...dialog.querySelectorAll(
      'button:not([disabled]), summary, [href], [tabindex]:not([tabindex="-1"])'
    )];
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
}

function renderConversionModal() {
  document.querySelector("#conversion-modal")?.remove();
  if (!state.conversion.open) return;
  document.querySelector("#toast-region").insertAdjacentHTML("beforebegin", conversionModalView());
  document.body.classList.add("modal-open");
  const modal = document.querySelector("#conversion-modal");
  hydrateIcons(modal);
  bindConversionModal();
  window.requestAnimationFrame(() => modal.querySelector("#conversion-title")?.focus());
}

async function openCheckConversion(button) {
  const checkRowId = Number(button.dataset.checkConversion);
  conversionTrigger = button;
  state.conversion = {
    open: true,
    loading: true,
    data: null,
    error: "",
    checkRowId,
    checkName: button.dataset.checkName || "Edit check",
    originalInfix: button.querySelector("span")?.textContent || ""
  };
  renderConversionModal();
  try {
    const data = await api.checkConversion(checkRowId);
    if (!state.conversion.open || state.conversion.checkRowId !== checkRowId) return;
    state.conversion.data = data;
  } catch (error) {
    if (!state.conversion.open || state.conversion.checkRowId !== checkRowId) return;
    if (error.payload?.status) {
      state.conversion.data = error.payload;
    } else {
      state.conversion.error = error.message;
    }
  } finally {
    if (state.conversion.open && state.conversion.checkRowId === checkRowId) {
      state.conversion.loading = false;
      renderConversionModal();
    }
  }
}

function dataView() {
  const [title, description] = BOARD_COPY[state.board];
  if (!state.status.ready) {
    main.innerHTML = `
      ${pageHeading(title, description)}
      <section class="table-panel"><div class="empty-state">${icon("upload")}<div><h3>Upload a workbook first</h3><p>This board becomes available after a valid ALS .xlsx workbook is parsed.</p><button class="button button-primary" id="empty-upload" type="button">Go to Upload</button></div></div></section>`;
    document.querySelector("#empty-upload").addEventListener("click", () => navigate("upload"));
    return;
  }
  main.innerHTML = `${pageHeading(title, description)}${toolbarView()}${tableView()}`;
  bindDataControls();
}

function renderCurrentBoard() {
  if (state.board === "upload") uploadView();
  else dataView();
  hydrateIcons(main);
}

function boardParams(allRows = false) {
  const params = new URLSearchParams();
  if (state.board === "crf-book") {
    params.set("form_oid", state.filters.FormOID || "");
    params.set("folder_oid", state.filters.FolderOID || "");
    params.set("exact", String(state.exactMatch));
    if (!allRows) {
      params.set("page", state.page);
      params.set("page_size", 25);
    }
    return params;
  }
  params.set("filters", JSON.stringify(state.filters));
  params.set("active", state.active);
  params.set("exact", String(state.exactMatch));
  if (!allRows) {
    params.set("page", state.page);
    params.set("page_size", state.pageSize);
  }
  if (state.sort) params.set("sort", state.sort);
  params.set("direction", state.direction);
  const columns = selectedColumns();
  if (columns) params.set("columns", columns.join(","));
  return params;
}

function csvUrl() {
  const path = state.board === "crf-book" ? "/api/crf-book/csv" : `/api/data/${state.board}/csv`;
  return `${path}?${boardParams(true)}`;
}

async function loadBoard() {
  const sequence = ++requestSequence;
  const activeFilter = document.activeElement?.dataset?.filter;
  const selectionStart = activeFilter ? document.activeElement.selectionStart : null;
  state.loading = true;
  renderCurrentBoard();
  try {
    const params = boardParams();
    const result = state.board === "crf-book"
      ? await api.crfBook(params)
      : await api.board(state.board, params);
    if (sequence !== requestSequence) return;
    state.result = result;
    if (!state.sort && result.sort) {
      state.sort = result.sort;
      state.direction = result.direction;
    }
  } catch (error) {
    if (sequence !== requestSequence) return;
    showToast(error.message, "error");
  } finally {
    if (sequence === requestSequence) {
      state.loading = false;
      renderCurrentBoard();
      if (activeFilter) {
        const input = document.querySelector(`[data-filter="${CSS.escape(activeFilter)}"]`);
        input?.focus();
        if (selectionStart !== null) input?.setSelectionRange(selectionStart, selectionStart);
      }
    }
  }
}

function queueFilterLoad() {
  window.clearTimeout(filterTimer);
  filterTimer = window.setTimeout(loadBoard, 280);
}

function bindDataControls() {
  document.querySelectorAll("[data-filter]").forEach((input) => input.addEventListener("input", (event) => {
    state.filters[event.target.dataset.filter] = event.target.value;
    state.page = 1;
    const link = document.querySelector("#download-csv");
    if (link) link.href = csvUrl();
    queueFilterLoad();
  }));
  document.querySelector("#active-filter")?.addEventListener("change", (event) => {
    state.active = event.target.value;
    state.page = 1;
    loadBoard();
  });
  document.querySelector("#exact-match")?.addEventListener("change", (event) => {
    state.exactMatch = event.target.checked;
    state.page = 1;
    loadBoard();
  });
  document.querySelector("#reset-filters")?.addEventListener("click", () => {
    state.filters = {};
    state.active = "";
    state.exactMatch = false;
    state.page = 1;
    loadBoard();
  });
  document.querySelectorAll("[data-sort]").forEach((button) => button.addEventListener("click", () => {
    const column = button.dataset.sort;
    state.direction = state.sort === column && state.direction === "asc" ? "desc" : "asc";
    state.sort = column;
    state.page = 1;
    loadBoard();
  }));
  document.querySelectorAll("[data-page]").forEach((button) => button.addEventListener("click", () => {
    state.page = Number(button.dataset.page);
    loadBoard();
  }));
  document.querySelectorAll("[data-dictionary]").forEach((button) => button.addEventListener("click", () => {
    navigate("dictionary-entries", { DataDictionaryName: button.dataset.dictionary });
  }));
  document.querySelectorAll("[data-check-conversion]").forEach((button) => {
    button.addEventListener("click", () => openCheckConversion(button));
  });
  const pickerButton = document.querySelector("#column-picker-button");
  const pickerMenu = document.querySelector("#column-menu");
  pickerButton?.addEventListener("click", () => {
    pickerMenu.hidden = !pickerMenu.hidden;
    pickerButton.setAttribute("aria-expanded", String(!pickerMenu.hidden));
  });
  pickerMenu?.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => checkbox.addEventListener("change", () => {
    if (checkbox.checked) state.optionalGroups.add(checkbox.value);
    else state.optionalGroups.delete(checkbox.value);
    state.page = 1;
    loadBoard();
  }));
}

nav.addEventListener("click", (event) => {
  const button = event.target.closest("[data-board]");
  if (button) navigate(button.dataset.board);
});
document.querySelector("#mobile-menu").addEventListener("click", () => {
  const open = sidebar.classList.toggle("open");
  scrim.hidden = !open;
  document.querySelector("#mobile-menu").setAttribute("aria-expanded", String(open));
});
scrim.addEventListener("click", closeSidebar);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.conversion.open) {
    closeConversionModal();
    return;
  }
  if (event.key === "Escape") closeSidebar();
});

async function initialize() {
  try {
    [state.schema, state.status] = await Promise.all([api.schema(), api.status()]);
    state.board = state.status.ready ? "crf-book" : "upload";
    updateChrome();
    renderCurrentBoard();
    if (state.status.ready) await loadBoard();
  } catch (error) {
    showToast(`The dashboard could not start: ${error.message}`, "error");
    main.innerHTML = `${pageHeading("ALS Dashboard", "The application service is unavailable.")}<div class="notice warning">${icon("warning")}<span>${escapeHtml(error.message)}</span></div>`;
  }
}

hydrateIcons();
initialize();
