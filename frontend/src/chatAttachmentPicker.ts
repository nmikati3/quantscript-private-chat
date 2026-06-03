import { uploadChatAttachmentFromBrowser } from "./api";

/** Mirror of backend `ALLOWED_EXTENSIONS` in `chat_attachments.py`. */
export const CHAT_ATTACHMENT_EXTENSIONS = [
  "png",
  "jpg",
  "jpeg",
  "pdf",
  "xlsx",
  "csv",
  "parquet",
  "json",
] as const;

/** Extensions passed to the desktop open dialog (no leading dot). */
export const CHAT_ATTACHMENT_DIALOG_EXTENSIONS = [...CHAT_ATTACHMENT_EXTENSIONS];

export const CHAT_ALLOWED_ATTACHMENT_EXTS = new Set(
  CHAT_ATTACHMENT_EXTENSIONS.map((ext) => `.${ext}`),
);

/** Value for `<input type="file" accept="...">` in browser mode. */
export const CHAT_ATTACHMENT_ACCEPT = CHAT_ATTACHMENT_EXTENSIONS.map((ext) => `.${ext}`).join(",");

export function fileBasename(pathOrName: string): string {
  return pathOrName.replace(/\\/g, "/").split("/").pop() ?? pathOrName;
}

/** Used to decide whether to show a subtitle line with a filesystem path vs. filename only. */
export function looksLikeFullFilesystemPath(p: string): boolean {
  if (!p) return false;
  if (p.startsWith("/")) return true;
  if (/^[a-zA-Z]:[\\/]/.test(p)) return true;
  return p.includes("/") || (p.includes("\\") && p.length > 1);
}

/**
 * Desktop (Tauri): native file dialog, read bytes via Rust, upload to backend.
 * Returns the backend temp path plus the real path chosen by the user for display.
 */
export async function pickChatAttachmentDesktop(): Promise<{
  serverPath: string;
  displayPath: string;
} | null> {
  const { open } = await import("@tauri-apps/plugin-dialog");
  const { invoke } = await import("@tauri-apps/api/core");
  const selected = await open({
    multiple: false,
    filters: [
      {
        name: "Attachments",
        extensions: CHAT_ATTACHMENT_DIALOG_EXTENSIONS,
      },
    ],
  });
  if (selected == null) return null;
  const path = Array.isArray(selected) ? selected[0] : selected;
  if (!path) return null;

  await invoke("authorize_file_path", { path });
  const raw = await invoke<number[] | Uint8Array>("read_binary_file", { path });
  const uint8 = raw instanceof Uint8Array ? raw : new Uint8Array(raw);
  const name = fileBasename(path);
  const bytesForFile = new Uint8Array(uint8);
  const file = new File([bytesForFile], name);
  const serverPath = await uploadChatAttachmentFromBrowser(file);
  return { serverPath, displayPath: path };
}
