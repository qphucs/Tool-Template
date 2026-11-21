import { NextRequest, NextResponse } from "next/server";

const providers: Record<string, { key: string; url: string; headers?: (key: string) => HeadersInit }> = {
  "gemini-flash": { key: "GEMINI_API_KEY", url: "https://generativelanguage.googleapis.com/v1beta/models", headers: (key) => ({ "x-goog-api-key": key }) },
  "openrouter-llama": { key: "OPENROUTER_API_KEY", url: "https://openrouter.ai/api/v1/models", headers: (key) => ({ Authorization: `Bearer ${key}` }) },
  "openrouter-deepseek": { key: "OPENROUTER_API_KEY", url: "https://openrouter.ai/api/v1/models", headers: (key) => ({ Authorization: `Bearer ${key}` }) },
  "groq-llama": { key: "GROQ_API_KEY", url: "https://api.groq.com/openai/v1/models", headers: (key) => ({ Authorization: `Bearer ${key}` }) },
  "claude-sonnet": { key: "ANTHROPIC_API_KEY", url: "https://api.anthropic.com/v1/models", headers: (key) => ({ "x-api-key": key, "anthropic-version": "2023-06-01" }) },
  "openai-mini": { key: "OPENAI_API_KEY", url: "https://api.openai.com/v1/models", headers: (key) => ({ Authorization: `Bearer ${key}` }) },
};

export async function GET(request: NextRequest) {
  const id = request.nextUrl.searchParams.get("id") || "";
  if (id === "ollama-llama") {
    try {
      const response = await fetch("http://127.0.0.1:11434/api/tags", { signal: AbortSignal.timeout(2500), cache: "no-store" });
      if (!response.ok) return NextResponse.json({ state: "offline", message: "Ollama chưa phản hồi. Cài và mở Ollama để kết nối tự động." });
      const data = await response.json() as { models?: Array<{ name: string }> };
      const installed = data.models?.some((model) => model.name.startsWith("llama3.1"));
      return NextResponse.json({ state: installed ? "connected" : "setup", message: installed ? "Đã kết nối Ollama trên máy." : "Ollama đang chạy; cần tải model llama3.1 bằng lệnh: ollama pull llama3.1" });
    } catch {
      return NextResponse.json({ state: "offline", message: "Chưa kết nối Ollama. Cài và mở Ollama để dùng model miễn phí không cần API key." });
    }
  }

  const provider = providers[id];
  if (!provider) return NextResponse.json({ state: "error", message: "Model không hợp lệ." }, { status: 400 });
  const key = process.env[provider.key];
  if (!key) return NextResponse.json({ state: "needs-key", message: `Model này dùng gói miễn phí/trả phí của nhà cung cấp nhưng cần API key. Thêm ${provider.key} vào .env.local rồi khởi động lại ứng dụng.` });
  try {
    const response = await fetch(provider.url, { headers: provider.headers?.(key), signal: AbortSignal.timeout(6000), cache: "no-store" });
    if (response.ok) return NextResponse.json({ state: "connected", message: "Đã kết nối nhà cung cấp bằng API key trên máy chủ." });
    return NextResponse.json({ state: "error", message: `Nhà cung cấp từ chối kết nối (HTTP ${response.status}). Kiểm tra key hoặc quyền truy cập model.` });
  } catch {
    return NextResponse.json({ state: "error", message: "Không thể kết nối nhà cung cấp. Kiểm tra mạng trên máy chạy ứng dụng." });
  }
}
