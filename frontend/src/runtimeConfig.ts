type DesktopSidecarInfo = {
  apiBaseUrl: string;
  pid: number;
  port: number;
  sidecarToken: string;
};

const envApiBase = (import.meta.env.VITE_API_BASE_URL || "").trim();
const defaultApiBase = envApiBase || "/api";

function isDesktopRuntime(): boolean {
  if (typeof window === "undefined") return false;
  return "__TAURI_INTERNALS__" in window;
}

let apiBaseUrl = defaultApiBase;
// Detected synchronously at module load so the UI knows it's the desktop app
// before the (potentially slow) sidecar startup completes. This lets App render
// the live initializing screen immediately instead of the static placeholder.
let desktopRuntime = isDesktopRuntime();
let lastDesktopError: string | null = null;
let sidecarToken: string | null = null;

export async function initializeRuntimeConfig(): Promise<void> {
  if (!isDesktopRuntime()) return;
  desktopRuntime = true;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    const info = await invoke<DesktopSidecarInfo>("start_backend_sidecar");
    apiBaseUrl = info.apiBaseUrl;
    sidecarToken = info.sidecarToken;
    lastDesktopError = null;
  } catch (error) {
    lastDesktopError = error instanceof Error ? error.message : String(error);
    throw error;
  }
}

export function getApiBaseUrl(): string {
  return apiBaseUrl;
}

export function isDesktopApp(): boolean {
  return desktopRuntime;
}

export function getLastDesktopError(): string | null {
  return lastDesktopError;
}

export function getSidecarToken(): string | null {
  return sidecarToken;
}

export async function restartDesktopSidecar(): Promise<void> {
  if (!isDesktopRuntime()) return;
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("stop_backend_sidecar");
  const info = await invoke<DesktopSidecarInfo>("start_backend_sidecar");
  apiBaseUrl = info.apiBaseUrl;
  sidecarToken = info.sidecarToken;
  lastDesktopError = null;
}

export async function safeExitDesktopApp(): Promise<void> {
  if (!isDesktopRuntime()) return;
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("stop_backend_sidecar");
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  await getCurrentWindow().close();
}
