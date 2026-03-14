from __future__ import annotations

import shutil
import threading
import uuid
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_file
from PIL import Image, UnidentifiedImageError

try:
    import tkinter as tk
    from tkinter import filedialog
except Exception:  # pragma: no cover
    tk = None
    filedialog = None


app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_RENAME_EXTENSIONS = ALLOWED_EXTENSIONS | {".txt"}
MAX_OUTPUT_PREVIEW_ITEMS = 120
DESTINATION_SAME = "same"
DESTINATION_ARCHIVE = "archive"
ALLOWED_DESTINATIONS = {DESTINATION_SAME, DESTINATION_ARCHIVE}
ARCHIVE_DIRECTORY = Path(r"E:\testing 21\images\archive")

RESIZE_MODE_PERCENTAGE = "percentage"
RESIZE_MODE_MAX_EDGE = "max_edge"
RESIZE_MODE_EXACT = "exact"
ALLOWED_RESIZE_MODES = {RESIZE_MODE_PERCENTAGE, RESIZE_MODE_MAX_EDGE, RESIZE_MODE_EXACT}

CONVERT_FORMATS = {"PNG": "PNG", "JPEG": "JPEG", "WEBP": "WEBP"}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
class SelectionQueue:
    """Thread-safe ordered list of unique file paths."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._paths: list[str] = []

    def append(self, paths: list[str]) -> list[str]:
        unique = normalize_paths(paths)
        if not unique:
            return self.snapshot()
        with self._lock:
            seen = set(self._paths)
            for p in unique:
                if p not in seen:
                    self._paths.append(p)
                    seen.add(p)
            return list(self._paths)

    def remove_one(self, path: str) -> bool:
        normalized = normalize_paths([path])
        if not normalized:
            return False
        target = normalized[0]
        with self._lock:
            before = len(self._paths)
            self._paths[:] = [p for p in self._paths if p != target]
            return len(self._paths) < before

    def remove_many(self, paths: list[str]) -> int:
        normalized = set(normalize_paths(paths))
        if not normalized:
            return 0
        with self._lock:
            before = len(self._paths)
            self._paths[:] = [p for p in self._paths if p not in normalized]
            return before - len(self._paths)

    def snapshot(self) -> list[str]:
        with self._lock:
            return list(self._paths)


class JobStore:
    """Thread-safe job dictionary."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def create(self, job_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._jobs[job_id] = payload

    def update(self, job_id: str, **kwargs: Any) -> None:
        with self._lock:
            self._jobs[job_id].update(kwargs)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            current = self._jobs.get(job_id)
            if not current:
                return None
            return {k: (list(v) if isinstance(v, list) else v) for k, v in current.items()}


# Per-tool state
crop_queue = SelectionQueue()
crop_jobs = JobStore()
rename_queue = SelectionQueue()
rename_jobs = JobStore()
resize_queue = SelectionQueue()
resize_jobs = JobStore()
convert_queue = SelectionQueue()
convert_jobs = JobStore()

dialog_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Path / file helpers
# ---------------------------------------------------------------------------
def is_supported_image(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS


def is_supported_rename_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in ALLOWED_RENAME_EXTENSIONS


def to_response_paths(paths: list[str]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in paths:
        p = Path(item)
        result.append({"name": p.name, "folder": str(p.parent), "path": str(p)})
    return result


def normalize_paths(paths: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        if not raw:
            continue
        try:
            p = str(Path(raw).expanduser().resolve())
        except OSError:
            continue
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def queue_response(queue: SelectionQueue) -> dict[str, Any]:
    paths = queue.snapshot()
    return {"count": len(paths), "items": to_response_paths(paths)}


# ---------------------------------------------------------------------------
# File pickers
# ---------------------------------------------------------------------------
def open_tk() -> Any:
    if tk is None:
        raise RuntimeError("tkinter is not available in this Python environment.")
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.update()
    return root


def pick_single_file() -> list[str]:
    with dialog_lock:
        root = open_tk()
        try:
            path = filedialog.askopenfilename(
                title="Select one image",
                filetypes=[("Images", "*.png *.jpg *.jpeg *.webp")],
            )
            return [path] if path else []
        finally:
            root.destroy()


def pick_multiple_files() -> list[str]:
    with dialog_lock:
        root = open_tk()
        try:
            paths = filedialog.askopenfilenames(
                title="Select image files",
                filetypes=[("Images", "*.png *.jpg *.jpeg *.webp")],
            )
            return list(paths)
        finally:
            root.destroy()


def pick_folder_files() -> list[str]:
    with dialog_lock:
        root = open_tk()
        try:
            folder = filedialog.askdirectory(title="Select folder with images")
        finally:
            root.destroy()
    if not folder:
        return []
    return [
        str(p.resolve())
        for p in sorted(Path(folder).rglob("*"))
        if is_supported_image(p)
    ]


def pick_single_rename_file() -> list[str]:
    with dialog_lock:
        root = open_tk()
        try:
            path = filedialog.askopenfilename(
                title="Select one file",
                filetypes=[
                    ("Supported files", "*.png *.jpg *.jpeg *.webp *.txt"),
                    ("Images", "*.png *.jpg *.jpeg *.webp"),
                    ("Text files", "*.txt"),
                ],
            )
            return [path] if path else []
        finally:
            root.destroy()


def pick_multiple_rename_files() -> list[str]:
    with dialog_lock:
        root = open_tk()
        try:
            paths = filedialog.askopenfilenames(
                title="Select files",
                filetypes=[
                    ("Supported files", "*.png *.jpg *.jpeg *.webp *.txt"),
                    ("Images", "*.png *.jpg *.jpeg *.webp"),
                    ("Text files", "*.txt"),
                ],
            )
            return list(paths)
        finally:
            root.destroy()


def pick_rename_folder_files() -> list[str]:
    with dialog_lock:
        root = open_tk()
        try:
            folder = filedialog.askdirectory(title="Select folder with supported files")
        finally:
            root.destroy()
    if not folder:
        return []
    return [
        str(p.resolve())
        for p in sorted(Path(folder).rglob("*"))
        if is_supported_rename_file(p)
    ]


# ---------------------------------------------------------------------------
# Crop helpers
# ---------------------------------------------------------------------------
def lowest_available_number(used: set[int]) -> int:
    n = 1
    while n in used:
        n += 1
    return n


def next_image_numbers(directory: Path) -> set[int]:
    used: set[int] = set()
    for fp in directory.iterdir():
        if fp.is_file() and fp.stem.isdigit() and fp.suffix.lower() in ALLOWED_EXTENSIONS:
            used.add(int(fp.stem))
    return used


def crop_one_image(
    image_path: Path,
    grid_rows: int,
    grid_cols: int,
    selected_cells: set[int] | None = None,
) -> list[str]:
    with Image.open(image_path) as img:
        w, h = img.size
        tw = w // grid_cols
        th = h // grid_rows
        if tw <= 0 or th <= 0:
            raise ValueError(
                f"Image {image_path.name} is too small for a {grid_rows}x{grid_cols} split."
            )

        output_dir = image_path.parent
        used = next_image_numbers(output_dir)
        num = lowest_available_number(used)
        output_paths: list[str] = []

        for row in range(grid_rows):
            for col in range(grid_cols):
                idx = row * grid_cols + col
                if selected_cells is not None and idx not in selected_cells:
                    continue
                left = col * tw
                upper = row * th
                cropped = img.crop((left, upper, left + tw, upper + th))
                while num in used:
                    num += 1
                out = output_dir / f"{num}.png"
                cropped.save(out, format="PNG", optimize=True)
                used.add(num)
                num += 1
                output_paths.append(str(out))
        return output_paths


def get_unique_destination_path(directory: Path, file_name: str) -> Path:
    candidate = directory / file_name
    if not candidate.exists():
        return candidate
    base = Path(file_name).stem
    ext = Path(file_name).suffix
    idx = 1
    while True:
        candidate = directory / f"{base}_{idx}{ext}"
        if not candidate.exists():
            return candidate
        idx += 1


def move_original_to_archive(image_path: Path) -> Path:
    archive_dir = ARCHIVE_DIRECTORY.resolve()
    archive_dir.mkdir(parents=True, exist_ok=True)
    if image_path.parent.resolve() == archive_dir:
        return image_path
    dest = get_unique_destination_path(archive_dir, image_path.name)
    return Path(shutil.move(str(image_path), str(dest)))


def parse_selected_cells(
    grid_rows: int,
    grid_cols: int,
    require: bool,
    raw_cells: Any,
) -> list[int]:
    if not require:
        return []
    if not isinstance(raw_cells, list):
        raise ValueError("Selected cells must be a list.")
    max_cells = grid_rows * grid_cols
    parsed: set[int] = set()
    for item in raw_cells:
        try:
            idx = int(item)
        except (TypeError, ValueError):
            raise ValueError("Selected cells must contain numeric indexes.") from None
        if idx < 0 or idx >= max_cells:
            raise ValueError("Selected cell index is out of range for the selected grid.")
        parsed.add(idx)
    if not parsed:
        raise ValueError("Select at least one cell when selector mode is enabled.")
    return sorted(parsed)


def parse_selector_paths(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("Selector paths must be a list.")
    return normalize_paths([str(item) for item in raw if item is not None])


# ---------------------------------------------------------------------------
# Crop worker
# ---------------------------------------------------------------------------
def process_images_worker(
    job_id: str,
    image_paths: list[str],
    grid_rows: int,
    grid_cols: int,
    original_destination: str,
    selected_cells: list[int],
    selector_paths: list[str],
) -> None:
    total = len(image_paths)
    processed = successful = total_crops = archived = 0
    errors: list[str] = []
    output_items: list[dict[str, str]] = []
    truncated = False
    successful_paths: list[str] = []
    cell_set = set(selected_cells) if selected_cells else None
    selector_set = set(selector_paths)

    crop_jobs.update(job_id, status="running", progress=0)

    for raw in image_paths:
        ip = Path(raw)
        try:
            if not is_supported_image(ip):
                raise ValueError(f"Unsupported file type: {ip.name}")
            apply = cell_set is not None and str(ip) in selector_set
            outputs = crop_one_image(ip, grid_rows, grid_cols, cell_set if apply else None)
            total_crops += len(outputs)
            successful += 1
            successful_paths.append(str(ip))
            for out in outputs:
                if len(output_items) >= MAX_OUTPUT_PREVIEW_ITEMS:
                    truncated = True
                    continue
                op = Path(out)
                output_items.append({
                    "name": op.name, "folder": str(op.parent),
                    "path": str(op), "source": ip.name,
                })
            if original_destination == DESTINATION_ARCHIVE:
                try:
                    move_original_to_archive(ip)
                    archived += 1
                except (PermissionError, OSError) as exc:
                    errors.append(f"{ip.name}: Cropped, but archive move failed - {exc}")
        except (FileNotFoundError, PermissionError, ValueError, UnidentifiedImageError) as exc:
            errors.append(f"{ip.name}: {exc}")
        except Exception as exc:
            errors.append(f"{ip.name}: Unexpected error - {exc}")
        finally:
            processed += 1
            crop_jobs.update(
                job_id,
                processed_images=processed, successful_images=successful,
                total_crops=total_crops, progress=int(processed / total * 100) if total else 100,
                errors=list(errors), output_items=list(output_items),
                output_preview_truncated=truncated, archived_images=archived,
            )

    crop_queue.remove_many(successful_paths)
    msg = f"Completed. Processed {successful}/{total} images, created {total_crops} crops."
    if original_destination == DESTINATION_ARCHIVE:
        msg += f" Archived: {archived}."
    crop_jobs.update(job_id, status="done", progress=100, message=msg)


# ---------------------------------------------------------------------------
# Rename helpers
# ---------------------------------------------------------------------------
def render_name_from_template(template: str, number: int, source_path: Path) -> str:
    name = template.replace("{no}", str(number)).strip()
    if not name:
        raise ValueError("Rename template produced an empty filename.")
    if Path(name).name != name:
        raise ValueError("Rename template must be a filename only, without folder separators.")
    if not Path(name).suffix:
        name = f"{name}{source_path.suffix.lower()}"
    return name


def build_rename_plan(
    image_paths: list[str], rename_template: str, start_number: int,
) -> list[tuple[Path, Path]]:
    if "{no}" not in rename_template:
        raise ValueError("Rename template must include '{no}'.")
    if start_number < 1:
        raise ValueError("Start number must be 1 or greater.")

    plan: list[tuple[Path, Path]] = []
    for offset, raw in enumerate(image_paths):
        src = Path(raw)
        if not is_supported_rename_file(src):
            raise ValueError(f"Unsupported file type: {src.name}")
        if not src.exists():
            raise FileNotFoundError(f"File not found: {src}")
        target_name = render_name_from_template(rename_template, start_number + offset, src)
        plan.append((src, src.parent / target_name))

    owners: dict[Path, Path] = {}
    for src, tgt in plan:
        existing = owners.get(tgt)
        if existing is not None and existing != src:
            raise ValueError(f"Duplicate rename target: {tgt.name}")
        owners[tgt] = src

    sources = {src for src, _ in plan}
    for _, tgt in plan:
        if tgt.exists() and tgt not in sources:
            raise FileExistsError(f"Target already exists: {tgt}")
    return plan


def execute_rename_plan(plan: list[tuple[Path, Path]]) -> list[tuple[Path, Path]]:
    staged: list[tuple[Path, Path, Path]] = []
    for i, (src, tgt) in enumerate(plan):
        tmp = get_unique_destination_path(src.parent, f".__rename_tmp__{uuid.uuid4().hex}_{i}{src.suffix}")
        src.rename(tmp)
        staged.append((src, tgt, tmp))
    try:
        for _, tgt, tmp in staged:
            tmp.rename(tgt)
    except Exception:
        for src, tgt, tmp in reversed(staged):
            try:
                if tmp.exists():
                    tmp.rename(src)
                elif tgt.exists():
                    tgt.rename(src)
            except Exception:
                pass
        raise
    return [(src, tgt) for src, tgt, _ in staged]


def process_rename_worker(
    job_id: str, paths: list[str], template: str, start: int,
) -> None:
    total = len(paths)
    rename_jobs.update(job_id, status="running", progress=0)
    try:
        plan = build_rename_plan(paths, template, start)
        pairs = execute_rename_plan(plan)
        renamed = sum(1 for s, t in pairs if s != t)
        unchanged = total - renamed
        rename_queue.remove_many([str(s) for s, _ in pairs])
        preview: list[dict[str, str]] = [
            {"from": s.name, "to": t.name, "folder": str(t.parent)}
            for s, t in pairs[:120]
        ]
        rename_jobs.update(
            job_id, status="done", progress=100,
            message=f"Completed. Processed {total} files. Renamed: {renamed}. Unchanged: {unchanged}.",
            processed_images=total, renamed_count=renamed, unchanged_count=unchanged,
            errors=[], preview_items=preview,
        )
    except Exception as exc:
        rename_jobs.update(
            job_id, status="done", progress=100, message="Rename failed.",
            processed_images=0, renamed_count=0, unchanged_count=0,
            errors=[str(exc)], preview_items=[],
        )


# ---------------------------------------------------------------------------
# Resize helpers
# ---------------------------------------------------------------------------
def resize_one_image(
    image_path: Path,
    mode: str,
    percentage: int,
    max_edge: int,
    width: int,
    height: int,
    maintain_aspect: bool,
    quality: int,
) -> str:
    with Image.open(image_path) as img:
        orig_w, orig_h = img.size

        if mode == RESIZE_MODE_PERCENTAGE:
            new_w = max(1, int(orig_w * percentage / 100))
            new_h = max(1, int(orig_h * percentage / 100))
        elif mode == RESIZE_MODE_MAX_EDGE:
            longest = max(orig_w, orig_h)
            if longest <= max_edge:
                new_w, new_h = orig_w, orig_h
            else:
                scale = max_edge / longest
                new_w = max(1, int(orig_w * scale))
                new_h = max(1, int(orig_h * scale))
        elif mode == RESIZE_MODE_EXACT:
            if maintain_aspect:
                img_copy = img.copy()
                img_copy.thumbnail((width, height), Image.LANCZOS)
                new_w, new_h = img_copy.size
            else:
                new_w, new_h = width, height
        else:
            raise ValueError(f"Unknown resize mode: {mode}")

        resized = img.resize((new_w, new_h), Image.LANCZOS)

        ext = image_path.suffix.lower()
        out_name = f"{image_path.stem}_resized{ext}"
        out_path = get_unique_destination_path(image_path.parent, out_name)

        save_kwargs: dict[str, Any] = {}
        if ext in (".jpg", ".jpeg"):
            if resized.mode == "RGBA":
                resized = resized.convert("RGB")
            save_kwargs["quality"] = quality
            save_kwargs["optimize"] = True
        elif ext == ".webp":
            save_kwargs["quality"] = quality
        elif ext == ".png":
            save_kwargs["optimize"] = True

        resized.save(out_path, **save_kwargs)
        return str(out_path)


def process_resize_worker(
    job_id: str,
    paths: list[str],
    mode: str,
    percentage: int,
    max_edge: int,
    width: int,
    height: int,
    maintain_aspect: bool,
    quality: int,
) -> None:
    total = len(paths)
    processed = successful = 0
    errors: list[str] = []
    output_items: list[dict[str, str]] = []

    resize_jobs.update(job_id, status="running", progress=0)

    for raw in paths:
        ip = Path(raw)
        try:
            if not is_supported_image(ip):
                raise ValueError(f"Unsupported: {ip.name}")
            out = resize_one_image(ip, mode, percentage, max_edge, width, height, maintain_aspect, quality)
            successful += 1
            op = Path(out)
            if len(output_items) < MAX_OUTPUT_PREVIEW_ITEMS:
                output_items.append({
                    "name": op.name, "folder": str(op.parent),
                    "path": str(op), "source": ip.name,
                })
        except Exception as exc:
            errors.append(f"{ip.name}: {exc}")
        finally:
            processed += 1
            resize_jobs.update(
                job_id,
                processed_images=processed, successful_images=successful,
                progress=int(processed / total * 100) if total else 100,
                errors=list(errors), output_items=list(output_items),
            )

    resize_queue.remove_many(paths)
    resize_jobs.update(
        job_id, status="done", progress=100,
        message=f"Completed. Resized {successful}/{total} images.",
    )


# ---------------------------------------------------------------------------
# Convert helpers
# ---------------------------------------------------------------------------
def convert_one_image(image_path: Path, target_format: str, quality: int) -> str:
    target_key = target_format.upper()
    if target_key not in CONVERT_FORMATS:
        raise ValueError(f"Unsupported target format: {target_format}")

    pil_format = CONVERT_FORMATS[target_key]
    ext_map = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}
    new_ext = ext_map[pil_format]

    if image_path.suffix.lower() == new_ext:
        raise ValueError(f"{image_path.name} is already {target_key}.")

    out_name = f"{image_path.stem}{new_ext}"
    out_path = get_unique_destination_path(image_path.parent, out_name)

    with Image.open(image_path) as img:
        save_kwargs: dict[str, Any] = {}
        output_img = img

        if pil_format == "JPEG" and img.mode in ("RGBA", "P", "LA"):
            output_img = img.convert("RGB")
        elif pil_format == "JPEG":
            output_img = img.convert("RGB") if img.mode != "RGB" else img

        if pil_format in ("JPEG", "WEBP"):
            save_kwargs["quality"] = quality
        if pil_format in ("PNG",):
            save_kwargs["optimize"] = True

        output_img.save(out_path, format=pil_format, **save_kwargs)
    return str(out_path)


def process_convert_worker(
    job_id: str,
    paths: list[str],
    target_format: str,
    quality: int,
) -> None:
    total = len(paths)
    processed = successful = 0
    errors: list[str] = []
    output_items: list[dict[str, str]] = []

    convert_jobs.update(job_id, status="running", progress=0)

    for raw in paths:
        ip = Path(raw)
        try:
            if not is_supported_image(ip):
                raise ValueError(f"Unsupported: {ip.name}")
            out = convert_one_image(ip, target_format, quality)
            successful += 1
            op = Path(out)
            if len(output_items) < MAX_OUTPUT_PREVIEW_ITEMS:
                output_items.append({
                    "name": op.name, "folder": str(op.parent),
                    "path": str(op), "source": ip.name,
                })
        except Exception as exc:
            errors.append(f"{ip.name}: {exc}")
        finally:
            processed += 1
            convert_jobs.update(
                job_id,
                processed_images=processed, successful_images=successful,
                progress=int(processed / total * 100) if total else 100,
                errors=list(errors), output_items=list(output_items),
            )

    convert_queue.remove_many(paths)
    convert_jobs.update(
        job_id, status="done", progress=100,
        message=f"Completed. Converted {successful}/{total} images to {target_format.upper()}.",
    )


# ===================================================================
# Routes
# ===================================================================

# -- Pages --
@app.get("/")
def index() -> str:
    return render_template("index.html", active_page="crop")


@app.get("/rename")
def rename_page() -> str:
    return render_template("rename.html", active_page="rename")


@app.get("/resize")
def resize_page() -> str:
    return render_template("resize.html", active_page="resize")


@app.get("/convert")
def convert_page() -> str:
    return render_template("convert.html", active_page="convert")


# -- Image preview --
@app.get("/api/image")
def api_image() -> Any:
    raw_path = request.args.get("path", "")
    if not raw_path:
        return jsonify({"error": "Path required."}), 400
    p = Path(raw_path)
    if not p.is_file():
        return jsonify({"error": "File not found."}), 404
    if p.suffix.lower() not in ALLOWED_EXTENSIONS:
        return jsonify({"error": "Unsupported type."}), 400
    return send_file(p, mimetype=f"image/{p.suffix.lower().strip('.')}")


# ===================================================================
# Crop API
# ===================================================================
@app.get("/api/selection")
def api_crop_selection() -> Any:
    return jsonify(queue_response(crop_queue))


@app.post("/api/select/single")
def api_crop_select_single() -> Any:
    try:
        paths = pick_single_file()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500
    crop_queue.append(paths)
    return jsonify(queue_response(crop_queue))


@app.post("/api/select/multiple")
def api_crop_select_multiple() -> Any:
    try:
        paths = pick_multiple_files()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500
    crop_queue.append(paths)
    return jsonify(queue_response(crop_queue))


@app.post("/api/select/folder")
def api_crop_select_folder() -> Any:
    try:
        paths = pick_folder_files()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500
    crop_queue.append(paths)
    return jsonify(queue_response(crop_queue))


@app.post("/api/selection/remove")
def api_crop_selection_remove() -> Any:
    body = request.get_json(silent=True) or {}
    raw = body.get("path")
    if not raw:
        return jsonify({"error": "Path required."}), 400
    removed = crop_queue.remove_one(str(raw))
    resp = queue_response(crop_queue)
    resp["removed"] = removed
    return jsonify(resp)


@app.post("/api/process")
def api_crop_process() -> Any:
    paths = crop_queue.snapshot()
    if not paths:
        return jsonify({"error": "No images selected."}), 400

    body = request.get_json(silent=True) or {}
    grid_rows = int(body.get("grid_rows", body.get("grid", 2)))
    grid_cols = int(body.get("grid_cols", body.get("grid", 2)))
    if grid_rows < 1 or grid_cols < 1 or grid_rows > 12 or grid_cols > 12:
        return jsonify({"error": "Grid dimensions must be between 1 and 12."}), 400

    dest = str(body.get("original_destination", DESTINATION_SAME))
    if dest not in ALLOWED_DESTINATIONS:
        dest = DESTINATION_SAME

    try:
        cells = parse_selected_cells(
            grid_rows, grid_cols,
            bool(body.get("use_cell_selector")),
            body.get("selected_cells", []),
        )
        sel_paths = parse_selector_paths(body.get("selector_paths"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    job_id = uuid.uuid4().hex
    crop_jobs.create(job_id, {
        "status": "queued", "progress": 0, "total_images": len(paths),
        "processed_images": 0, "successful_images": 0, "total_crops": 0,
        "errors": [], "output_items": [], "output_preview_truncated": False,
        "message": "", "archived_images": 0,
    })
    threading.Thread(
        target=process_images_worker,
        args=(job_id, paths, grid_rows, grid_cols, dest, cells, sel_paths),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


@app.get("/api/status/<job_id>")
def api_crop_status(job_id: str) -> Any:
    job = crop_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    return jsonify(job)


# ===================================================================
# Rename API
# ===================================================================
@app.get("/api/rename/selection")
def api_rename_selection() -> Any:
    return jsonify(queue_response(rename_queue))


@app.post("/api/rename/select/single")
def api_rename_select_single() -> Any:
    try:
        paths = pick_single_rename_file()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500
    rename_queue.append(paths)
    return jsonify(queue_response(rename_queue))


@app.post("/api/rename/select/multiple")
def api_rename_select_multiple() -> Any:
    try:
        paths = pick_multiple_rename_files()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500
    rename_queue.append(paths)
    return jsonify(queue_response(rename_queue))


@app.post("/api/rename/select/folder")
def api_rename_select_folder() -> Any:
    try:
        paths = pick_rename_folder_files()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500
    rename_queue.append(paths)
    return jsonify(queue_response(rename_queue))


@app.post("/api/rename/selection/remove")
def api_rename_selection_remove() -> Any:
    body = request.get_json(silent=True) or {}
    raw = body.get("path")
    if not raw:
        return jsonify({"error": "Path required."}), 400
    removed = rename_queue.remove_one(str(raw))
    resp = queue_response(rename_queue)
    resp["removed"] = removed
    return jsonify(resp)


@app.post("/api/rename/process")
def api_rename_process() -> Any:
    body = request.get_json(silent=True) or {}
    template = str(body.get("template", "")).strip()
    if not template:
        return jsonify({"error": "Rename template is required."}), 400
    try:
        start = int(body.get("start_number", 1))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid start number."}), 400

    paths = rename_queue.snapshot()
    if not paths:
        return jsonify({"error": "No files selected."}), 400

    job_id = uuid.uuid4().hex
    rename_jobs.create(job_id, {
        "status": "queued", "progress": 0, "total_images": len(paths),
        "processed_images": 0, "renamed_count": 0, "unchanged_count": 0,
        "errors": [], "preview_items": [], "message": "",
    })
    threading.Thread(
        target=process_rename_worker,
        args=(job_id, paths, template, start),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


@app.get("/api/rename/status/<job_id>")
def api_rename_status(job_id: str) -> Any:
    job = rename_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    return jsonify(job)


# ===================================================================
# Resize API
# ===================================================================
@app.get("/api/resize/selection")
def api_resize_selection() -> Any:
    return jsonify(queue_response(resize_queue))


@app.post("/api/resize/select/single")
def api_resize_select_single() -> Any:
    try:
        paths = pick_single_file()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500
    resize_queue.append(paths)
    return jsonify(queue_response(resize_queue))


@app.post("/api/resize/select/multiple")
def api_resize_select_multiple() -> Any:
    try:
        paths = pick_multiple_files()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500
    resize_queue.append(paths)
    return jsonify(queue_response(resize_queue))


@app.post("/api/resize/select/folder")
def api_resize_select_folder() -> Any:
    try:
        paths = pick_folder_files()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500
    resize_queue.append(paths)
    return jsonify(queue_response(resize_queue))


@app.post("/api/resize/selection/remove")
def api_resize_selection_remove() -> Any:
    body = request.get_json(silent=True) or {}
    raw = body.get("path")
    if not raw:
        return jsonify({"error": "Path required."}), 400
    removed = resize_queue.remove_one(str(raw))
    resp = queue_response(resize_queue)
    resp["removed"] = removed
    return jsonify(resp)


@app.post("/api/resize/process")
def api_resize_process() -> Any:
    paths = resize_queue.snapshot()
    if not paths:
        return jsonify({"error": "No images selected."}), 400

    body = request.get_json(silent=True) or {}
    mode = str(body.get("mode", RESIZE_MODE_PERCENTAGE))
    if mode not in ALLOWED_RESIZE_MODES:
        return jsonify({"error": f"Invalid resize mode: {mode}"}), 400

    try:
        percentage = int(body.get("percentage", 50))
        max_edge = int(body.get("max_edge", 1024))
        width = int(body.get("width", 800))
        height = int(body.get("height", 600))
        quality = max(1, min(100, int(body.get("quality", 90))))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid numeric parameter."}), 400

    maintain_aspect = bool(body.get("maintain_aspect", True))

    if mode == RESIZE_MODE_PERCENTAGE and (percentage < 1 or percentage > 1000):
        return jsonify({"error": "Percentage must be 1–1000."}), 400
    if mode == RESIZE_MODE_MAX_EDGE and max_edge < 1:
        return jsonify({"error": "Max edge must be at least 1."}), 400
    if mode == RESIZE_MODE_EXACT and (width < 1 or height < 1):
        return jsonify({"error": "Width and height must be at least 1."}), 400

    job_id = uuid.uuid4().hex
    resize_jobs.create(job_id, {
        "status": "queued", "progress": 0, "total_images": len(paths),
        "processed_images": 0, "successful_images": 0,
        "errors": [], "output_items": [], "message": "",
    })
    threading.Thread(
        target=process_resize_worker,
        args=(job_id, paths, mode, percentage, max_edge, width, height, maintain_aspect, quality),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


@app.get("/api/resize/status/<job_id>")
def api_resize_status(job_id: str) -> Any:
    job = resize_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    return jsonify(job)


# ===================================================================
# Convert API
# ===================================================================
@app.get("/api/convert/selection")
def api_convert_selection() -> Any:
    return jsonify(queue_response(convert_queue))


@app.post("/api/convert/select/single")
def api_convert_select_single() -> Any:
    try:
        paths = pick_single_file()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500
    convert_queue.append(paths)
    return jsonify(queue_response(convert_queue))


@app.post("/api/convert/select/multiple")
def api_convert_select_multiple() -> Any:
    try:
        paths = pick_multiple_files()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500
    convert_queue.append(paths)
    return jsonify(queue_response(convert_queue))


@app.post("/api/convert/select/folder")
def api_convert_select_folder() -> Any:
    try:
        paths = pick_folder_files()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500
    convert_queue.append(paths)
    return jsonify(queue_response(convert_queue))


@app.post("/api/convert/selection/remove")
def api_convert_selection_remove() -> Any:
    body = request.get_json(silent=True) or {}
    raw = body.get("path")
    if not raw:
        return jsonify({"error": "Path required."}), 400
    removed = convert_queue.remove_one(str(raw))
    resp = queue_response(convert_queue)
    resp["removed"] = removed
    return jsonify(resp)


@app.post("/api/convert/process")
def api_convert_process() -> Any:
    paths = convert_queue.snapshot()
    if not paths:
        return jsonify({"error": "No images selected."}), 400

    body = request.get_json(silent=True) or {}
    target_format = str(body.get("target_format", "")).upper()
    if target_format not in CONVERT_FORMATS:
        return jsonify({"error": f"Unsupported format: {target_format}"}), 400

    try:
        quality = max(1, min(100, int(body.get("quality", 85))))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid quality value."}), 400

    job_id = uuid.uuid4().hex
    convert_jobs.create(job_id, {
        "status": "queued", "progress": 0, "total_images": len(paths),
        "processed_images": 0, "successful_images": 0,
        "errors": [], "output_items": [], "message": "",
    })
    threading.Thread(
        target=process_convert_worker,
        args=(job_id, paths, target_format, quality),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


@app.get("/api/convert/status/<job_id>")
def api_convert_status(job_id: str) -> Any:
    job = convert_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    return jsonify(job)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
