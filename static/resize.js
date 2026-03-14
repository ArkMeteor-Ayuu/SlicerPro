/* ================================================
   Image Resizer – resize.js
   ================================================ */
const pickSingleBtn = document.getElementById("resize-pick-single");
const pickMultipleBtn = document.getElementById("resize-pick-multiple");
const pickFolderBtn = document.getElementById("resize-pick-folder");
const processBtn = document.getElementById("resize-process-btn");

const modeSelect = document.getElementById("resize-mode");
const modePercentage = document.getElementById("mode-percentage");
const modeMaxEdge = document.getElementById("mode-max-edge");
const modeExact = document.getElementById("mode-exact");
const percentageInput = document.getElementById("resize-percentage");
const maxEdgeInput = document.getElementById("resize-max-edge");
const widthInput = document.getElementById("resize-width");
const heightInput = document.getElementById("resize-height");
const aspectCheckbox = document.getElementById("resize-aspect");
const qualitySlider = document.getElementById("resize-quality");
const qualityValue = document.getElementById("resize-quality-value");

const selectionCount = document.getElementById("resize-selection-count");
const selectionList = document.getElementById("resize-selection-list");
const selectedPreviewGrid = document.getElementById("resize-selected-preview-grid");
const selectedPreviewNote = document.getElementById("resize-selected-preview-note");
const progressFill = document.getElementById("resize-progress-fill");
const statusText = document.getElementById("resize-status-text");
const completionMessage = document.getElementById("resize-completion-message");
const errorList = document.getElementById("resize-error-list");
const totalEl = document.getElementById("resize-total");
const successEl = document.getElementById("resize-success");
const errCountEl = document.getElementById("resize-errors-count");
const outputPreviewGrid = document.getElementById("resize-output-preview-grid");
const outputPreviewNote = document.getElementById("resize-output-preview-note");

let pollTimer = null;
let isProcessing = false;

/* ---- Mode switch ---- */
function syncMode() {
    const m = modeSelect.value;
    modePercentage.classList.toggle("hidden", m !== "percentage");
    modeMaxEdge.classList.toggle("hidden", m !== "max_edge");
    modeExact.classList.toggle("hidden", m !== "exact");
}
modeSelect.addEventListener("change", syncMode);
syncMode();

qualitySlider.addEventListener("input", () => {
    qualityValue.textContent = qualitySlider.value;
});

/* ---- Helpers ---- */
function clearChildren(el) { while (el.firstChild) el.removeChild(el.firstChild); }

function setStatus(msg) { statusText.textContent = msg; }

function setControlsDisabled(val) {
    pickSingleBtn.disabled = val;
    pickMultipleBtn.disabled = val;
    pickFolderBtn.disabled = val;
    processBtn.disabled = val;
    modeSelect.disabled = val;
    percentageInput.disabled = val;
    maxEdgeInput.disabled = val;
    widthInput.disabled = val;
    heightInput.disabled = val;
    aspectCheckbox.disabled = val;
    qualitySlider.disabled = val;
    document.querySelectorAll(".remove-btn").forEach((b) => (b.disabled = val));
}

function getImagePreviewUrl(path) {
    return `/api/image?path=${encodeURIComponent(path)}`;
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
    if (!items.length) { selectedPreviewNote.textContent = "No selected image previews yet."; return; }
    items.slice(0, 24).forEach((item) => {
        selectedPreviewGrid.appendChild(createThumbCard(item, item.name));
    });
    selectedPreviewNote.textContent = items.length > 24
        ? `Showing 24 of ${items.length} selected images.`
        : `Showing ${items.length} selected image preview${items.length === 1 ? "" : "s"}.`;
}

function renderOutputPreviews(items) {
    clearChildren(outputPreviewGrid);
    if (!items.length) { outputPreviewNote.textContent = "No output previews yet."; return; }
    items.slice(0, 120).forEach((item) => {
        outputPreviewGrid.appendChild(createThumbCard(item, `${item.name} from ${item.source}`));
    });
    outputPreviewNote.textContent = `Showing ${items.length} output preview${items.length === 1 ? "" : "s"}.`;
}

function renderSelection(data) {
    const count = data.count || 0;
    selectionCount.textContent =
        count === 0 ? "No images selected" : count === 1 ? "1 image selected" : `${count} images selected`;

    clearChildren(selectionList);
    (data.items || []).slice(0, 30).forEach((item) => {
        const li = document.createElement("li");
        li.className = "selection-row";
        const label = document.createElement("span");
        label.className = "selection-text";
        label.textContent = `${item.name} (${item.folder})`;
        const actions = document.createElement("div");
        actions.className = "selection-actions";
        const removeBtn = document.createElement("button");
        removeBtn.type = "button";
        removeBtn.className = "remove-btn";
        removeBtn.textContent = "Remove";
        removeBtn.disabled = isProcessing;
        removeBtn.addEventListener("click", () => removeItem(item.path));
        actions.appendChild(removeBtn);
        li.appendChild(label);
        li.appendChild(actions);
        selectionList.appendChild(li);
    });
    renderSelectionPreviews(data.items || []);
}

function resetResultArea() {
    progressFill.style.width = "0%";
    totalEl.textContent = "0";
    successEl.textContent = "0";
    errCountEl.textContent = "0";
    completionMessage.textContent = "";
    clearChildren(errorList);
    renderOutputPreviews([]);
}

function renderStatus(data) {
    progressFill.style.width = `${data.progress || 0}%`;
    totalEl.textContent = `${data.total_images ?? 0}`;
    successEl.textContent = `${data.successful_images ?? 0}`;
    const errs = data.errors || [];
    errCountEl.textContent = `${errs.length}`;
    if (data.status === "running") setStatus(`Resizing… ${data.processed_images}/${data.total_images}`);
    else if (data.status === "queued") setStatus("Waiting to start…");
    else if (data.status === "done") {
        setStatus("Completed.");
        completionMessage.textContent = data.message || "Resize completed.";
    }
    clearChildren(errorList);
    errs.forEach((msg) => {
        const li = document.createElement("li");
        li.textContent = msg;
        errorList.appendChild(li);
    });
    renderOutputPreviews(data.output_items || []);
}

async function fetchJson(url, options = {}) {
    const res = await fetch(url, options);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Request failed");
    return data;
}

async function pickImages(url) {
    setStatus("Opening picker…");
    try {
        const data = await fetchJson(url, { method: "POST" });
        renderSelection(data);
        setStatus("Selection updated.");
    } catch (err) {
        setStatus(`Selection error: ${err.message}`);
    }
}

async function removeItem(path) {
    if (isProcessing) return;
    setStatus("Removing…");
    try {
        const data = await fetchJson("/api/resize/selection/remove", {
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

async function processResize() {
    resetResultArea();
    isProcessing = true;
    setControlsDisabled(true);
    setStatus("Submitting resize job…");

    const payload = {
        mode: modeSelect.value,
        percentage: Number(percentageInput.value || 50),
        max_edge: Number(maxEdgeInput.value || 1024),
        width: Number(widthInput.value || 800),
        height: Number(heightInput.value || 600),
        maintain_aspect: aspectCheckbox.checked,
        quality: Number(qualitySlider.value || 90),
    };

    try {
        const data = await fetchJson("/api/resize/process", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        startPolling(data.job_id);
    } catch (err) {
        isProcessing = false;
        setControlsDisabled(false);
        setStatus(`Resize error: ${err.message}`);
    }
}

function startPolling(jobId) {
    if (pollTimer) clearInterval(pollTimer);
    const tick = async () => {
        try {
            const data = await fetchJson(`/api/resize/status/${jobId}`);
            renderStatus(data);
            if (data.status === "done") {
                clearInterval(pollTimer);
                pollTimer = null;
                isProcessing = false;
                setControlsDisabled(false);
                loadSelection();
            }
        } catch (err) {
            clearInterval(pollTimer);
            pollTimer = null;
            isProcessing = false;
            setControlsDisabled(false);
            setStatus(`Status error: ${err.message}`);
        }
    };
    tick();
    pollTimer = setInterval(tick, 600);
}

async function loadSelection() {
    try {
        const data = await fetchJson("/api/resize/selection");
        renderSelection(data);
    } catch {
        setStatus("Unable to load initial selection.");
    }
}

pickSingleBtn.addEventListener("click", () => pickImages("/api/resize/select/single"));
pickMultipleBtn.addEventListener("click", () => pickImages("/api/resize/select/multiple"));
pickFolderBtn.addEventListener("click", () => pickImages("/api/resize/select/folder"));
processBtn.addEventListener("click", processResize);

loadSelection();
