# AI Video Studio

Local web application scaffold for the AI Video Studio product brief. It is a separate Next.js application; the existing CapCut desktop tool remains unchanged.

## Run locally

From the workspace root, double-click `Run AI Video Studio.bat`, or use PowerShell:

```powershell
cd ai-video-studio
npm run dev
```

Open `http://localhost:3000` in a browser. Node.js 20.9 or newer is required.

## Current slice

- Responsive workspace with overview, create, project, library, and AI settings screens.
- Create a project with a local reference video, mode, target length, aspect ratio, resolution, and creative direction.
- Project metadata and source videos persist under `storage/` on the machine running the Next.js server. `STUDIO_DATA_DIR` can point this data to another local directory.
- Local upload limit is 200 MB per video. Supported file extensions: MP4, MOV, M4V, WebM.
- The source video can be previewed or deleted with its project.
- AI creative guidance and a selection of one to three free/paid model profiles are stored in the current browser's local storage.
- A local Python worker can run the repository's OpenCV scene, movement, transition, and overlay analysis; results and a visual summary are saved with the project. Audio/beat extraction needs FFmpeg; visual analysis continues if FFmpeg is missing.
- Project-level social marketing tools can generate a PNG cover from a chosen video timestamp, add a headline and brand label, and export vertical 9:16, portrait 4:5, or square 1:1 artwork.
- The social post QC checks video readability, aspect ratio, resolution, duration, and file size against a selected Facebook Reels, Facebook Feed, TikTok organic, or TikTok in-feed ad target. Audio, safe-zone placement, rights, and disclosure remain manual checks.
- Cover generation and technical checks run locally through OpenCV and PySide6 in the workspace `.venv` Python installation; no video is sent to an AI image service.

## Not connected yet

The local analysis worker is only the first processing stage. AI video understanding, AI storyboard generation, video scene-generation adapters, final video rendering, retry and cost policy, and automated audio/content review still need implementation. The provider/model selections and creative prompt are not yet passed to any provider. Do not put API keys into the browser UI; provider credentials belong in a server-side secret store.

The current project store is a single-user local JSON file. It is a development scaffold, not a multi-user or production deployment. Before public deployment, replace it with authenticated project access, PostgreSQL, private object storage, and a durable worker queue.

## Model connection

Selecting a model checks its provider automatically. Ollama at `http://127.0.0.1:11434` needs no API key; install and run Ollama, then download the configured local model with `ollama pull llama3.1`. Hosted providers require their own server-side key even when the selected model has a free tier. Add the relevant variable to `ai-video-studio/.env.local`, then restart Next.js: `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`, `ANTHROPIC_API_KEY`, or `OPENAI_API_KEY`. Keys are never sent to or stored in the browser. Choosing a model checks provider availability; it does not yet send project prompts or run model inference.
