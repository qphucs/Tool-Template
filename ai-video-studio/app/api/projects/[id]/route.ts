import { readFile, writeFile, unlink, rm } from "node:fs/promises";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";
import { dataRoot, type ProjectRecord } from "@/lib/projects";

export async function DELETE(_request: NextRequest, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) {
    return NextResponse.json({ error: "Invalid project id." }, { status: 400 });
  }
  const root = dataRoot();
  const metadataPath = path.join(root, "projects.json");
  try {
    const projects = JSON.parse(await readFile(metadataPath, "utf8")) as ProjectRecord[];
    const removed = projects.find((project) => project.id === id);
    if (!removed) return NextResponse.json({ error: "Project not found." }, { status: 404 });
    await writeFile(metadataPath, JSON.stringify(projects.filter((project) => project.id !== id), null, 2), "utf8");
    if (removed.sourceFile && path.basename(removed.sourceFile) === removed.sourceFile) {
      await unlink(path.join(root, "uploads", removed.sourceFile)).catch(() => undefined);
    }
    await rm(path.join(root, "projects", id), { recursive: true, force: true }).catch(() => undefined);
    return NextResponse.json({ deleted: true });
  } catch {
    return NextResponse.json({ error: "Could not update the local project library." }, { status: 500 });
  }
}
