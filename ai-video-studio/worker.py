"""Small persistent local worker for reference-video scene analysis."""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

STUDIO_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = STUDIO_ROOT.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

DATA_ROOT = Path(os.environ.get("STUDIO_DATA_DIR", STUDIO_ROOT / "storage")).resolve()
PROJECTS_FILE = DATA_ROOT / "projects.json"
QUEUE_FILE = DATA_ROOT / "jobs.json"
LOCK_FILE = DATA_ROOT / "worker.lock"


def read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return fallback


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def update_project(project_id: str, **changes) -> None:
    projects = read_json(PROJECTS_FILE, [])
    for project in projects:
        if project.get("id") == project_id:
            project.update(changes)
            project["updatedAt"] = datetime.now(timezone.utc).isoformat()
            break
    write_json(PROJECTS_FILE, projects)


def update_job(job_id: str, **changes) -> None:
    jobs = read_json(QUEUE_FILE, [])
    for job in jobs:
        if job.get("id") == job_id:
            job.update(changes)
            job["updatedAt"] = datetime.now(timezone.utc).isoformat()
            break
    write_json(QUEUE_FILE, jobs)


def process(job: dict) -> None:
    from capcut_tool.analyze.run import analyze_video

    project_id = job["projectId"]
    projects = read_json(PROJECTS_FILE, [])
    project = next((item for item in projects if item.get("id") == project_id), None)
    if project is None:
        raise FileNotFoundError("Project was deleted before analysis started.")
    source_name = project.get("sourceFile", "")
    if not source_name or Path(source_name).name != source_name:
        raise ValueError("Project has an invalid reference video path.")
    source = DATA_ROOT / "uploads" / source_name
    if not source.is_file():
        raise FileNotFoundError("Reference video is missing from local storage.")

    update_project(project_id, status="Analyzing", progress="Đang mở video…", analysisError="")
    update_job(job["id"], status="RUNNING", startedAt=datetime.now(timezone.utc).isoformat())

    def progress(message: str) -> None:
        update_project(project_id, status="Analyzing", progress=message[:180])
        update_job(job["id"], progress=message[:180])

    # Keep the first local pipeline independent of OCR model downloads. OCR can
    # be enabled later through an optional worker capability.
    result, output_dir = analyze_video(source, read_text=False, progress=progress)
    project_dir = DATA_ROOT / "projects" / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    analysis_file = project_dir / "analysis.json"
    analysis_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_source = output_dir / "summary.jpg"
    summary_target = project_dir / "summary.jpg"
    if summary_source.exists():
        summary_target.write_bytes(summary_source.read_bytes())
    update_project(project_id, status="Analysis complete", progress="Đã phân tích xong các cảnh", analysisFile="analysis.json", analysisError="")
    update_job(job["id"], status="COMPLETED", finishedAt=datetime.now(timezone.utc).isoformat())


def main() -> int:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return 0
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        while True:
            jobs = read_json(QUEUE_FILE, [])
            job = next((item for item in jobs if item.get("status") == "PENDING"), None)
            if job is None:
                time.sleep(0.75)
                jobs = read_json(QUEUE_FILE, [])
                job = next((item for item in jobs if item.get("status") == "PENDING"), None)
                if job is None:
                    return 0
            try:
                process(job)
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"[:700]
                update_project(job.get("projectId", ""), status="Failed", progress="Phân tích thất bại", analysisError=message)
                update_job(job["id"], status="FAILED", error=message, finishedAt=datetime.now(timezone.utc).isoformat())
                traceback.print_exc()
    finally:
        LOCK_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
