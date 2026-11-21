"use client";

import { Fragment, useEffect, useMemo, useState, type ChangeEvent, type Dispatch, type FormEvent, type ReactNode, type SetStateAction } from "react";

type ProjectMode = "Recreate" | "Inspired" | "Auto mode";
type ProjectForm = {
  name: string;
  mode: ProjectMode;
  duration: string;
  aspect: string;
  resolution: string;
  prompt: string;
};
type Project = {
  id: string;
  name: string;
  sourceName: string;
  mode: ProjectMode;
  duration: string;
  aspect: string;
  resolution: string;
  prompt: string;
  status: "Pending" | "Queued" | "Analyzing" | "Analysis complete" | "Failed";
  createdAt: string;
  progress?: string;
  analysisError?: string;
};
type AnalysisResult = {
  video: { fps: number; width: number; height: number; duration_s: number; frames: number };
  music: { tempo: number | null };
  shots: Array<{ index: number; start_s: number; end_s: number; reference_s: number; tracked_ratio: number }>;
  events: Array<{ type: string; shot: number; start_s: number; end_s: number; strength: number }>;
  transitions: Array<{ type: string; cut_s: number }>;
  overlays: unknown[];
  texts: unknown[];
};
type MarketingCheck = { name: string; status: "pass" | "warn" | "manual"; detail: string; action: string };
type MarketingQC = { platform: string; width: number; height: number; duration_s: number; fps: number; size_bytes: number; checks: MarketingCheck[]; note: string };
type ActivityDay = { day: string; count: number };
type ModelConnection = { state: "checking" | "connected" | "needs-key" | "setup" | "offline" | "error"; message: string };
type Section = "Overview" | "Create video" | "Projects" | "Library" | "AI settings" | "License admin";

const PROMPT_KEY = "ai-video-studio.prompt.v1";
const MODELS_KEY = "ai-video-studio.models.v1";
const MODEL_OPTIONS = [
  { id: "gemini-flash", name: "Gemini 2.5 Flash", provider: "Google Gemini", tier: "Gói miễn phí", role: "Phân tích và phản hồi nhanh", kind: "free" },
  { id: "openrouter-llama", name: "Llama 3.3 70B · :free", provider: "OpenRouter", tier: "Miễn phí", role: "Lập luận tổng quát", kind: "free" },
  { id: "openrouter-deepseek", name: "DeepSeek R1 · :free", provider: "OpenRouter", tier: "Miễn phí", role: "Lập luận và rà soát", kind: "free" },
  { id: "groq-llama", name: "Llama 3.3 70B", provider: "Groq", tier: "Gói miễn phí", role: "Lập kế hoạch nhanh", kind: "free" },
  { id: "ollama-llama", name: "Llama 3.1", provider: "Ollama", tier: "Cục bộ · Miễn phí", role: "Mô hình chạy trên máy", kind: "free" },
  { id: "claude-sonnet", name: "Claude Sonnet", provider: "Anthropic", tier: "API tính phí", role: "Chất lượng kịch bản và prompt", kind: "paid" },
  { id: "openai-mini", name: "GPT-4.1 mini", provider: "OpenAI", tier: "API tính phí", role: "Lập kế hoạch và rà soát", kind: "paid" },
];
const nav: { name: Section; label: string; icon: string }[] = [
  { name: "Overview", label: "Tổng quan", icon: "dashboard" },
  { name: "Create video", label: "Tạo video", icon: "add" },
  { name: "Projects", label: "Dự án", icon: "folder_open" },
  { name: "Library", label: "Thư viện", icon: "video_library" },
  { name: "AI settings", label: "Cài đặt AI", icon: "settings" },
  { name: "License admin", label: "Quản lý bản quyền", icon: "vpn_key" },
];

function NavIcon({ name }: { name: string }) {
  const paths: Record<string, string> = {
    dashboard: "M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z",
    add: "M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z",
    folder_open: "M20 6h-8l-2-2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm0 12H4l5-6h12l-1 6z",
    video_library: "M4 6H2v14c0 1.1.9 2 2 2h14v-2H4V6zm16-4H8C6.9 2 6 2.9 6 4v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-8 12V6l6 4-6 4z",
    settings: "M19.4 13a7.8 7.8 0 0 0 0-2l2-1.5-2-3.5-2.4 1a7.6 7.6 0 0 0-1.7-1L15 3h-4l-.4 3a7.6 7.6 0 0 0-1.7 1l-2.4-1-2 3.5 2 1.5a7.8 7.8 0 0 0 0 2l-2 1.5 2 3.5 2.4-1a7.6 7.6 0 0 0 1.7 1l.4 3h4l.4-3a7.6 7.6 0 0 0 1.7-1l2.4 1 2-3.5-2-1.5zM13 15a3 3 0 1 1 0-6 3 3 0 0 1 0 6z",
    vpn_key: "M7 14a4 4 0 1 1 3.9-5H22v4h-2v4h-4v-4h-5.1A4 4 0 0 1 7 14zm0-2a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d={paths[name] || paths.dashboard} /></svg>;
}

function modeLabel(mode: ProjectMode) { return ({ Recreate: "Tái tạo", Inspired: "Lấy cảm hứng", "Auto mode": "Tự động" })[mode]; }
function statusLabel(status: Project["status"]) { return ({ Pending: "Chờ xử lý", Queued: "Đang chờ", Analyzing: "Đang phân tích", "Analysis complete": "Đã phân tích", Failed: "Thất bại" })[status]; }
function durationLabel(value: string) { return value.replace(/seconds?/g, "giây").replace(/minutes?/g, "phút"); }
function aspectLabel(value: string) { return value.replace("Vertical", "Dọc").replace("Landscape", "Ngang").replace("Square", "Vuông"); }
function formatDate(value: string) {
  return new Intl.DateTimeFormat("vi-VN", { day: "numeric", month: "short", year: "numeric" }).format(new Date(value));
}

function loadSavedModels(): string[] | null {
  try {
    const parsed = JSON.parse(localStorage.getItem(MODELS_KEY) || "null");
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : null;
  } catch {
    return null;
  }
}

export default function Home() {
  const [section, setSection] = useState<Section>("Overview");
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProject, setActiveProject] = useState<string | null>(null);
  const [analysisForProject, setAnalysisForProject] = useState<{ projectId: string; result: AnalysisResult | null } | null>(null);
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const [source, setSource] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [selectedModels, setSelectedModels] = useState<string[]>(["gemini-flash"]);
  const [modelConnections, setModelConnections] = useState<Record<string, ModelConnection>>({});
  const [notice, setNotice] = useState("");
  const [form, setForm] = useState<ProjectForm>({
    name: "",
    mode: "Recreate" as ProjectMode,
    duration: "30 seconds",
    aspect: "9:16 · Vertical",
    resolution: "1080p",
    prompt: "",
  });
  const selectedProject = projects.find((project) => project.id === activeProject);
  const analysis = selectedProject?.status === "Analysis complete" && analysisForProject?.projectId === selectedProject.id ? analysisForProject.result : null;

  async function connectModel(id: string) {
    setModelConnections((current) => ({ ...current, [id]: { state: "checking", message: "Đang kiểm tra kết nối…" } }));
    try {
      const response = await fetch(`/api/models/connect?id=${encodeURIComponent(id)}`, { cache: "no-store" });
      const result = await response.json() as ModelConnection;
      setModelConnections((current) => ({ ...current, [id]: result }));
    } catch {
      setModelConnections((current) => ({ ...current, [id]: { state: "error", message: "Không kiểm tra được kết nối." } }));
    }
  }

  useEffect(() => {
    if (section === "AI settings") selectedModels.forEach((id) => { if (!modelConnections[id]) void connectModel(id); });
  }, [section, selectedModels, modelConnections]);

  useEffect(() => {
    Promise.all([
      fetch("/api/projects").then(async (response) => {
        if (!response.ok) throw new Error("Không tải được danh sách dự án.");
        return response.json() as Promise<Project[]>;
      }),
      Promise.resolve(localStorage.getItem(PROMPT_KEY) || ""),
      Promise.resolve(loadSavedModels()),
    ]).then(([saved, savedPrompt, savedModels]) => {
      setProjects(saved);
      setPrompt(savedPrompt);
      if (savedModels?.length) setSelectedModels(savedModels.slice(0, 3));
    }).catch(() => {
      setProjects([]);
      setPrompt(localStorage.getItem(PROMPT_KEY) || "");
      setNotice("Không kết nối được dịch vụ dự án trên máy. Hãy khởi động web app bằng npm run dev.");
    });
  }, []);

  const activity = useMemo(() => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const days = Array.from({ length: 7 }, (_, index) => {
      const date = new Date(today);
      date.setDate(date.getDate() - (6 - index));
      const count = projects.filter((project) => {
        const created = new Date(project.createdAt);
        return created.getFullYear() === date.getFullYear() && created.getMonth() === date.getMonth() && created.getDate() === date.getDate();
      }).length;
      return { day: new Intl.DateTimeFormat("vi-VN", { weekday: "short" }).format(date).toUpperCase(), count };
    });
    return days;
  }, [projects]);

  const hasActiveJob = projects.some((project) => project.status === "Queued" || project.status === "Analyzing");
  useEffect(() => {
    if (!hasActiveJob) return;
    const timer = window.setInterval(() => {
      fetch("/api/projects", { cache: "no-store" }).then((response) => response.json()).then((saved: Project[]) => setProjects(saved)).catch(() => undefined);
    }, 1800);
    return () => window.clearInterval(timer);
  }, [hasActiveJob]);

  const selectedProjectId = selectedProject?.id;
  const selectedProjectStatus = selectedProject?.status;
  useEffect(() => {
    if (!selectedProjectId || selectedProjectStatus !== "Analysis complete") return;
    fetch(`/api/projects/${selectedProjectId}/analysis`, { cache: "no-store" })
      .then((response) => response.ok ? response.json() as Promise<AnalysisResult> : null)
      .then((result) => setAnalysisForProject({ projectId: selectedProjectId, result }))
      .catch(() => setAnalysisForProject({ projectId: selectedProjectId, result: null }));
  }, [selectedProjectId, selectedProjectStatus]);

  function chooseFile(file?: File) {
    if (!file) return;
    if (!file.type.startsWith("video/") && !/\.(mp4|mov|m4v|webm)$/i.test(file.name)) {
      setNotice("Choose a video file such as MP4 hoặc MOV.");
      return;
    }
    setSource(file);
    setNotice("");
    if (!form.name) setForm((current) => ({ ...current, name: file.name.replace(/\.[^.]+$/, "") }));
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    chooseFile(event.target.files?.[0]);
  }

  async function createProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!source) {
      setNotice("Thêm video mẫu video to continue.");
      return;
    }
    setUploading(true);
    const data = new FormData();
    data.set("video", source);
    data.set("name", form.name.trim() || source.name.replace(/\.[^.]+$/, ""));
    data.set("mode", form.mode);
    data.set("duration", form.duration);
    data.set("aspect", form.aspect);
    data.set("resolution", form.resolution);
    data.set("prompt", form.prompt.trim());
    try {
      const response = await fetch("/api/projects", { method: "POST", body: data });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Không tạo được dự án.");
      const project = result as Project;
      setProjects((current) => [project, ...current]);
      setActiveProject(project.id);
      setSection("Projects");
      setSource(null);
      setNotice("Đã lưu dự án và video mẫu trên máy. Có thể chạy phân tích video.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Không tạo được dự án.");
    } finally {
      setUploading(false);
    }
  }

  function savePrompt() {
    localStorage.setItem(PROMPT_KEY, prompt);
    localStorage.setItem(MODELS_KEY, JSON.stringify(selectedModels.slice(0, 3)));
    setNotice("Đã lưu hướng dẫn AI và lựa chọn mô hình trong trình duyệt này.");
  }

  function openProject(id: string) {
    setActiveProject(id);
    setSection("Projects");
    setNotice("");
  }

  async function runAnalysis(id: string) {
    setAnalysisBusy(true);
    try {
      const response = await fetch(`/api/projects/${id}/analyze`, { method: "POST" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Không thể bắt đầu phân tích.");
      setProjects((current) => current.map((project) => project.id === id ? { ...project, status: "Queued", progress: "Waiting for local worker?", analysisError: "" } : project));
      setNotice("Đã thêm yêu cầu phân tích cảnh vào hàng chờ trên máy.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Không thể bắt đầu phân tích.");
    } finally {
      setAnalysisBusy(false);
    }
  }

  async function removeProject(id: string) {
    const response = await fetch(`/api/projects/${id}`, { method: "DELETE" });
    if (!response.ok) {
      setNotice("Không thể xóa dự án khỏi bộ nhớ trên máy.");
      return;
    }
    setProjects((current) => current.filter((project) => project.id !== id));
    if (activeProject === id) setActiveProject(null);
  }

  return (
    <main className="studio-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <div className="brand-mark"><span>V</span></div>
        <div><strong>AI VIDEO<span> STUDIO</span></strong><small>KHÔNG GIAN SÁNG TẠO</small></div>
        </div>
      <div className="workspace-switch"><div className="workspace-dot">S</div><div><b>Không gian Studio</b><small>Gói cá nhân</small></div><span className="chevron">⌄</span></div>
      <div className="nav-caption">KHÔNG GIAN LÀM VIỆC</div>
      <nav className="main-nav" aria-label="Điều hướng chính">
          {nav.map((item) => (
            <button className={`nav-item ${section === item.name ? "active" : ""}`} key={item.name} onClick={() => { setSection(item.name); setActiveProject(null); setNotice(""); }}>
            <span className="nav-icon"><NavIcon name={item.icon} /></span><span>{item.label}</span>
              {item.name === "Projects" && projects.length > 0 && <span className="nav-count">{projects.length}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="storage-card"><div className="storage-heading"><span>LƯU TRỮ</span><span>0.2 / 20 GB</span></div><div className="storage-track"><i /></div><small>Gói khởi đầu</small></div>
          <button className="profile-row"><div className="avatar">B</div><div><b>Buiva Studio</b><small>Không gian cục bộ</small></div><span className="more">···</span></button>
        </div>
      </aside>

      <section className="main-panel">
        <header className="topbar">
          <div className="breadcrumbs"><span>Không gian làm việc</span><span className="crumb-sep">/</span><b>{selectedProject && section === "Projects" ? selectedProject.name : nav.find((item) => item.name === section)?.label}</b></div>
          <div className="topbar-actions"><div className="worker-status"><i /> Worker chưa kết nối</div><button className="icon-button" aria-label="Thông báo">♧</button><div className="avatar small-avatar">B</div></div>
        </header>

        <div className="content-wrap">
          {notice && <div className="notice" role="status"><span>ⓘ</span>{notice}<button onClick={() => setNotice("")}>×</button></div>}
          {section === "Overview" && <Overview projects={projects} activity={activity} onCreate={() => setSection("Create video")} onOpen={openProject} />}
          {section === "Create video" && <CreateVideo form={form} setForm={setForm} source={source} dragging={dragging} setDragging={setDragging} uploading={uploading} onFileChange={onFileChange} chooseFile={chooseFile} onSubmit={createProject} />}
          {section === "Projects" && <Projects projects={projects} selected={selectedProject} analysis={analysis} analysisBusy={analysisBusy} onAnalyze={runAnalysis} onOpen={openProject} onRemove={removeProject} onCreate={() => setSection("Create video")} />}
          {section === "Library" && <Library projects={projects} onOpen={openProject} />}
          {section === "AI settings" && <AISettings prompt={prompt} setPrompt={setPrompt} selectedModels={selectedModels} setSelectedModels={setSelectedModels} modelConnections={modelConnections} onConnect={connectModel} onSave={savePrompt} />}
          {section === "License admin" && <LicenseAdmin />}
        </div>
      </section>
    </main>
  );
}

type LicenseRow = { id: string; customer_name: string; plan: string; is_active: boolean; device_bound: boolean; bound_device_name: string | null; bound_device_os: string | null; device_bound_at: string | null; expires_at: string | null; created_at: string; last_validated_at: string | null };

function LicenseAdmin() {
  const [customerName, setCustomerName] = useState("");
  const [plan, setPlan] = useState("standard");
  const [expiresInDays, setExpiresInDays] = useState("30");
  const [licenses, setLicenses] = useState<LicenseRow[]>([]);
  const [issuedKey, setIssuedKey] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [expandedLicenseId, setExpandedLicenseId] = useState<string | null>(null);

  useEffect(() => { void loadLicenses(); }, []);

  async function loadLicenses() {
    setBusy(true); setMessage("");
    try {
      const response = await fetch("/api/admin/licenses", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not load licenses.");
      setLicenses(data.licenses as LicenseRow[]);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not load licenses."); }
    finally { setBusy(false); }
  }

  async function createLicense(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage(""); setIssuedKey("");
    try {
      const response = await fetch("/api/admin/licenses", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ customerName, plan, expiresInDays: expiresInDays === "never" ? null : Number(expiresInDays) }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Không tạo được key.");
      setIssuedKey(data.key); setCustomerName(""); await loadLicenses(); setMessage("Đã tạo key. Hãy sao chép và gửi cho khách; key chỉ hiển thị một lần.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Không tạo được key."); }
    finally { setBusy(false); }
  }

  async function revokeLicense(id: string) {
    if (!window.confirm("Thu hồi key này? Người dùng sẽ không thể xác thực lại.")) return;
    setBusy(true);
    try {
      const response = await fetch(`/api/admin/licenses/${id}`, { method: "PATCH" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Không thu hồi được key.");
      await loadLicenses(); setMessage("Đã thu hồi key.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Không thu hồi được key."); }
    finally { setBusy(false); }
  }

  return <>
    <PageTitle eyebrow="QUẢN TRỊ" title="Quản lý bản quyền" subtitle="Tạo key cấp cho khách hàng, kiểm tra trạng thái và thu hồi quyền sử dụng." />
    <section className="panel license-admin-card">
      <div className="panel-head"><div><div className="eyebrow">DỮ LIỆU NỘI BỘ</div><h2>{busy ? "Đang tải dữ liệu…" : `Đã tải ${licenses.length} key`}</h2></div><span className="saved-local">Tự động đồng bộ từ cơ sở dữ liệu riêng</span></div>
      <p className="settings-intro">Mỗi key chỉ kích hoạt trên tối đa 1 thiết bị. Key sẽ tự gắn với thiết bị đầu tiên sử dụng.</p>
      {message && <p className="license-message" role="status">{message}</p>}
    </section>
    <section className="panel license-admin-card">
      <div className="panel-head"><div><div className="eyebrow">PHÁT HÀNH KEY</div><h2>Tạo key bản quyền mới</h2></div></div>
      <form className="license-create-form" onSubmit={createLicense}>
        <label className="field-label">TÊN KHÁCH HÀNG<input value={customerName} onChange={(event) => setCustomerName(event.target.value)} maxLength={120} placeholder="Ví dụ: Nguyễn Văn A" /></label>
        <label className="field-label">GÓI BẢN QUYỀN<select value={plan} onChange={(event) => setPlan(event.target.value)}><option value="standard">Tiêu chuẩn</option><option value="pro">Chuyên nghiệp</option><option value="enterprise">Doanh nghiệp</option></select></label>
        <label className="field-label">THỜI HẠN<select value={expiresInDays} onChange={(event) => setExpiresInDays(event.target.value)}><option value="30">30 ngày</option><option value="90">90 ngày</option><option value="365">1 năm</option><option value="never">Không hết hạn</option></select></label>
        <button className="button primary" type="submit" disabled={busy}>Tạo key bản quyền</button>
      </form>
      {issuedKey && <div className="issued-key"><div><b>Key mới ? hãy sao chép ngay</b><code>{issuedKey}</code></div><button className="button secondary" onClick={() => void navigator.clipboard.writeText(issuedKey).then(() => setMessage("Đã sao chép key vào bộ nhớ tạm."))}>Sao chép</button></div>}
      {message && <p className="license-message" role="status">{message}</p>}
    </section>
    <section className="panel license-admin-card"><div className="panel-head"><div><div className="eyebrow">DANH SÁCH</div><h2>Key đã phát hành ({licenses.length})</h2></div></div>
      {licenses.length ? <div className="table-scroll"><table className="license-table"><thead><tr><th>KHÁCH HÀNG</th><th>GÓI</th><th>TRẠNG THÁI</th><th>THIẾT BỊ</th><th>HẾT HẠN</th><th>KHỞI TẠO</th><th/></tr></thead><tbody>{licenses.map((license) => <Fragment key={license.id}>
        <tr>
          <td>{license.customer_name || "Ch\u01b0a ghi t\u00ean"}</td>
          <td>{license.plan}</td>
          <td><span className={license.is_active ? "license-active" : "license-revoked"}>{license.is_active ? "\u0110ang ho\u1ea1t \u0111\u1ed9ng" : "\u0110\u00e3 thu h\u1ed3i"}</span></td>
          <td><div className="license-device"><b>{license.bound_device_name || (license.device_bound ? "Thi\u1ebft b\u1ecb \u0111\u00e3 k\u00edch ho\u1ea1t" : "Ch\u01b0a k\u00edch ho\u1ea1t")}</b><small>{license.device_bound ? "1/1 thi\u1ebft b\u1ecb" : "0/1 thi\u1ebft b\u1ecb"}</small><button type="button" className="license-details-button" aria-expanded={expandedLicenseId === license.id} onClick={() => setExpandedLicenseId(expandedLicenseId === license.id ? null : license.id)}>{expandedLicenseId === license.id ? "Thu g\u1ecdn" : "Xem th\u00eam"}</button></div></td>
          <td>{license.expires_at ? new Date(license.expires_at).toLocaleDateString("vi-VN") : "Kh\u00f4ng th\u1eddi h\u1ea1n"}</td>
          <td>{new Date(license.created_at).toLocaleDateString("vi-VN")}</td>
          <td>{license.is_active && <button className="button secondary revoke-button" disabled={busy} onClick={() => void revokeLicense(license.id)}>{"Thu h\u1ed3i"}</button>}</td>
        </tr>
        {expandedLicenseId === license.id && <tr className="license-expanded-row"><td colSpan={7}><div className="license-expanded-grid"><div><small>T\u00caN THI\u1ebeT B\u1eca</small><b>{license.bound_device_name || "Ch\u01b0a c\u00f3 d\u1eef li\u1ec7u; m\u1edf desktop app v\u1eeba c\u1eadp nh\u1eadt v\u00e0 x\u00e1c th\u1ef1c key."}</b></div><div><small>H\u1ec6 \u0110I\u1ec0U H\u00c0NH / KI\u1ebeN TR\u00daC</small><b>{license.bound_device_os || "Ch\u01b0a ghi nh\u1eadn"}</b></div><div><small>TH\u1edcI \u0110I\u1ec2M K\u00cdCH HO\u1ea0T</small><b>{license.device_bound_at ? new Date(license.device_bound_at).toLocaleString("vi-VN") : "Ch\u01b0a k\u00edch ho\u1ea1t"}</b></div><div><small>X\u00c1C TH\u1ef0C G\u1ea6N NH\u1ea4T</small><b>{license.last_validated_at ? new Date(license.last_validated_at).toLocaleString("vi-VN") : "Ch\u01b0a c\u00f3 l\u1ea7n n\u00e0o"}</b></div></div></td></tr>}
      </Fragment>)}</tbody></table></div> : <p className="settings-intro">No licenses found in the internal database.</p>}
    </section>
  </>;
}

function PageTitle({ eyebrow, title, subtitle, action }: { eyebrow: string; title: string; subtitle: string; action?: ReactNode }) {
  return <div className="page-title"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{subtitle}</p></div>{action}</div>;
}

function Overview({ projects, activity, onCreate, onOpen }: { projects: Project[]; activity: ActivityDay[]; onCreate: () => void; onOpen: (id: string) => void }) {
  const activityMax = Math.max(1, ...activity.map((item) => item.count));
  const cards = [
    { label: "TỔNG SỐ DỰ ÁN", value: String(projects.length).padStart(2, "0"), icon: "▤", trend: "Toàn bộ dự án video" },
    { label: "ĐANG CHỜ XỬ LÝ", value: String(projects.filter((project) => project.status === "Pending" || project.status === "Queued" || project.status === "Analyzing").length).padStart(2, "0"), icon: "◷", trend: "Có thể phân tích cảnh trên máy" },
    { label: "VIDEO ĐÃ PHÂN TÍCH", value: String(projects.filter((project) => project.status === "Analysis complete").length).padStart(2, "0"), icon: "▷", trend: "Sẵn sàng lên kịch bản" },
    { label: "CHI PHÍ THÁNG", value: "0 USD", icon: "＄", trend: "Chưa phát sinh phí API" },
  ];
  return <>
    <PageTitle eyebrow="BẢNG ĐIỀU KHIỂN" title="Chào Buiva!" subtitle="Tổng quan không gian sản xuất video của bạn." action={<button className="button primary" onClick={onCreate}><span>＋</span> Tạo video</button>} />
    <div className="stat-grid">{cards.map((card, index) => <div className="stat-card" key={card.label}><div className={`stat-icon icon-${index}`}>{card.icon}</div><div className="stat-label">{card.label}</div><div className="stat-value">{card.value}</div><div className="stat-foot"><span className={index === 3 ? "muted-dot" : "green-dot"} />{card.trend}</div></div>)}</div>
    <div className="overview-grid">
      <section className="panel journey-panel"><div className="panel-head"><div><div className="eyebrow">QUY TRÌNH CỦA BẠN</div><h2>Từ video mẫu đến bản dựng cuối</h2></div><span className="live-tag"><i /> SẴN SÀNG BẮT ĐẦU</span></div><div className="journey-line">{[{n:"01",t:"Thêm video mẫu",d:"Tải video lên hoặc dán liên kết",i:"↥"},{n:"02",t:"Phân tích cảnh",d:"Nhận diện nhịp cắt, chuyển động và chuyển cảnh",i:"⌕"},{n:"03",t:"Lên kế hoạch và tạo",d:"Kịch bản phân cảnh và clip bằng AI",i:"✦"},{n:"04",t:"Duyệt và xuất video",d:"Ghép dựng và kiểm tra video",i:"↗"}].map((step,index)=><div className="journey-step" key={step.n}><div className={`step-icon ${index===0?"step-now":""}`}>{step.i}</div><div className="step-copy"><span>BƯỚC {step.n}</span><b>{step.t}</b><small>{step.d}</small></div>{index<3&&<div className="step-connector"/>}</div>)}</div><button className="text-link" onClick={onCreate}>Bắt đầu dự án đầu tiên <span>→</span></button></section>
      <section className="panel chart-panel"><div className="panel-head"><div><div className="eyebrow">HOẠT ĐỘNG</div><h2>Tổng quan sản xuất</h2></div><span className="select-pill">7 ngày qua</span></div><div className="chart-legend"><span><i className="legend-purple"/> Dự án đã tạo</span></div><div className="chart-area"><div className="chart-y"><span>{activityMax}</span><span>{Math.ceil(activityMax*2/3)}</span><span>{Math.ceil(activityMax/3)}</span><span>0</span></div><div className="chart-bars">{activity.map((item)=><div className="chart-col" key={item.day}><div className="bar-stack"><i style={{height:`${item.count ? Math.max(6,item.count/activityMax*80) : 0}%`}}/></div><small>{item.day}</small></div>)}</div>{projects.length===0&&<div className="chart-empty">Hoạt động sản xuất sẽ hiển thị tại đây.</div>}</div></section>
    </div>
    <section className="panel recent-panel"><div className="panel-head"><div><div className="eyebrow">KHÔNG GIAN CỦA BẠN</div><h2>Dự án gần đây</h2></div><button className="text-link" onClick={() => onCreate()}>Dự án mới <span>＋</span></button></div>{projects.length ? <ProjectTable projects={projects.slice(0,4)} onOpen={onOpen}/> : <div className="empty-inline"><div className="empty-icon">▧</div><div><b>Chưa có dự án nào</b><p>Bắt đầu bằng video mẫu để tạo kịch bản phân cảnh đầu tiên.</p></div><button className="button secondary" onClick={onCreate}>Tạo dự án <span>→</span></button></div>}</section>
  </>;
}

function CreateVideo({ form, setForm, source, dragging, setDragging, uploading, onFileChange, chooseFile, onSubmit }: {
  form: ProjectForm;
  setForm: Dispatch<SetStateAction<ProjectForm>>;
  source: File | null; dragging: boolean; setDragging: (value: boolean) => void; uploading: boolean;
  onFileChange: (event: ChangeEvent<HTMLInputElement>) => void; chooseFile: (file?: File) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
}) {
  return <>
    <PageTitle eyebrow="QUY TRÌNH MỚI" title="Tạo video mới" subtitle="Bắt đầu từ video mẫu. Bạn có thể chỉnh cài đặt dự án sau." />
    <form className="create-layout" onSubmit={onSubmit}>
      <div className="create-main">
        <section className="panel form-panel"><div className="section-heading"><span className="number-badge">01</span><div><h2>Video mẫu</h2><p>Chọn video làm tư liệu tham khảo cho sản phẩm mới.</p></div></div>
          <label className={`upload-zone ${dragging?"dragging":""}`} onDragOver={(event)=>{event.preventDefault();setDragging(true)}} onDragLeave={()=>setDragging(false)} onDrop={(event)=>{event.preventDefault();setDragging(false);chooseFile(event.dataTransfer.files[0])}}>
            <input type="file" accept="video/mp4,video/quicktime,video/*" onChange={onFileChange}/><span className="upload-glyph">↥</span>{source?<><b>{source.name}</b><small>{(source.size/1024/1024).toFixed(1)} MB · Sẵn sàng thêm</small></>:<><b>Thả video vào đây hoặc <em>chọn tệp</em></b><small>MP4 hoặc MOV · Tải lên tối đa 200 MB</small></>}</label>
          <div className="or-divider"><span/>HOẶC<span/></div><label className="field-label">ĐƯỜNG DẪN VIDEO<div className="url-input"><span>↗</span><input placeholder="Dán liên kết video được hỗ trợ" disabled/><span className="coming-tag">SẮP RA MẮT</span></div></label>
        </section>
        <section className="panel form-panel"><div className="section-heading"><span className="number-badge">02</span><div><h2>Định hướng sáng tạo</h2><p>Chọn mức độ bám sát video mẫu.</p></div></div><div className="mode-grid">{[{name:"Recreate" as ProjectMode,icon:"⟳",desc:"Bám sát cấu trúc và phong cách video mẫu."},{name:"Inspired" as ProjectMode,icon:"✧",desc:"Lấy cảm hứng và tạo nội dung mới."},{name:"Auto mode" as ProjectMode,icon:"◈",desc:"Để AI tự quyết định theo yêu cầu của bạn."}].map((mode)=><button type="button" className={`mode-card ${form.mode===mode.name?"selected":""}`} key={mode.name} onClick={()=>setForm(current=>({...current,mode:mode.name}))}><span className="mode-icon">{mode.icon}</span><b>{mode.name === "Recreate" ? "Tái tạo" : mode.name === "Inspired" ? "Lấy cảm hứng" : "Tự động"}</b><small>{mode.desc}</small><i className="radio-dot"/></button>)}</div><label className="field-label project-name">TÊN DỰ ÁN<input value={form.name} onChange={(event)=>setForm(current=>({...current,name:event.target.value}))} placeholder="VD: Chiến dịch ra mắt mùa hè"/></label><label className="field-label">YÊU CẦU BỔ SUNG <span className="optional">KHÔNG BẮT BUỘC</span><textarea value={form.prompt} onChange={(event)=>setForm(current=>({...current,prompt:event.target.value}))} placeholder="Mô tả ý tưởng, đối tượng xem, cảm xúc hoặc điều bạn muốn AI lưu ý?" rows={4}/></label></section>
      </div>
      <aside className="create-side"><section className="panel form-panel settings-panel"><div className="section-heading"><span className="number-badge">03</span><div><h2>Cài đặt đầu ra</h2><p>Chọn định dạng video cần xuất.</p></div></div><label className="field-label">THỜI LƯỢNG MỤC TIÊU<select value={form.duration} onChange={(event)=>setForm(current=>({...current,duration:event.target.value}))}><option value="15 seconds">15 giây</option><option value="30 seconds">30 giây</option><option value="60 seconds">60 giây</option><option value="90 seconds">90 giây</option><option value="5 minutes">5 phút</option><option value="10 minutes">10 phút</option></select></label><label className="field-label">TỶ LỆ KHUNG HÌNH<select value={form.aspect} onChange={(event)=>setForm(current=>({...current,aspect:event.target.value}))}><option value="9:16 · Vertical">9:16 · Dọc</option><option value="16:9 · Landscape">16:9 · Ngang</option><option value="1:1 · Square">1:1 · Vuông</option></select></label><label className="field-label">ĐỘ PHÂN GIẢI<select value={form.resolution} onChange={(event)=>setForm(current=>({...current,resolution:event.target.value}))}><option>720p</option><option>1080p</option><option>4K</option></select></label><div className="provider-hint"><span>✦</span><div><b>Nhà cung cấp AI</b><small>Kết nối mô hình trong Cài đặt AI sau khi thiết lập.</small></div><span className="chevron">→</span></div></section><div className="create-footer"><p>Video mẫu được lưu trên máy (giới hạn 200 MB mỗi video).</p><button className="button primary full-button" type="submit" disabled={uploading}>{uploading ? "Đang lưu video mẫu…" : <>Tạo dự án <span>→</span></>}</button></div></aside>
    </form>
  </>;
}

function MarketingTools({ project }: { project: Project }) {
  const [title, setTitle] = useState(project.name);
  const [brand, setBrand] = useState("");
  const [seconds, setSeconds] = useState("0");
  const [aspect, setAspect] = useState("vertical");
  const [platform, setPlatform] = useState("facebook_reels");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [coverVersion, setCoverVersion] = useState(0);
  const [coverLoaded, setCoverLoaded] = useState(false);
  const [qc, setQc] = useState<MarketingQC | null>(null);
  async function generateCover() {
    setBusy(true); setMessage("");
    try {
      const response = await fetch(`/api/projects/${project.id}/marketing`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "cover", title, brand, seconds: Number(seconds), aspect }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Không thể tạo ảnh bìa.");
      setCoverLoaded(false); setCoverVersion(Date.now()); setMessage("Đã tạo ảnh bìa trên máy và lưu vào dự án.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Tạo ảnh bìa thất bại."); }
    finally { setBusy(false); }
  }
  async function inspectVideo() {
    setBusy(true); setMessage("");
    try {
      const response = await fetch(`/api/projects/${project.id}/marketing`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "qc", platform }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Không thể kiểm tra video.");
      setQc(result as MarketingQC);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Rà soát kỹ thuật thất bại."); }
    finally { setBusy(false); }
  }
  return <section className="panel marketing-panel"><div className="panel-head"><div><div className="eyebrow">TIẾP THỊ MẠNG XÃ HỘI</div><h2>Ảnh bìa và kiểm tra bài đăng</h2></div><span className="saved-local">Xử lý trên máy</span></div><p className="settings-intro">Tạo ảnh bìa có thương hiệu từ một khung hình video, sau đó kiểm tra thông số đăng Facebook hoặc TikTok.</p><div className="marketing-grid"><div className="marketing-form"><h3>01 · Ảnh bìa</h3><div className="marketing-fields"><label className="field-label">TIÊU ĐỀ<input maxLength={140} value={title} onChange={(e)=>setTitle(e.target.value)} placeholder="Tiêu đề chiến dịch"/></label><label className="field-label">THƯƠNG HIỆU / TÀI KHOẢN<input maxLength={28} value={brand} onChange={(e)=>setBrand(e.target.value)} placeholder="Tên thương hiệu (không bắt buộc)"/></label><div className="cover-options"><label className="field-label">THỜI ĐIỂM KHUNG HÌNH (GIÂY)<input type="number" min="0" step="0.5" value={seconds} onChange={(e)=>setSeconds(e.target.value)}/></label><label className="field-label">KÍCH THƯỚC ẢNH BÌA<select value={aspect} onChange={(e)=>setAspect(e.target.value)}><option value="vertical">Dọc · 9:16</option><option value="portrait">Dọc · 4:5</option><option value="square">Vuông · 1:1</option></select></label></div><button className="button primary" disabled={busy || !title.trim()} onClick={generateCover}>{busy ? "Đang xử lý?" : "Tạo ảnh bìa →"}</button></div></div><div className="cover-preview-wrap"><div className={`cover-preview ${aspect}`}>{coverVersion > 0 && <img src={`/api/projects/${project.id}/marketing?v=${coverVersion}`} alt="Ảnh bìa mạng xã hội đã tạo" onLoad={()=>setCoverLoaded(true)} onError={()=>setCoverLoaded(false)} style={{display:coverLoaded?"block":"none"}}/>}{!coverLoaded && <div className="cover-empty">✦<small>Xem trước ảnh bìa</small></div>}</div><a className="text-link" href={`/api/projects/${project.id}/marketing`} download={`${project.name.replace(/[^a-z0-9-_]/gi,"-")}-cover.png`}>Tải ảnh PNG ↗</a></div></div><div className="qc-divider"/><div className="qc-controls"><div><h3>02 · Kiểm tra video đăng bài</h3><p>Chọn loại bài đăng dự kiến. Giới hạn có thể khác theo vị trí quảng cáo và tài khoản.</p></div><div className="qc-select"><select value={platform} onChange={(e)=>{setPlatform(e.target.value);setQc(null);}}><option value="facebook_reels">Facebook · Reels</option><option value="facebook_feed">Facebook · Bài đăng bảng tin</option><option value="tiktok_organic">TikTok · Bài đăng thường</option><option value="tiktok_ads">TikTok · Quảng cáo In-Feed</option></select><button className="button secondary" disabled={busy} onClick={inspectVideo}>{busy ? "Đang kiểm tra?" : "Kiểm tra video"}</button></div></div>{qc && <><div className="qc-overview"><span>{qc.width} × {qc.height}</span><span>{qc.duration_s.toFixed(1)}s · {qc.fps} fps</span><span>{(qc.size_bytes / 1048576).toFixed(1)} MB</span></div><div className="qc-list">{qc.checks.map((item)=><div className="qc-row" key={item.name}><span className={`qc-state ${item.status}`}>{item.status === "pass" ? "✓ ĐẠT" : item.status === "warn" ? "! CẦN XEM LẠI" : "? THỦ CÔNG"}</span><div><b>{item.name}</b><small>{item.detail}</small><em>{item.action}</em></div></div>)}</div><p className="qc-note">{qc.note}</p></>}{message && <div className="worker-callout">ⓘ<p>{message}</p></div>}</section>;
}

function Projects({ projects, selected, analysis, analysisBusy, onAnalyze, onOpen, onRemove, onCreate }: { projects: Project[]; selected?: Project; analysis: AnalysisResult | null; analysisBusy: boolean; onAnalyze: (id:string)=>void; onOpen: (id:string)=>void; onRemove: (id:string)=>void; onCreate:()=>void }) {
  if (selected) return <><PageTitle eyebrow="CHI TIẾT DỰ ÁN" title={selected.name} subtitle={`Tạo ngày ${formatDate(selected.createdAt)} · ${modeLabel(selected.mode)}`} action={<button className="button secondary" onClick={()=>onRemove(selected.id)}>Xóa dự án</button>}/><div className="detail-grid"><section className="panel detail-preview"><div className="preview-screen"><video controls preload="metadata" src={`/api/projects/${selected.id}/source`} aria-label={`Video mẫu: ${selected.sourceName}`}/><span className="preview-label">VIDEO MẪU</span></div><div className="file-row"><span className="file-icon">▣</span><div><b>{selected.sourceName}</b><small>Video nguồn · Đã lưu trên máy</small></div></div></section><section className="panel detail-meta"><div className="eyebrow">CÀI ĐẶT DỰ ÁN</div><h2>Yêu cầu sáng tạo</h2><div className="detail-list"><div><span>Chế độ</span><b>{modeLabel(selected.mode)}</b></div><div><span>Thời lượng mục tiêu</span><b>{durationLabel(selected.duration)}</b></div><div><span>Định dạng</span><b>{aspectLabel(selected.aspect)} · {selected.resolution}</b></div><div><span>Trạng thái dự án</span><b className={`status-copy status-${selected.status.toLowerCase().replaceAll(" ", "-")}`}><i/>{statusLabel(selected.status)}</b></div></div><div className="brief-box"><span>YÊU CẦU BỔ SUNG</span><p>{selected.prompt || "Chưa có yêu cầu bổ sung."}</p></div>{selected.status === "Queued" || selected.status === "Analyzing" ? <div className="worker-callout"><span>◷</span><p>{selected.progress || "Worker trên máy đang phân tích video mẫu…"}</p></div> : selected.status === "Failed" ? <div className="worker-callout error-callout"><span>!</span><p>{selected.analysisError || "Phân tích trên máy thất bại."}</p></div> : selected.status === "Analysis complete" ? <div className="worker-callout success-callout"><span>✓</span><p>Đã phân tích video trên máy. Xem danh sách cảnh bên dưới.</p></div> : <div className="worker-callout"><span>ⓘ</span><p>Phân tích video trên máy để nhận diện cảnh, chuyển cảnh, chuyển động, lớp phủ và nhịp âm thanh nếu có.</p></div>}{(selected.status === "Pending" || selected.status === "Failed") && <button className="button primary analyze-button" disabled={analysisBusy} onClick={()=>onAnalyze(selected.id)}>{analysisBusy ? "Đang đưa vào hàng chờ…" : selected.status === "Failed" ? "Thử phân tích lại" : "Phân tích video mẫu"} <span>→</span></button>}</section></div>{analysis && <section className="panel analysis-panel"><div className="panel-head"><div><div className="eyebrow">PHÂN TÍCH VIDEO TRÊN MÁY</div><h2>Phân tích phân cảnh</h2></div><a className="button secondary" href={`/api/projects/${selected.id}/summary`} target="_blank" rel="noreferrer">Mở ảnh tổng hợp ↗</a></div><div className="analysis-stats"><div><small>THỜI LƯỢNG</small><b>{analysis.video.duration_s.toFixed(1)}s</b></div><div><small>KÍCH THƯỚC KHUNG HÌNH</small><b>{analysis.video.width} × {analysis.video.height}</b></div><div><small>TỐC ĐỘ KHUNG HÌNH</small><b>{analysis.video.fps.toFixed(2)} fps</b></div><div><small>SỐ PHÂN CẢNH</small><b>{analysis.shots.length}</b></div><div><small>NHỊP ĐIỆU</small><b>{analysis.music.tempo ? `${analysis.music.tempo} BPM` : "Chưa nhận diện"}</b></div></div><div className="scene-list">{analysis.shots.map((shot)=><div className="scene-row" key={shot.index}><span className="scene-index">{String(shot.index+1).padStart(2,"0")}</span><div className="scene-time">{shot.start_s.toFixed(1)}s ? {shot.end_s.toFixed(1)}s</div><div className="scene-meter"><i style={{width:`${Math.max(8,Math.min(100,shot.tracked_ratio*100))}%`}}/></div><span className="scene-meta">{analysis.events.filter((event)=>event.shot===shot.index).length} hiệu ứng</span></div>)}</div></section>}<MarketingTools project={selected}/><button className="text-link back-link" onClick={()=>onOpen("")}>← Quay lại danh sách dự án</button></>;
  return <><PageTitle eyebrow="KHÔNG GIAN LÀM VIỆC" title="Dự án" subtitle="Theo dõi video mẫu, kịch bản phân cảnh và bản dựng." action={<button className="button primary" onClick={onCreate}>＋ Dự án mới</button>}/><section className="panel projects-panel">{projects.length?<ProjectTable projects={projects} onOpen={onOpen}/>:<div className="empty-state"><div className="empty-icon">▤</div><h2>Dự án của bạn sẽ hiển thị tại đây</h2><p>Tải video mẫu lên để bắt đầu sản phẩm AI đầu tiên.</p><button className="button primary" onClick={onCreate}>Tạo dự án</button></div>}</section></>;
}

function ProjectTable({ projects, onOpen }: { projects: Project[]; onOpen: (id:string)=>void }) {
  return <div className="table-scroll"><table className="project-table"><thead><tr><th>DỰ ÁN</th><th>CHẾ ĐỘ</th><th>NGÀY TẠO</th><th>TRẠNG THÁI</th><th/></tr></thead><tbody>{projects.map((project,index)=><tr key={project.id} onClick={()=>onOpen(project.id)}><td><div className="project-cell"><div className={`project-thumb thumb-${index%4}`}>▶</div><div><b>{project.name}</b><small>{project.sourceName}</small></div></div></td><td><span className="mode-tag">{modeLabel(project.mode)}</span></td><td>{formatDate(project.createdAt)}</td><td><span className="status-tag"><i/>{statusLabel(project.status)}</span></td><td><span className="row-arrow">↗</span></td></tr>)}</tbody></table></div>;
}

function Library({ projects, onOpen }: { projects: Project[]; onOpen: (id:string)=>void }) {
  return <><PageTitle eyebrow="THƯ VIỆN TƯ LIỆU" title="Thư viện video" subtitle="Duyệt video nguồn, phân cảnh đã tạo và video đã xuất."/><div className="library-toolbar"><div className="library-tabs"><button className="selected">Tất cả tư liệu <span>{projects.length}</span></button><button>Video mẫu</button><button>Phân cảnh đã tạo <span>0</span></button><button>Video đã xuất <span>0</span></button></div><button className="select-pill">Mới thêm gần đây ⌄</button></div>{projects.length?<div className="library-grid">{projects.map((project,index)=><button className="library-card" key={project.id} onClick={()=>onOpen(project.id)}><div className={`library-art art-${index%4}`}><div className="art-grid"/><span className="play-button">▶</span><span className="asset-kind">VIDEO MẪU</span></div><div className="library-card-copy"><b>{project.name}</b><small>{project.sourceName}</small><span>{formatDate(project.createdAt)} <i>·</i> {modeLabel(project.mode)}</span></div></button>)}</div>:<section className="panel empty-library"><div className="empty-icon">▧</div><h2>Thư viện đang chờ bạn</h2><p>Video mẫu bạn thêm sẽ được sắp xếp tại đây.</p></section>}</>;
}

function AISettings({ prompt, setPrompt, selectedModels, setSelectedModels, modelConnections, onConnect, onSave }: { prompt: string; setPrompt: (value:string)=>void; selectedModels: string[]; setSelectedModels: Dispatch<SetStateAction<string[]>>; modelConnections: Record<string, ModelConnection>; onConnect: (id:string)=>void; onSave:()=>void }) {
  function toggleModel(id: string) {
    setSelectedModels((current) => {
      if (current.includes(id)) return current.length > 1 ? current.filter((item) => item !== id) : current;
      if (current.length >= 3) return current;
      onConnect(id);
      return [...current, id];
    });
  }
  return <><PageTitle eyebrow={"C\u1ea4U H\u00ccNH"} title={"C\u00e0i \u0111\u1eb7t AI"} subtitle={"Ch\u1ecdn nh\u00f3m m\u00f4 h\u00ecnh v\u00e0 h\u01b0\u1edbng d\u1eabn s\u00e1ng t\u1ea1o cho d\u1ef1 \u00e1n m\u1edbi."}/><div className="settings-layout"><div className="settings-main"><section className="panel settings-card"><div className="panel-head"><div><div className="eyebrow">{"NH\u00d3M M\u00d4 H\u00ccNH"}</div><h2>{"Ch\u1ecdn 1\u20133 m\u00f4 h\u00ecnh"}</h2></div><span className="saved-local">{selectedModels.length} {"\u0111\u00e3 ch\u1ecdn"}</span></div><p className="settings-intro">{"M\u1ed9t s\u1ed1 nh\u00e0 cung c\u1ea5p c\u00f3 g\u00f3i mi\u1ec5n ph\u00ed nh\u01b0ng v\u1eabn c\u1ea7n API key. Ollama ch\u1ea1y tr\u00ean m\u00e1y th\u00ec kh\u00f4ng c\u1ea7n key. Ch\u1ecdn model \u0111\u1ec3 t\u1ef1 ki\u1ec3m tra k\u1ebft n\u1ed1i."}</p><div className="model-options">{MODEL_OPTIONS.map((model)=><label className={`model-option ${selectedModels.includes(model.id)?"checked":""}`} key={model.id}><input type="checkbox" checked={selectedModels.includes(model.id)} onChange={()=>toggleModel(model.id)} disabled={!selectedModels.includes(model.id)&&selectedModels.length>=3}/><span className="model-checkbox">\u2713</span><span className="model-details"><b>{model.name}</b><small>{model.provider} \u00b7 {model.role}</small>{selectedModels.includes(model.id) && <small className={`connection-state ${modelConnections[model.id]?.state || "checking"}`}>{modelConnections[model.id]?.message || "\u0110ang ki\u1ec3m tra k\u1ebft n\u1ed1i\u2026"}</small>}</span><span className={`model-tier ${model.kind}`}>{model.tier}</span></label>)}</div><div className="provider-security"><span>\u24d8</span><p>{"API key ch\u1ec9 \u0111\u01b0\u1ee3c \u0111\u1ecdc t\u1eeb m\u00f4i tr\u01b0\u1eddng m\u00e1y ch\u1ee7, kh\u00f4ng l\u01b0u trong tr\u00ecnh duy\u1ec7t. Ollama t\u1ef1 k\u1ebft n\u1ed1i khi \u0111ang ch\u1ea1y tr\u00ean m\u00e1y."}</p></div></section><section className="panel settings-card prompt-settings"><div className="panel-head"><div><div className="eyebrow">{"H\u01af\u1edaNG D\u1eaaN S\u00c1NG T\u1ea0O"}</div><h2>{"H\u01b0\u1edbng d\u1eabn AI theo phong c\u00e1ch c\u1ee7a b\u1ea1n"}</h2></div><span className="saved-local">{"\u0110\u00e3 l\u01b0u tr\u00ean m\u00e1y"}</span></div><p className="settings-intro">{"Th\u00eam y\u00eau c\u1ea7u s\u00e1ng t\u1ea1o m\u1eb7c \u0111\u1ecbnh \u0111\u1ec3 \u0111\u1ecbnh h\u01b0\u1edbng ph\u00e2n t\u00edch, prompt ph\u00e2n c\u1ea3nh v\u00e0 r\u00e0 so\u00e1t ch\u1ea5t l\u01b0\u1ee3ng cho d\u1ef1 \u00e1n m\u1edbi."}</p><label className="field-label">{"PROMPT S\u00c1NG T\u1ea0O CHUNG"}<textarea value={prompt} onChange={(event)=>setPrompt(event.target.value)} rows={7} placeholder={"V\u00ed d\u1ee5: Gi\u1eef nh\u00e2n v\u1eadt nh\u1ea5t qu\u00e1n gi\u1eefa c\u00e1c c\u1ea3nh. D\u00f9ng l\u1eddi tho\u1ea1i ti\u1ebfng Vi\u1ec7t t\u1ef1 nhi\u00ean, \u00e1nh s\u00e1ng \u0111i\u1ec7n \u1ea3nh, b\u1ed1 c\u1ee5c g\u1ecdn v\u00e0 tr\u00e1nh rung m\u00e1y nhanh\u2026"}/></label><div className="prompt-actions"><small>{"Ch\u1ec9 l\u01b0u trong tr\u00ecnh duy\u1ec7t tr\u00ean thi\u1ebft b\u1ecb n\u00e0y."}</small><button className="button primary" onClick={onSave}>{"L\u01b0u c\u00e0i \u0111\u1eb7t"}</button></div></section></div><aside className="panel info-card"><div className="info-icon">\u2726</div><h3>{"C\u00e1c m\u00f4 h\u00ecnh chuy\u00ean bi\u1ec7t ph\u1ed1i h\u1ee3p hi\u1ec7u qu\u1ea3 h\u01a1n."}</h3><p>{"Khi \u0111\u01b0\u1ee3c k\u1ebft n\u1ed1i, c\u00e1c m\u00f4 h\u00ecnh c\u00f3 th\u1ec3 l\u1ea7n l\u01b0\u1ee3t r\u00e0 so\u00e1t v\u00e0 ho\u00e0n thi\u1ec7n k\u1ecbch b\u1ea3n ph\u00e2n c\u1ea3nh c\u00f9ng prompt."}</p><div className="info-rule"/><div className="info-stage"><span>01</span><b>{"L\u1ef1a ch\u1ecdn mi\u1ec5n ph\u00ed"}</b><small>Gemini, OpenRouter, Groq ho\u1eb7c Ollama tr\u00ean m\u00e1y</small></div><div className="info-stage"><span>02</span><b>{"L\u1ef1a ch\u1ecdn tr\u1ea3 ph\u00ed"}</b><small>C\u00e1c m\u00f4 h\u00ecnh Claude v\u00e0 OpenAI</small></div><div className="info-stage"><span>03</span><b>{"T\u1ea1o video"}</b><small>D\u1ef1 ki\u1ebfn t\u00edch h\u1ee3p Veo, Kling, Runway</small></div></aside></div></>;
}
