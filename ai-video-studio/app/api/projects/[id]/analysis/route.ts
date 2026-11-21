import { readFile } from "node:fs/promises";
import path from "node:path";
import { NextResponse } from "next/server";
import { dataRoot } from "@/lib/projects";

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) return NextResponse.json({ error: "Invalid project id." }, { status: 400 });
  try {
    const file = path.join(dataRoot(), "projects", id, "analysis.json");
    const result = JSON.parse(await readFile(file, "utf8"));
    return NextResponse.json(result, { headers: { "Cache-Control": "private, no-store" } });
  } catch {
    return NextResponse.json({ error: "Analysis has not completed yet." }, { status: 404 });
  }
}
