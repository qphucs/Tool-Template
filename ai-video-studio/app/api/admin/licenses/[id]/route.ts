import { NextRequest, NextResponse } from "next/server";
import { isInternalRequest, licenseDb } from "@/lib/licenses";

export async function PATCH(request: NextRequest, context: { params: Promise<{ id: string }> }) {
  if (!isInternalRequest(request)) return NextResponse.json({ error: "Trang quản trị chỉ dùng được trong mạng nội bộ." }, { status: 403 });
  const { id } = await context.params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) return NextResponse.json({ error: "Mã bản quyền không hợp lệ." }, { status: 400 });
  try {
    const sql = licenseDb();
    const rows = await sql`UPDATE app_licenses SET is_active = FALSE WHERE id = ${id}::uuid AND is_active = TRUE RETURNING id::text`;
    if (!rows.length) return NextResponse.json({ error: "Không tìm thấy key đang hoạt động." }, { status: 404 });
    return NextResponse.json({ ok: true }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "Không thể thu hồi key bản quyền." }, { status: 500 });
  }
}
