import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";
import { dataRoot, type ProjectRecord } from "@/lib/projects";

const readProjects = async () => JSON.parse(await readFile(path.join(dataRoot(), "projects.json"), "utf8")) as ProjectRecord[];
const writeAtomic = async (target: string, value: unknown) => {
  await mkdir(path.dirname(target), { recursive: true });
  const temp = `${target}.tmp`;
  await writeFile(temp, JSON.stringify(value, null, 2), "utf8");
  await rename(temp, target);
};

export async function POST(_request: NextRequest, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) return NextResponse.json({ error: "Mã dự án không hợp lệ." }, { status: 400 });
  try {
    const projects = await readProjects();
    const project = projects.find((item) => item.id === id);
    if (!project) return NextResponse.json({ error: "Không tìm thấy dự án." }, { status: 404 });
    if (project.status === "Queued" || project.status === "Analyzing") {
      return NextResponse.json({ error: "Video đang được phân tích." }, { status: 409 });
    }

    const workspace = path.resolve(process.cwd(), "..");
    const python = path.join(workspace, ".venv", "Scripts", "python.exe");
    const worker = path.join(process.cwd(), "worker.py");
    if (!existsSync(python) || !existsSync(worker)) {
      return NextResponse.json({ error: "Chưa cài worker Python cục bộ. Hãy xem hướng dẫn thiết lập." }, { status: 503 });
    }

    const now = new Date().toISOString();
    const jobsPath = path.join(dataRoot(), "jobs.json");
    const jobs: Array<Record<string, unknown>> = await readFile(jobsPath, "utf8").then((value) => JSON.parse(value) as Array<Record<string, unknown>>).catch((): Array<Record<string, unknown>> => []);
    const job = { id: randomUUID(), projectId: id, kind: "REFERENCE_ANALYSIS", status: "PENDING", createdAt: now };
    jobs.push(job);
    await writeAtomic(jobsPath, jobs);
    project.status = "Queued";
    project.progress = "Đang chờ worker trên máy…";
    project.analysisError = "";
    await writeAtomic(path.join(dataRoot(), "projects.json"), projects);

    const child = spawn(python, ["-X", "utf8", worker], {
      cwd: workspace,
      detached: true,
      windowsHide: true,
      stdio: "ignore",
      env: { ...process.env, STUDIO_DATA_DIR: dataRoot() },
    });
    child.unref();
    return NextResponse.json({ accepted: true, jobId: job.id, status: project.status }, { status: 202 });
  } catch {
    return NextResponse.json({ error: "Không thể đưa yêu cầu phân tích cảnh vào hàng chờ." }, { status: 500 });
  }
}
