import { type Message } from "./App";
import { logger } from "./logger";
import { getApiBaseUrl, getSidecarToken } from "./runtimeConfig";

// In local dev, Vite proxies /api to VITE_BACKEND_URL
// In desktop mode, this is replaced at startup with a loopback sidecar URL.
const API_URL = () => getApiBaseUrl();

export type StartupPhaseStatus = "pending" | "running" | "done" | "error";

export interface StartupPhase {
  id: string;
  label: string;
  status: StartupPhaseStatus;
  /** 0–100 when the backend reports Hugging Face download progress */
  percent?: number;
  /** Human-readable sub-step, e.g. current file or "Loading into memory" */
  detail?: string;
}

export interface StartupStatusPayload {
  ready: boolean;
  error: string | null;
  phases: StartupPhase[];
  /** False on low-memory (< 16 GB RAM) machines where deep research can't run. */
  deepResearchAvailable?: boolean;
}

/** Poll while the backend loads models. */
export async function fetchStartupStatus(): Promise<StartupStatusPayload> {
  const headers: Record<string, string> = {};
  const token = getSidecarToken();
  if (token) {
    headers["X-Sidecar-Token"] = token;
  }
  const response = await fetch(`${API_URL()}/startup_status`, { headers });
  if (!response.ok) {
    throw new Error(`startup_status ${response.status}`);
  }
  return response.json();
}

async function getAuthHeaders(): Promise<HeadersInit> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getSidecarToken();
  if (token) {
    headers["X-Sidecar-Token"] = token;
  }
  return headers;
}

function chatPayload(
  base: Record<string, unknown>,
  chatUploadLocalPath?: string | null
): string {
  const payload = chatUploadLocalPath
    ? { ...base, chat_upload_local_path: chatUploadLocalPath }
    : base;
  return JSON.stringify(payload);
}

/** Time to wait for the first streamed byte before aborting (local LLM can be slow). */
export const STREAM_FIRST_CHUNK_TIMEOUT_MS = 120_000;
/** Max idle time between chunks once streaming has started. */
export const STREAM_IDLE_TIMEOUT_MS = 60_000;

export type StreamingOptions = {
  signal?: AbortSignal;
  firstChunkTimeoutMs?: number;
  idleTimeoutMs?: number;
};

export async function sendStreamingMessage(
  messages: Array<{ role: string; content: string; attachmentPath?: string }>,
  search: boolean,
  onChunk: (chunk: string) => void,
  chatUploadLocalPath?: string | null,
  options?: StreamingOptions,
): Promise<void> {
  const body = chatPayload({ messages, search }, chatUploadLocalPath);
  const firstChunkTimeoutMs = options?.firstChunkTimeoutMs ?? STREAM_FIRST_CHUNK_TIMEOUT_MS;
  const idleTimeoutMs = options?.idleTimeoutMs ?? STREAM_IDLE_TIMEOUT_MS;

  const controller = new AbortController();
  const { signal: externalSignal } = options ?? {};

  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalSignal.addEventListener("abort", () => controller.abort(), { once: true });
    }
  }

  let receivedChunk = false;
  let timedOut = false;
  let firstChunkTimer: ReturnType<typeof setTimeout> | undefined;
  let idleTimer: ReturnType<typeof setTimeout> | undefined;

  const throwStreamTimeout = (hadChunks: boolean): never => {
    const err = new Error(
      hadChunks
        ? "Stream timed out (no data received for a while)"
        : "Stream timed out (no response from server)",
    );
    err.name = "StreamTimeoutError";
    throw err;
  };

  const clearStreamTimers = () => {
    if (firstChunkTimer !== undefined) {
      clearTimeout(firstChunkTimer);
      firstChunkTimer = undefined;
    }
    if (idleTimer !== undefined) {
      clearTimeout(idleTimer);
      idleTimer = undefined;
    }
  };

  const armIdleTimer = () => {
    if (idleTimer !== undefined) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, idleTimeoutMs);
  };

  firstChunkTimer = setTimeout(() => {
    if (!receivedChunk) {
      timedOut = true;
      controller.abort();
    }
  }, firstChunkTimeoutMs);

  const headers = await getAuthHeaders();
  let response: Response;
  try {
    response = await fetch(`${API_URL()}/stream_text_response`, {
      method: "POST",
      headers: headers,
      body: body,
      signal: controller.signal,
    });
  } catch (error) {
    clearStreamTimers();
    if (timedOut) {
      throwStreamTimeout(receivedChunk);
    }
    throw error;
  }

  if (!response.ok) {
    clearStreamTimers();
    const errorText = await response.text().catch(() => response.statusText);
    throw new Error(`Failed to send streaming message: ${response.status} ${errorText}`);
  }

  if (!response.body) {
    clearStreamTimers();
    throw new Error("Response body is null");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  const cancelReaderOnAbort = () => {
    void reader.cancel().catch(() => {});
  };
  controller.signal.addEventListener("abort", cancelReaderOnAbort);

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      receivedChunk = true;
      clearStreamTimers();
      armIdleTimer();

      const chunk = decoder.decode(value, { stream: true });
      onChunk(chunk);
    }

    if (timedOut) {
      throwStreamTimeout(receivedChunk);
    }
  } catch (error) {
    if (timedOut) {
      throwStreamTimeout(receivedChunk);
    }
    throw error;
  } finally {
    controller.signal.removeEventListener("abort", cancelReaderOnAbort);
    clearStreamTimers();
    reader.releaseLock();
  }
}

export async function sendDeepResearchMessage(
  messages: Array<{ role: string; content: string }>,
  onProgress: (progress: string) => void,
  onClarificationQuestion: (clarifications: string) => void,
  onFinalReport: (finalReport: string) => void,
  onError: (error: string) => void,
  onDone: () => void,
  chatUploadLocalPath?: string | null,
  signal?: AbortSignal,
): Promise<void> {
  const body = chatPayload({ messages }, chatUploadLocalPath);

  const headers = await getAuthHeaders();
  const response = await fetch(`${API_URL()}/deep_research_response`, {
    method: "POST",
    headers: headers,
    body: body,
    signal,
  });

  if (!response.ok) {
    const errorText = await response.text().catch(() => response.statusText);
    onError(`Failed to send deep research message: ${response.status} ${errorText}`);
    return;
  }

  if (!response.body) {
    throw new Error("Response body is null");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      
      // Process complete SSE events (lines ending with \n\n)
      const lines = buffer.split("\n\n");
      buffer = lines.pop() || ""; // Keep incomplete line in buffer

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          const data = line.slice(6); // Remove "data: " prefix
          try {
            const parsed = JSON.parse(data);
            
            if (parsed.type === "progress") {
              onProgress(parsed.content || "");
            } else if (parsed.type === "clarification_question") {
              onClarificationQuestion(parsed.clarification_question || "");
            } else if (parsed.type === "final_report") {
              onFinalReport(parsed.final_report || "");
            } else if (parsed.type === "done") {
              onDone();
              return;
            } else if (parsed.type === "message" && parsed.error) {
              onError(parsed.error || "Unknown error");
              return;
            } else if (parsed.type === "error") {
              onError(parsed.message || "Unknown error");
              return;
            }
          } catch (e) {
            // Keep the always-on error log free of conversation content; the
            // raw SSE payload is only emitted in development.
            logger.error("Error parsing SSE data:", e);
            logger.log("Raw SSE data:", data);
          }
        }
      }
    }
    
    // Process any remaining buffer
    if (buffer.trim()) {
      const lines = buffer.split("\n\n");
      for (const line of lines) {
        if (line.startsWith("data: ")) {
          const data = line.slice(6);
          try {
            const parsed = JSON.parse(data);
            if (parsed.type === "done") {
              onDone();
            } else if (parsed.type === "message" && parsed.error) {
              onError(parsed.error || "Unknown error");
            } else if (parsed.type === "error") {
              onError(parsed.message || "Unknown error");
            }
          } catch (e) {
            logger.error("Error parsing final SSE data:", e);
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
}

export async function getConversations(): Promise<Conversation[]> {

  const endpoint = "/get_all_conversations";
  const headers = await getAuthHeaders();
  
  const response = await fetch(`${API_URL()}${endpoint}`, {
    method: "POST",
    headers: headers
  });

  if (!response.ok) {
    throw new Error("Failed to fetch conversations");
  }

  const data = await response.json();
  return data.conversations || [];
}

export async function updateConversationTitle(conversationId: string, newTitle: string): Promise<void> {

  const endpoint = "/update_conversation_title";
  const body = JSON.stringify({ conversation_id: conversationId, new_title: newTitle });
  const headers = await getAuthHeaders();

  const response = await fetch(`${API_URL()}${endpoint}`, {
    method: "POST",
    headers: headers,
    body: body,
  });

  if (!response.ok) {
    throw new Error("Failed to update conversation title");
  }
}

export async function deleteConversation(conversationId: string): Promise<void> {
  const endpoint = "/delete_conversation";
  const body = JSON.stringify({ conversation_id: conversationId });
  const headers = await getAuthHeaders();

  const response = await fetch(`${API_URL()}${endpoint}`, {
    method: "POST",
    headers: headers,
    body: body,
  });

  if (!response.ok) {
    throw new Error("Failed to delete conversation");
  }
}

export async function createConversation(messages: Array<Message>): Promise<string> {
  const endpoint = "/create_conversation";
  const body = JSON.stringify({ messages: messages.map((message) => ({
    role: message.role,
    content: message.content,
    // The live temp path is sent on the inference request, not persisted here.
    ...(message.attachmentName ? { attachmentName: message.attachmentName } : {}),
  })) });
  const headers = await getAuthHeaders();

  const response = await fetch(`${API_URL()}${endpoint}`, {
    method: "POST",
    headers: headers,
    body: body,
  });

  if (!response.ok) {
    throw new Error("Failed to create conversation");
  }

  const data = await response.json();
  // Return conversation ID from response
  return data.conversation_id || data.conversation?.id || "";
}


export async function getConversationMessages(conversationId: string): Promise<Array<{ role: string; content: string; attachmentName?: string; response_type?: string; code?: string | null; isComplete?: boolean; progress?: string; isDeepResearch?: boolean }>> {
  const endpoint = "/get_conversation_by_id";
  const body = JSON.stringify({ conversation_id: conversationId });
  const headers = await getAuthHeaders();

  const response = await fetch(`${API_URL()}${endpoint}`, {
    method: "POST",
    headers: headers,
    body: body,
  });

  if (!response.ok) {
    const errorText = await response.text();
    // Log only the status in the always-on error path; the response body may
    // echo request content and is restricted to development.
    logger.error("API Error Response:", response.status, response.statusText);
    logger.log("API Error Response body:", errorText);
    throw new Error(`Failed to get conversation messages: ${response.status} ${response.statusText}`);
  }

  const data = await response.json();
  logger.log("Full API response:", data);
  
  const rawMessages = data.conversation;
  
  if (!Array.isArray(rawMessages) || rawMessages.length === 0) {
    if (!Array.isArray(rawMessages)) {
      logger.warn("data.conversation is not an array. Full response:", data);
    }
    return [];
  }
  
  interface RawMessage {
    role: string;
    content: string;
    createdAt?: string;
    attachmentName?: string;
    isComplete?: boolean;
    progress?: string;
    isDeepResearch?: boolean;
  }

  const sortedMessages = [...(rawMessages as RawMessage[])].sort((a, b) => {
    const dateA = a.createdAt ? new Date(a.createdAt).getTime() : 0;
    const dateB = b.createdAt ? new Date(b.createdAt).getTime() : 0;
    return dateA - dateB;
  });
  
  const mappedMessages = sortedMessages.map((msg) => ({
    role: msg.role,
    content: msg.content,
    ...(msg.attachmentName ? { attachmentName: msg.attachmentName } : {}),
  }));
  
  return mappedMessages;
}


export async function addMessageToConversation(conversationId: string, message: Message): Promise<void> {
  const endpoint = "/add_message_to_conversation";
  const body = JSON.stringify({ 
    conversation_id: conversationId, 
    role: message.role, 
    content: message.content, 
    ...(message.attachmentPath ? { attachmentPath: message.attachmentPath } : {}),
  });
  const headers = await getAuthHeaders();

  const response = await fetch(`${API_URL()}${endpoint}`, {
    method: "POST",
    headers: headers,
    body: body,
  });

  if (!response.ok) {
    throw new Error("Failed to add message to conversation");
  }
}

/** Remove a temp attachment from the backend (best-effort). */
export async function deleteChatAttachment(path: string): Promise<void> {
  const headers = await getAuthHeaders();
  const response = await fetch(`${API_URL()}/delete_chat_attachment`, {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!response.ok) {
    const errorText = await response.text().catch(() => response.statusText);
    throw new Error(`Failed to delete attachment: ${response.status} ${errorText}`);
  }
}

/** Upload a file chosen in the browser; returns a temp path on the backend. */
export async function uploadChatAttachmentFromBrowser(file: File): Promise<string> {
  const form = new FormData();
  form.append("file", file);
  const headers: Record<string, string> = {};
  const token = getSidecarToken();
  if (token) {
    headers["X-Sidecar-Token"] = token;
  }
  const response = await fetch(`${API_URL()}/upload_chat_attachment`, {
    method: "POST",
    headers,
    body: form,
  });

  if (!response.ok) {
    const errorText = await response.text().catch(() => response.statusText);
    throw new Error(`Failed to upload attachment: ${response.status} ${errorText}`);
  }

  const data = await response.json();
  return data.path || "";
}