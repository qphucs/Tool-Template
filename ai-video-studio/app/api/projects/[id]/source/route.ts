import { readFile } from "node:fs/promises";
import path from "node:path";
import { NextResponse } from "next/server";
import { dataRoot, type ProjectRecord } from "@/lib/projects";

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) {
    return NextResponse.json({ error: "Invalid project id." }, { status: 400 });
  }
  try {
    const projects = JSON.parse(await readFile(path.join(dataRoot(), "projects.json"), "utf8")) as ProjectRecord[];
    const project = projects.find((item) => item.id === id);
    if (!project || !project.sourceFile || path.basename(project.sourceFile) !== project.sourceFile) {
      return NextResponse.json({ error: "Reference video not found." }, { status: 404 });
    }
    const ext = path.extname(project.sourceFile).toLowerCase();
    const contentType = ({ ".mp4": "video/mp4", ".mov": "video/quicktime", ".m4v": "video/x-m4v", ".webm": "video/webm" } as Record<string, string>)[ext] || "application/octet-stream";
    const bytes = await readFile(path.join(dataRoot(), "uploads", project.sourceFile));
    return new Response(bytes, { headers: { "Content-Type": contentType, "Content-Length": String(bytes.byteLength), "Cache-Control": "private, no-store" } });
  } catch {
    return NextResponse.json({ error: "Reference video could not be read." }, { status: 404 });
  }
}
