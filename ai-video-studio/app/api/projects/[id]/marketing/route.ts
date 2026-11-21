import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";
import { dataRoot, type ProjectRecord } from "@/lib/projects";

async function getProject(id: string) {
  if (!/^[0-9a-f-]{36}$/i.test(id)) throw new Error("Invalid project id.");
  const root = dataRoot();
  const projects = JSON.parse(await readFile(path.join(root, "projects.json"), "utf8")) as ProjectRecord[];
  const project = projects.find((item) => item.id === id);
  if (!project || path.basename(project.sourceFile) !== project.sourceFile) throw new Error("Project or video source was not found.");
  const video = path.join(root, "uploads", project.sourceFile);
  if (!existsSync(video)) throw new Error("Project source video is missing from local storage.");
  return { root, project, video, outputDir: path.join(root, "projects", id) };
}

async function runPython(payload: Record<string, unknown>) {
  const workspace = path.resolve(process.cwd(), "..");
  const python = path.join(workspace, ".venv", "Scripts", "python.exe");
  const script = path.join(process.cwd(), "marketing.py");
  return await new Promise<{ ok: boolean; result?: unknown; error?: string }>((resolve, reject) => {
    const child = spawn(python, [script], { windowsHide: true, stdio: ["pipe", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8").on("data", (chunk: string) => { stdout += chunk; });
    child.stderr.setEncoding("utf8").on("data", (chunk: string) => { stderr += chunk; });
    child.on("error", reject);
    child.on("close", (code) => {
      try {
        if (code !== 0 && !stdout) return reject(new Error(stderr.trim() || "Local Python processing failed."));
        resolve(JSON.parse(stdout) as { ok: boolean; result?: unknown; error?: string });
      } catch (error) { reject(error); }
    });
    child.stdin.end(JSON.stringify(payload));
  });
}

export async function GET(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    const { outputDir } = await getProject(id);
    const data = await readFile(path.join(outputDir, "cover.png"));
    return new NextResponse(data, { headers: { "Content-Type": "image/png", "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "Chưa có ảnh bìa được tạo." }, { status: 404 });
  }
}

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    const body = await request.json() as Record<string, unknown>;
    const { video, outputDir } = await getProject(id);
    let payload: Record<string, unknown>;
    if (body.action === "cover") {
      const title = String(body.title || "").trim().slice(0, 140);
      if (!title) return NextResponse.json({ error: "Hãy nhập tiêu đề ảnh bìa trước." }, { status: 400 });
      const seconds = Number(body.seconds || 0);
      if (!Number.isFinite(seconds) || seconds < 0 || seconds > 86400) return NextResponse.json({ error: "Thời điểm khung hình phải là số giây hợp lệ." }, { status: 400 });
      const aspect = ["vertical", "portrait", "square"].includes(String(body.aspect)) ? String(body.aspect) : "vertical";
      await mkdir(outputDir, { recursive: true });
      payload = { action: "cover", video, output: path.join(outputDir, "cover.png"), seconds, title, brand: String(body.brand || "").trim().slice(0, 28), aspect };
    } else {
      const platform = String(body.platform || "facebook_reels");
      if (!["facebook_reels", "facebook_feed", "tiktok_organic", "tiktok_ads"].includes(platform)) return NextResponse.json({ error: "Hãy chọn nền tảng mạng xã hội được hỗ trợ." }, { status: 400 });
      payload = { action: "qc", video, platform };
    }
    const result = await runPython(payload);
    if (!result.ok) return NextResponse.json({ error: result.error || "Tác vụ tiếp thị thất bại." }, { status: 422 });
    if (body.action === "cover") {
      const coverInfo = result.result as Record<string, unknown>;
      await writeFile(path.join(outputDir, "cover.json"), JSON.stringify({ ...coverInfo, title: String(body.title).slice(0, 140), brand: String(body.brand || ""), aspect: body.aspect || "vertical" }, null, 2));
    }
    return NextResponse.json(result.result);
  } catch (error) {
    const detail = error instanceof Error ? error.message : "Local marketing tools could not process this video.";
    return NextResponse.json({ error: detail.includes("ENOENT") ? "Không tìm thấy Python hoặc công cụ video trên máy. Hãy mở ứng dụng bằng tệp khởi chạy dự án." : detail }, { status: 500 });
  }
}
