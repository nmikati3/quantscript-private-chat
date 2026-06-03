/**
 * Tests for the frontend API layer (src/api.ts).
 *
 * We mock `fetch` globally and verify that each API function sends the
 * correct request and parses the response properly.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Mock runtimeConfig before importing api
vi.mock("../runtimeConfig", () => ({
  getApiBaseUrl: () => "http://localhost:8000",
  getSidecarToken: () => null,
  isDesktopApp: () => false,
  initializeRuntimeConfig: vi.fn(),
}));

// Mock logger to suppress output during tests
vi.mock("../logger", () => ({
  logger: { log: vi.fn(), error: vi.fn(), warn: vi.fn() },
}));

import type { Message } from "../App";
import {
  fetchStartupStatus,
  sendStreamingMessage,
  type StreamingOptions,
  createConversation,
  getConversations,
  deleteConversation,
  addMessageToConversation,
  getConversationMessages,
  updateConversationTitle,
  uploadChatAttachmentFromBrowser,
} from "../api";

function testMessage(
  role: Message["role"],
  content: string,
  id = "test-msg-1",
): Message {
  return { id, role, content };
}

/** Short timeouts so open streams cannot leave 120s timers behind in watch mode. */
const testStreamOptions: StreamingOptions = {
  firstChunkTimeoutMs: 30_000,
  idleTimeoutMs: 30_000,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("fetchStartupStatus", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("returns parsed status on success", async () => {
    const payload = { ready: true, error: null, phases: [] };
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse(payload));

    const result = await fetchStartupStatus();
    expect(result).toEqual(payload);
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/startup_status",
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });

  it("throws on non-OK response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("fail", { status: 503 }),
    );
    await expect(fetchStartupStatus()).rejects.toThrow("startup_status 503");
  });
});

describe("createConversation", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("sends messages and returns conversation_id", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse({ conversation_id: "abc-123" }),
    );

    const messages = [testMessage("user", "hi")];
    const id = await createConversation(messages);
    expect(id).toBe("abc-123");

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("http://localhost:8000/create_conversation");
    expect(init?.method).toBe("POST");
    const body = JSON.parse(init?.body as string);
    expect(body.messages).toHaveLength(1);
    expect(body.messages[0].role).toBe("user");
  });

  it("throws on failure", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("error", { status: 500 }),
    );
    await expect(
      createConversation([testMessage("user", "hi")]),
    ).rejects.toThrow("Failed to create conversation");
  });
});

describe("getConversations", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("returns conversation list", async () => {
    const conversations = [
      { id: "1", title: "Chat 1", createdAt: "2026-01-01", updatedAt: "2026-01-01" },
    ];
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse({ conversations }),
    );

    const result = await getConversations();
    expect(result).toEqual(conversations);
  });

  it("returns empty array when field is missing", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse({}));
    const result = await getConversations();
    expect(result).toEqual([]);
  });
});

describe("deleteConversation", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("sends correct request", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse({ status: "success" }));
    await deleteConversation("conv-1");

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("http://localhost:8000/delete_conversation");
    const body = JSON.parse(init?.body as string);
    expect(body.conversation_id).toBe("conv-1");
  });

  it("throws on failure", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("error", { status: 500 }),
    );
    await expect(deleteConversation("conv-1")).rejects.toThrow();
  });
});

describe("addMessageToConversation", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("sends message payload", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse({ status: "success" }));
    await addMessageToConversation(
      "conv-1",
      testMessage("assistant", "hello", "test-msg-2"),
    );

    const body = JSON.parse(vi.mocked(fetch).mock.calls[0][1]?.body as string);
    expect(body.conversation_id).toBe("conv-1");
    expect(body.role).toBe("assistant");
    expect(body.content).toBe("hello");
  });
});

describe("updateConversationTitle", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("sends title update", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse({ status: "success" }));
    await updateConversationTitle("conv-1", "New Title");

    const body = JSON.parse(vi.mocked(fetch).mock.calls[0][1]?.body as string);
    expect(body.conversation_id).toBe("conv-1");
    expect(body.new_title).toBe("New Title");
  });

  it("throws on failure", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("error", { status: 400 }),
    );
    await expect(updateConversationTitle("conv-1", "x")).rejects.toThrow();
  });
});

describe("getConversationMessages", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("returns sorted and mapped messages", async () => {
    const conversation = [
      { role: "user", content: "q", createdAt: "2026-01-01T00:00:01Z" },
      { role: "assistant", content: "a", createdAt: "2026-01-01T00:00:02Z" },
    ];
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse({ status: "success", conversation }),
    );

    const result = await getConversationMessages("conv-1");
    expect(result).toHaveLength(2);
    expect(result[0].role).toBe("user");
    expect(result[0].content).toBe("q");
    expect(result[1].role).toBe("assistant");
    expect(result[1].content).toBe("a");
  });

  it("throws on error response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("not found", { status: 404 }),
    );
    await expect(getConversationMessages("conv-1")).rejects.toThrow();
  });
});

describe("sendStreamingMessage", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => {
    vi.useRealTimers();
  });

  it("streams chunks to callback", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode("Hello"));
        controller.enqueue(encoder.encode(" world"));
        controller.close();
      },
    });

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(stream, { status: 200 }),
    );

    const chunks: string[] = [];
    await sendStreamingMessage(
      [{ role: "user", content: "hi" }],
      false,
      (chunk) => chunks.push(chunk),
      undefined,
      testStreamOptions,
    );

    expect(chunks).toEqual(["Hello", " world"]);
  });

  it("throws on non-OK response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("error", { status: 500 }),
    );

    await expect(
      sendStreamingMessage(
        [{ role: "user", content: "hi" }],
        false,
        () => {},
        undefined,
        testStreamOptions,
      ),
    ).rejects.toThrow("Failed to send streaming message");
  });

  it("passes abort signal to fetch", async () => {
    const stream = new ReadableStream({
      start(controller) {
        controller.close();
      },
    });
    const abortController = new AbortController();

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(stream, { status: 200 }),
    );

    await sendStreamingMessage(
      [{ role: "user", content: "hi" }],
      false,
      () => {},
      undefined,
      { ...testStreamOptions, signal: abortController.signal },
    );

    const init = vi.mocked(fetch).mock.calls[0][1];
    expect(init?.signal).toBeInstanceOf(AbortSignal);
  });

  it("aborts when first chunk timeout is exceeded", async () => {
    const stream = new ReadableStream({
      start() {
        // never enqueue or close — simulates a hung backend stream
      },
    });

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(stream, { status: 200 }),
    );

    await expect(
      sendStreamingMessage(
        [{ role: "user", content: "hi" }],
        false,
        () => {},
        undefined,
        { firstChunkTimeoutMs: 50, idleTimeoutMs: 5000 },
      ),
    ).rejects.toMatchObject({ name: "StreamTimeoutError" });
  });

  it("includes search flag and upload path in request", async () => {
    const stream = new ReadableStream({
      start(controller) {
        controller.close();
      },
    });

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(stream, { status: 200 }),
    );

    await sendStreamingMessage(
      [{ role: "user", content: "find info" }],
      true,
      () => {},
      "/tmp/file.pdf",
      testStreamOptions,
    );

    const body = JSON.parse(vi.mocked(fetch).mock.calls[0][1]?.body as string);
    expect(body.search).toBe(true);
    expect(body.chat_upload_local_path).toBe("/tmp/file.pdf");
  });
});

describe("uploadChatAttachmentFromBrowser", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("uploads file and returns path", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse({ path: "/tmp/upload.csv" }),
    );

    const file = new File(["a,b,c"], "data.csv", { type: "text/csv" });
    const result = await uploadChatAttachmentFromBrowser(file);
    expect(result).toBe("/tmp/upload.csv");

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("http://localhost:8000/upload_chat_attachment");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeInstanceOf(FormData);
  });

  it("throws on upload failure", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("too large", { status: 413 }),
    );

    const file = new File(["x"], "big.csv", { type: "text/csv" });
    await expect(uploadChatAttachmentFromBrowser(file)).rejects.toThrow(
      "Failed to upload attachment",
    );
  });
});
