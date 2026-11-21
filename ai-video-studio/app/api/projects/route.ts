import { randomUUID } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";
import { dataRoot, type ProjectRecord } from "@/lib/projects";

const projectsFile = () => path.join(dataRoot(), "projects.json");

async function readProjects(): Promise<ProjectRecord[]> {
  try {
    return JSON.parse(await readFile(projectsFile(), "utf8")) as ProjectRecord[];
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

function publicProject({ sourceFile: _sourceFile, ...project }: ProjectRecord) {
  return project;
}

export async function GET() {
  try {
    const projects = await readProjects();
    return NextResponse.json(projects.map(publicProject));
  } catch {
    return NextResponse.json({ error: "Không thể đọc thư viện dự án trên máy." }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
  try {
    const form = await request.formData();
    const file = form.get("video");
    if (!(file instanceof File) || file.size === 0) {
      return NextResponse.json({ error: "Hãy chọn video mẫu trước." }, { status: 400 });
    }
    const maxBytes = 200 * 1024 * 1024;
    if (file.size > maxBytes) {
      return NextResponse.json({ error: "Giới hạn tải lên là 200 MB cho mỗi video." }, { status: 413 });
    }
    const ext = path.extname(file.name).toLowerCase();
    if (![".mp4", ".mov", ".m4v", ".webm"].includes(ext)) {
      return NextResponse.json({ error: "Hãy dùng video MP4, MOV, M4V hoặc WebM." }, { status: 415 });
    }

    const id = randomUUID();
    const sourceFile = `${id}${ext}`;
    const uploadDir = path.join(dataRoot(), "uploads");
    await mkdir(uploadDir, { recursive: true });
    await writeFile(path.join(uploadDir, sourceFile), Buffer.from(await file.arrayBuffer()), { flag: "wx" });

    const mode = String(form.get("mode") || "Recreate");
    const project: ProjectRecord = {
      id,
      name: String(form.get("name") || file.name.replace(/\.[^.]+$/, "")).trim().slice(0, 120),
      sourceName: path.basename(file.name).slice(0, 180),
      sourceFile,
      mode: ["Recreate", "Inspired", "Auto mode"].includes(mode) ? mode as ProjectRecord["mode"] : "Recreate",
      duration: String(form.get("duration") || "30 seconds").slice(0, 40),
      aspect: String(form.get("aspect") || "9:16 · Vertical").slice(0, 40),
      resolution: String(form.get("resolution") || "1080p").slice(0, 20),
      prompt: String(form.get("prompt") || "").trim().slice(0, 4000),
      status: "Pending",
      createdAt: new Date().toISOString(),
    };
    const projects = await readProjects();
    projects.unshift(project);
    await writeFile(projectsFile(), JSON.stringify(projects, null, 2), "utf8");
    return NextResponse.json(publicProject(project), { status: 201 });
  } catch {
    return NextResponse.json({ error: "Không thể lưu dự án. Hãy kiểm tra quyền truy cập thư mục lưu trữ." }, { status: 500 });
  }
}

