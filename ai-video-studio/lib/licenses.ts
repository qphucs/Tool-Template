import { neon } from "@neondatabase/serverless";
import { NextRequest } from "next/server";

export function licenseDb() {
  const connectionString = process.env.DATABASE_URL;
  if (!connectionString) throw new Error("LICENSE_DATABASE_NOT_CONFIGURED");
  return neon(connectionString);
}

export function isInternalRequest(request: NextRequest) {
  const rawHost = request.headers.get("host")?.toLowerCase() || "";
  const host = rawHost.startsWith("[") ? rawHost.slice(1, rawHost.indexOf("]")) : rawHost.split(":")[0];
  if (host === "localhost" || host === "::1") return true;
  const octets = host.split(".").map(Number);
  if (octets.length !== 4 || octets.some((octet) => !Number.isInteger(octet) || octet < 0 || octet > 255)) return false;
  const [first, second] = octets;
  return first === 127 || first === 10 || first === 192 && second === 168 || first === 172 && second >= 16 && second <= 31 || first === 169 && second === 254;
}
