import { createHash, randomBytes } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";
import { isInternalRequest, licenseDb } from "@/lib/licenses";

export async function GET(request: NextRequest) {
  if (!isInternalRequest(request)) return NextResponse.json({ error: "Trang quản trị chỉ dùng được trong mạng nội bộ." }, { status: 403 });
  try {
    const sql = licenseDb();
    await sql`ALTER TABLE app_licenses
      ADD COLUMN IF NOT EXISTS bound_device_hash CHAR(64),
      ADD COLUMN IF NOT EXISTS bound_device_name TEXT,
      ADD COLUMN IF NOT EXISTS bound_device_os TEXT,
      ADD COLUMN IF NOT EXISTS device_bound_at TIMESTAMPTZ`;
    const licenses = await sql`SELECT id::text, customer_name, plan, is_active, (bound_device_hash IS NOT NULL) AS device_bound, bound_device_name, bound_device_os, device_bound_at, expires_at, created_at, last_validated_at FROM app_licenses ORDER BY created_at DESC LIMIT 200`;
    return NextResponse.json({ licenses }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    const databaseCode = typeof error === "object" && error !== null && "code" in error ? String(error.code) : "UNKNOWN";
    console.error(`License list query failed [${databaseCode}]: ${detail.replace(/postgres(?:ql)?:\/\/\S+/gi, "postgresql://[redacted]")}`);
    const code = error instanceof Error && error.message === "LICENSE_DATABASE_NOT_CONFIGURED" ? 503 : 500;
    return NextResponse.json({ error: code === 503 ? "Máy chủ chưa cấu hình DATABASE_URL." : "Không thể đọc danh sách key." }, { status: code });
  }
}

export async function POST(request: NextRequest) {
  if (!isInternalRequest(request)) return NextResponse.json({ error: "Trang quản trị chỉ dùng được trong mạng nội bộ." }, { status: 403 });
  try {
    const body = await request.json() as { customerName?: unknown; plan?: unknown; expiresInDays?: unknown };
    const customerName = String(body.customerName || "").trim().slice(0, 120);
    const plan = String(body.plan || "standard").trim().slice(0, 40);
    const expiresInDays = body.expiresInDays === null ? null : Number(body.expiresInDays);
    if (!plan || (expiresInDays !== null && (!Number.isInteger(expiresInDays) || expiresInDays < 1 || expiresInDays > 3650))) {
      return NextResponse.json({ error: "Gói bản quyền hoặc thời hạn không hợp lệ." }, { status: 400 });
    }
    const key = `AVS-${randomBytes(32).toString("base64url")}`;
    const keyHash = createHash("sha256").update(key, "utf8").digest("hex");
    const sql = licenseDb();
    const rows = await sql`
      INSERT INTO app_licenses (license_hash, customer_name, plan, is_active, expires_at)
      VALUES (${keyHash}, ${customerName}, ${plan}, TRUE, ${expiresInDays === null ? null : new Date(Date.now() + expiresInDays * 86400000).toISOString()})
      RETURNING id::text, customer_name, plan, is_active, expires_at, created_at
    `;
    return NextResponse.json({ license: rows[0], key }, { status: 201, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const code = error instanceof Error && error.message === "LICENSE_DATABASE_NOT_CONFIGURED" ? 503 : 500;
    return NextResponse.json({ error: code === 503 ? "Máy chủ chưa cấu hình DATABASE_URL." : "Không thể tạo key. Hãy chạy schema cơ sở dữ liệu trước." }, { status: code });
  }
}
