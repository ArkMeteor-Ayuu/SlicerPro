/* ================================================
   Grid Cutter – app.js
   ================================================ */
const pickSingleBtn = document.getElementById("pick-single");
const pickMultipleBtn = document.getElementById("pick-multiple");
const pickFolderBtn = document.getElementById("pick-folder");
const processBtn = document.getElementById("process-btn");
const gridSizeSelect = document.getElementById("grid-size");
const customGridRow = document.getElementById("custom-grid-row");
const customRowsInput = document.getElementById("custom-rows");
const customColsInput = document.getElementById("custom-cols");
const archiveToggle = document.getElementById("archive-toggle");
const cellSelectorToggle = document.getElementById("cell-selector-toggle");
const cellSelectorPanel = document.getElementById("cell-selector-panel");
const cellSelectorGrid = document.getElementById("cell-selector-grid");
const cellSelectorNote = document.getElementById("cell-selector-note");

const selectionCount = document.getElementById("selection-count");
const selectionList = document.getElementById("selection-list");
const selectedPreviewGrid = document.getElementById("selected-preview-grid");
const selectedPreviewNote = document.getElementById("selected-preview-note");
const progressFill = document.getElementById("progress-fill");
const statusText = document.getElementById("status-text");
const completionMessage = document.getElementById("completion-message");
const errorList = document.getElementById("error-list");
const outputPreviewGrid = document.getElementById("output-preview-grid");
const outputPreviewNote = document.getElementById("output-preview-note");

const imagesProcessed = document.getElementById("images-processed");
const imagesSuccessful = document.getElementById("images-successful");
const cropsCreated = document.getElementById("crops-created");
const archivedImages = document.getElementById("archived-images");

let pollTimer = null;
const maxSelectionPreview = 24;
const maxOutputPreview = 120;
let isProcessing = false;
let selectedCellIndexes = new Set();
let currentSelectionItems = [];
let selectorEnabledByPath = new Map();

/* ---- Grid helpers ---- */

function getGridDimensions() {
    const val = gridSizeSelect.value;
    if (val === "custom") {
        const r = Math.max(1, Math.min(12, Number(customRowsInput.value) || 2));
        const c = Math.max(1, Math.min(12, Number(customColsInput.value) || 2));
        return { rows: r, cols: c };
    }
    const n = Number(val);
    return { rows: n, cols: n };
}

function getTotalCells() {
    const { rows, cols } = getGridDimensions();
    return rows * cols;
}

function syncCustomGrid() {
    customGridRow.classList.toggle("hidden", gridSizeSelect.value !== "custom");
}

function getSelectorTargetPaths() {
    return currentSelectionItems
        .filter((item) => selectorEnabledByPath.get(item.path))
        .map((item) => item.path);
}

function updateCellSelectorNote() {
    if (!cellSelectorToggle.checked) {
        cellSelectorNote.textContent = "Selector is off. All cells will be cropped.";
        return;
    }
    const total = getTotalCells();
    const sel = selectedCellIndexes.size;
    const targets = getSelectorTargetPaths().length;
    if (targets === 0) {
        cellSelectorNote.textContent = "Selector is on, but no images are marked.";
    } else if (sel === 0) {
        cellSelectorNote.textContent = `Pick at least one cell for ${targets} marked image${targets === 1 ? "" : "s"}.`;
    } else if (sel === total) {
        cellSelectorNote.textContent = `All ${total} cells for ${targets} image${targets === 1 ? "" : "s"}.`;
    } else {
        cellSelectorNote.textContent = `${sel} of ${total} cells for ${targets} image${targets === 1 ? "" : "s"}.`;
    }
}

function renderCellSelectorGrid() {
    const { rows, cols } = getGridDimensions();
    const total = rows * cols;
    selectedCellIndexes = new Set([...selectedCellIndexes].filter((i) => i >= 0 && i < total));
    clearChildren(cellSelectorGrid);
    cellSelectorGrid.style.setProperty("--selector-cols", `${cols}`);

    for (let idx = 0; idx < total; idx++) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "cell-option";
        btn.textContent = `${idx + 1}`;
        btn.disabled = isProcessing;
        if (selectedCellIndexes.has(idx)) btn.classList.add("selected");

        btn.addEventListener("click", () => {
            if (isProcessing) return;
            if (selectedCellIndexes.has(idx)) selectedCellIndexes.delete(idx);
            else selectedCellIndexes.add(idx);
            renderCellSelectorGrid();
        });
        cellSelectorGrid.appendChild(btn);
    }
    updateCellSelectorNote();
}

function syncCellSelectorVisibility() {
    const on = cellSelectorToggle.checked;
    cellSelectorPanel.classList.toggle("hidden", !on);
    if (on) renderCellSelectorGrid();
    else updateCellSelectorNote();
    setButtonsDisabled(isProcessing);
}

/* ---- Rendering helpers ---- */

function getImagePreviewUrl(path) {
    return `/api/image?path=${encodeURIComponent(path)}`;
}

function clearChildren(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
}

function createThumbCard(item, caption) {
    const fig = document.createElement("figure");
    fig.className = "thumb-card";
    const img = document.createElement("img");
    img.src = getImagePreviewUrl(item.path);
    img.alt = item.name;
    img.loading = "lazy";
    const cap = document.createElement("figcaption");
    cap.textContent = caption;
    fig.appendChild(img);
    fig.appendChild(cap);
    return fig;
}

function renderSelectionPreviews(items) {
    clearChildren(selectedPreviewGrid);
    if (!items.length) {
        selectedPreviewNote.textContent = "No selected image previews yet.";
        return;
    }
    items.slice(0, maxSelectionPreview).forEach((item) => {
        selectedPreviewGrid.appendChild(createThumbCard(item, item.name));
    });
    selectedPreviewNote.textContent =
        items.length > maxSelectionPreview
            ? `Showing ${maxSelectionPreview} of ${items.length} selected images.`
            : `Showing ${items.length} selected image preview${items.length === 1 ? "" : "s"}.`;
}

function renderOutputPreviews(items, truncated) {
    clearChildren(outputPreviewGrid);
    if (!items.length) {
        outputPreviewNote.textContent = "No output previews yet.";
        return;
    }
    items.slice(0, maxOutputPreview).forEach((item) => {
        outputPreviewGrid.appendChild(createThumbCard(item, `${item.name} from ${item.source}`));
    });
    outputPreviewNote.textContent = truncated
        ? `Showing first ${items.length} output previews.`
        : `Showing ${items.length} output preview${items.length === 1 ? "" : "s"}.`;
}

function setButtonsDisabled(val) {
    pickSingleBtn.disabled = val;
    pickMultipleBtn.disabled = val;
    pickFolderBtn.disabled = val;
    processBtn.disabled = val;
    gridSizeSelect.disabled = val;
    archiveToggle.disabled = val;
    cellSelectorToggle.disabled = val;
    if (customRowsInput) customRowsInput.disabled = val;
    if (customColsInput) customColsInput.disabled = val;
    document.querySelectorAll(".cell-option").forEach((b) => (b.disabled = val));
    document.querySelectorAll(".remove-btn").forEach((b) => (b.disabled = val));
    document.querySelectorAll(".row-selector-checkbox").forEach((inp) => {
        inp.disabled = val || !cellSelectorToggle.checked;
    });
}

function setStatus(msg) {
    statusText.textContent = msg;
}

/* ---- Selection rendering ---- */

function renderSelection(data) {
    const count = data.count || 0;
    selectionCount.textContent =
        count === 0 ? "No images selected" : count === 1 ? "1 image selected" : `${count} images selected`;

    clearChildren(selectionList);
    const items = (data.items || []);
    currentSelectionItems = items;

    const paths = new Set(items.map((i) => i.path));
    [...selectorEnabledByPath.keys()].forEach((p) => { if (!paths.has(p)) selectorEnabledByPath.delete(p); });

    items.forEach((item) => {
        if (!selectorEnabledByPath.has(item.path)) {
            selectorEnabledByPath.set(item.path, cellSelectorToggle.checked);
        }
        const li = document.createElement("li");
        li.className = "selection-row";

        const label = document.createElement("span");
        label.className = "selection-text";
        label.textContent = `${item.name} (${item.folder})`;

        const actions = document.createElement("div");
        actions.className = "selection-actions";

        const selLabel = document.createElement("label");
        selLabel.className = "row-selector-label";
        const selCb = document.createElement("input");
        selCb.type = "checkbox";
        selCb.className = "row-selector-checkbox";
        selCb.checked = Boolean(selectorEnabledByPath.get(item.path));
        selCb.disabled = isProcessing || !cellSelectorToggle.checked;
        selCb.addEventListener("change", () => {
            selectorEnabledByPath.set(item.path, selCb.checked);
            updateCellSelectorNote();
        });
        const selText = document.createElement("span");
        selText.textContent = "Selector";
        selLabel.appendChild(selCb);
        selLabel.appendChild(selText);

        const removeBtn = document.createElement("button");
        removeBtn.type = "button";
        removeBtn.className = "remove-btn";
        removeBtn.textContent = "Remove";
        removeBtn.disabled = isProcessing;
        removeBtn.addEventListener("click", () => removeSelectionItem(item.path));

        actions.appendChild(selLabel);
        actions.appendChild(removeBtn);
        li.appendChild(label);
        li.appendChild(actions);
        selectionList.appendChild(li);
    });

    renderSelectionPreviews(items);
    updateCellSelectorNote();
}

/* ---- API helpers ---- */

async function fetchJson(url, options = {}) {
    const res = await fetch(url, options);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Request failed");
    return data;
}

async function removeSelectionItem(path) {
    if (isProcessing) return;
    setStatus("Removing…");
    try {
        const data = await fetchJson("/api/selection/remove", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path }),
        });
        renderSelection(data);
        setStatus("Selection updated.");
    } catch (err) {
        setStatus(`Remove error: ${err.message}`);
    }
}

async function pickImages(url) {
    setStatus("Opening picker…");
    completionMessage.textContent = "";
    renderOutputPreviews([], false);
    try {
        const data = await fetchJson(url, { method: "POST" });
        renderSelection(data);
        setStatus("Selection updated.");
    } catch (err) {
        setStatus(`Selection error: ${err.message}`);
    }
}

function resetResultArea() {
    progressFill.style.width = "0%";
    imagesProcessed.textContent = "0";
    imagesSuccessful.textContent = "0";
    cropsCreated.textContent = "0";
    archivedImages.textContent = "0";
    completionMessage.textContent = "";
    clearChildren(errorList);
    renderOutputPreviews([], false);
}

function renderStatus(data) {
    progressFill.style.width = `${data.progress || 0}%`;
    imagesProcessed.textContent = `${data.processed_images ?? 0}`;
    imagesSuccessful.textContent = `${data.successful_images ?? 0}`;
    cropsCreated.textContent = `${data.total_crops ?? 0}`;
    archivedImages.textContent = `${data.archived_images ?? 0}`;

    const total = data.total_images ?? 0;
    if (data.status === "running") setStatus(`Processing… ${data.processed_images}/${total}`);
    else if (data.status === "queued") setStatus("Waiting to start…");
    else if (data.status === "done") {
        setStatus("Completed.");
        completionMessage.textContent = data.message || "Processing completed.";
    }

    clearChildren(errorList);
    (data.errors || []).forEach((msg) => {
        const li = document.createElement("li");
        li.textContent = msg;
        errorList.appendChild(li);
    });
    renderOutputPreviews(data.output_items || [], data.output_preview_truncated || false);
}

async function processImages() {
    const selectorPaths = cellSelectorToggle.checked ? getSelectorTargetPaths() : [];
    if (cellSelectorToggle.checked && selectorPaths.length > 0 && selectedCellIndexes.size === 0) {
        setStatus("Selector is enabled. Please select at least one cell.");
        return;
    }

    resetResultArea();
    isProcessing = true;
    setButtonsDisabled(true);
    setStatus("Submitting job…");

    const { rows, cols } = getGridDimensions();
    const dest = archiveToggle.checked ? "archive" : "same";
    const useSel = cellSelectorToggle.checked;
    const cells =
        useSel && selectorPaths.length > 0 ? [...selectedCellIndexes].sort((a, b) => a - b) : [];

    try {
        const data = await fetchJson("/api/process", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                grid_rows: rows,
                grid_cols: cols,
                original_destination: dest,
                use_cell_selector: useSel,
                selected_cells: cells,
                selector_paths: selectorPaths,
            }),
        });
        startPolling(data.job_id);
    } catch (err) {
        isProcessing = false;
        setButtonsDisabled(false);
        setStatus(`Processing error: ${err.message}`);
    }
}

function startPolling(jobId) {
    if (pollTimer) clearInterval(pollTimer);
    const tick = async () => {
        try {
            const data = await fetchJson(`/api/status/${jobId}`);
            renderStatus(data);
            if (data.status === "done") {
                clearInterval(pollTimer);
                pollTimer = null;
                isProcessing = false;
                setButtonsDisabled(false);
                loadSelectionOnStart();
            }
        } catch (err) {
            clearInterval(pollTimer);
            pollTimer = null;
            isProcessing = false;
            setButtonsDisabled(false);
            setStatus(`Status error: ${err.message}`);
        }
    };
    tick();
    pollTimer = setInterval(tick, 600);
}

async function loadSelectionOnStart() {
    try {
        const data = await fetchJson("/api/selection");
        renderSelection(data);
    } catch {
        setStatus("Unable to load initial selection.");
    }
}

/* ---- Event listeners ---- */
pickSingleBtn.addEventListener("click", () => pickImages("/api/select/single"));
pickMultipleBtn.addEventListener("click", () => pickImages("/api/select/multiple"));
pickFolderBtn.addEventListener("click", () => pickImages("/api/select/folder"));
processBtn.addEventListener("click", processImages);
cellSelectorToggle.addEventListener("change", syncCellSelectorVisibility);
gridSizeSelect.addEventListener("change", () => {
    syncCustomGrid();
    renderCellSelectorGrid();
    syncCellSelectorVisibility();
});
if (customRowsInput) customRowsInput.addEventListener("change", () => { renderCellSelectorGrid(); });
if (customColsInput) customColsInput.addEventListener("change", () => { renderCellSelectorGrid(); });

syncCustomGrid();
syncCellSelectorVisibility();
loadSelectionOnStart();
