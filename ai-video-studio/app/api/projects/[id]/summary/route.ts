import { readFile } from "node:fs/promises";
import path from "node:path";
import { NextResponse } from "next/server";
import { dataRoot } from "@/lib/projects";

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) return NextResponse.json({ error: "Invalid project id." }, { status: 400 });
  try {
    const image = await readFile(path.join(dataRoot(), "projects", id, "summary.jpg"));
    return new Response(image, { headers: { "Content-Type": "image/jpeg", "Cache-Control": "private, no-store" } });
  } catch {
    return NextResponse.json({ error: "Summary image is not available." }, { status: 404 });
  }
}
