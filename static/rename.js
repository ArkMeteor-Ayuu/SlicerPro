/* ================================================
   Batch Rename – rename.js
   ================================================ */
const pickSingleBtn = document.getElementById("rename-pick-single");
const pickMultipleBtn = document.getElementById("rename-pick-multiple");
const pickFolderBtn = document.getElementById("rename-pick-folder");
const processBtn = document.getElementById("rename-process-btn");
const templateInput = document.getElementById("rename-template");
const startNumberInput = document.getElementById("rename-start-number");

const selectionCount = document.getElementById("rename-selection-count");
const selectionList = document.getElementById("rename-selection-list");
const progressFill = document.getElementById("rename-progress-fill");
const statusText = document.getElementById("rename-status-text");
const completionMessage = document.getElementById("rename-completion-message");
const errorList = document.getElementById("rename-error-list");

const totalImages = document.getElementById("rename-total-images");
const renamedCount = document.getElementById("rename-renamed-count");
const unchangedCount = document.getElementById("rename-unchanged-count");
const previewNote = document.getElementById("rename-preview-note");
const previewList = document.getElementById("rename-preview-list");

let pollTimer = null;
let isRenaming = false;

function setControlsDisabled(val) {
    pickSingleBtn.disabled = val;
    pickMultipleBtn.disabled = val;
    pickFolderBtn.disabled = val;
    processBtn.disabled = val;
    templateInput.disabled = val;
    startNumberInput.disabled = val;
    document.querySelectorAll(".remove-btn").forEach((b) => (b.disabled = val));
}

function setStatus(msg) { statusText.textContent = msg; }

function clearChildren(el) { while (el.firstChild) el.removeChild(el.firstChild); }

function renderRenamePreview(items) {
    clearChildren(previewList);
    if (!items.length) { previewNote.textContent = "No rename preview yet."; return; }
    items.forEach((item) => {
        const li = document.createElement("li");
        li.textContent = `${item.from} → ${item.to} (${item.folder})`;
        previewList.appendChild(li);
    });
    previewNote.textContent = `Showing ${items.length} rename result${items.length === 1 ? "" : "s"}.`;
}

function renderSelection(data) {
    const count = data.count || 0;
    selectionCount.textContent =
        count === 0 ? "No files selected" : count === 1 ? "1 file selected" : `${count} files selected`;

    clearChildren(selectionList);
    const items = data.items || [];
    items.slice(0, 30).forEach((item) => {
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
        removeBtn.disabled = isRenaming;
        removeBtn.addEventListener("click", () => removeSelectionItem(item.path));
        actions.appendChild(removeBtn);
        li.appendChild(label);
        li.appendChild(actions);
        selectionList.appendChild(li);
    });
    if (items.length > 30) {
        const li = document.createElement("li");
        li.textContent = `…and ${items.length - 30} more`;
        selectionList.appendChild(li);
    }
}

function resetResultArea() {
    progressFill.style.width = "0%";
    totalImages.textContent = "0";
    renamedCount.textContent = "0";
    unchangedCount.textContent = "0";
    completionMessage.textContent = "";
    clearChildren(errorList);
    renderRenamePreview([]);
}

function renderStatus(data) {
    progressFill.style.width = `${data.progress || 0}%`;
    totalImages.textContent = `${data.total_images ?? 0}`;
    renamedCount.textContent = `${data.renamed_count ?? 0}`;
    unchangedCount.textContent = `${data.unchanged_count ?? 0}`;
    if (data.status === "running") setStatus("Renaming files…");
    else if (data.status === "queued") setStatus("Waiting to start…");
    else if (data.status === "done") {
        setStatus("Completed.");
        completionMessage.textContent = data.message || "Rename completed.";
    }
    clearChildren(errorList);
    (data.errors || []).forEach((msg) => {
        const li = document.createElement("li");
        li.textContent = msg;
        errorList.appendChild(li);
    });
    renderRenamePreview(data.preview_items || []);
}

async function fetchJson(url, options = {}) {
    const res = await fetch(url, options);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Request failed");
    return data;
}

async function pickFiles(url) {
    setStatus("Opening picker…");
    try {
        const data = await fetchJson(url, { method: "POST" });
        renderSelection(data);
        setStatus("Selection updated.");
    } catch (err) {
        setStatus(`Selection error: ${err.message}`);
    }
}

async function removeSelectionItem(path) {
    if (isRenaming) return;
    setStatus("Removing…");
    try {
        const data = await fetchJson("/api/rename/selection/remove", {
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

async function processRename() {
    const template = templateInput.value.trim();
    const startNumber = Number(startNumberInput.value || "1");
    if (!template.includes("{no}")) { setStatus("Template must include {no}."); return; }
    if (!Number.isInteger(startNumber) || startNumber < 1) { setStatus("Start number must be ≥ 1."); return; }

    resetResultArea();
    isRenaming = true;
    setControlsDisabled(true);
    setStatus("Submitting rename job…");

    try {
        const data = await fetchJson("/api/rename/process", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ template, start_number: startNumber }),
        });
        startPolling(data.job_id);
    } catch (err) {
        isRenaming = false;
        setControlsDisabled(false);
        setStatus(`Rename error: ${err.message}`);
    }
}

function startPolling(jobId) {
    if (pollTimer) clearInterval(pollTimer);
    const tick = async () => {
        try {
            const data = await fetchJson(`/api/rename/status/${jobId}`);
            renderStatus(data);
            if (data.status === "done") {
                clearInterval(pollTimer);
                pollTimer = null;
                isRenaming = false;
                setControlsDisabled(false);
                loadSelectionOnStart();
            }
        } catch (err) {
            clearInterval(pollTimer);
            pollTimer = null;
            isRenaming = false;
            setControlsDisabled(false);
            setStatus(`Status error: ${err.message}`);
        }
    };
    tick();
    pollTimer = setInterval(tick, 600);
}

async function loadSelectionOnStart() {
    try {
        const data = await fetchJson("/api/rename/selection");
        renderSelection(data);
    } catch {
        setStatus("Unable to load initial selection.");
    }
}

pickSingleBtn.addEventListener("click", () => pickFiles("/api/rename/select/single"));
pickMultipleBtn.addEventListener("click", () => pickFiles("/api/rename/select/multiple"));
pickFolderBtn.addEventListener("click", () => pickFiles("/api/rename/select/folder"));
processBtn.addEventListener("click", processRename);

loadSelectionOnStart();
