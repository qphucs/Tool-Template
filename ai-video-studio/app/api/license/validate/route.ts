import { createHash } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";
import { licenseDb } from "@/lib/licenses";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json() as { app?: unknown; license_key?: unknown; device_id?: unknown; device_name?: unknown; device_os?: unknown };
    const key = typeof body.license_key === "string" ? body.license_key.trim() : "";
    const deviceId = typeof body.device_id === "string" ? body.device_id : "";
    const cleanDeviceInfo = (value: unknown) => typeof value === "string" ? value.replace(/[\u0000-\u001f\u007f]/g, "").trim().slice(0, 120) : null;
    const deviceName = cleanDeviceInfo(body.device_name);
    const deviceOs = cleanDeviceInfo(body.device_os);
    if (body.app !== "capcut-tool" || key.length < 20 || key.length > 200 || !/^[a-f0-9]{64}$/i.test(deviceId)) {
      return NextResponse.json({ valid: false, message: "Yêu cầu xác thực không hợp lệ." }, { status: 200, headers: { "Cache-Control": "no-store" } });
    }
    const keyHash = createHash("sha256").update(key, "utf8").digest("hex");
    const sql = licenseDb();
    await sql`ALTER TABLE app_licenses
      ADD COLUMN IF NOT EXISTS bound_device_hash CHAR(64),
      ADD COLUMN IF NOT EXISTS bound_device_name TEXT,
      ADD COLUMN IF NOT EXISTS bound_device_os TEXT,
      ADD COLUMN IF NOT EXISTS device_bound_at TIMESTAMPTZ`;
    const rows = await sql`
      UPDATE app_licenses
      SET bound_device_hash = COALESCE(bound_device_hash, ${deviceId}),
          bound_device_name = COALESCE(bound_device_name, ${deviceName}),
          bound_device_os = COALESCE(bound_device_os, ${deviceOs}),
          device_bound_at = COALESCE(device_bound_at, NOW()),
          last_validated_at = NOW()
      WHERE license_hash = ${keyHash} AND is_active = TRUE
        AND (expires_at IS NULL OR expires_at > NOW())
        AND (bound_device_hash IS NULL OR bound_device_hash = ${deviceId})
      RETURNING plan, expires_at
    `;
    if (!rows.length) return NextResponse.json({ valid: false, message: "Key không hợp lệ, hết hạn hoặc đã được kích hoạt trên thiết bị khác." }, { status: 200, headers: { "Cache-Control": "no-store" } });
    return NextResponse.json({ valid: true, plan: rows[0].plan, expires_at: rows[0].expires_at }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ valid: false, message: "Dịch vụ bản quyền hiện không khả dụng." }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
