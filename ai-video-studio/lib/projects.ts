import path from "node:path";

export type ProjectRecord = {
  id: string;
  name: string;
  sourceName: string;
  sourceFile: string;
  mode: "Recreate" | "Inspired" | "Auto mode";
  duration: string;
  aspect: string;
  resolution: string;
  prompt: string;
  status: "Pending" | "Queued" | "Analyzing" | "Analysis complete" | "Failed";
  createdAt: string;
  progress?: string;
  analysisError?: string;
  analysisFile?: string;
};

export const dataRoot = () => path.resolve(process.env.STUDIO_DATA_DIR || path.join(process.cwd(), "storage"));
