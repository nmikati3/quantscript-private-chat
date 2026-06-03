import { useState, useRef, useEffect } from "react";
import { 
  sendStreamingMessage,
  sendDeepResearchMessage, 
  createConversation, 
  addMessageToConversation,
  uploadChatAttachmentFromBrowser,
  deleteChatAttachment,
} from "./api";
import { type Message } from "./App";
import type { DeepResearchLivePatch } from "./deepResearchLive";
import { generateMessageId } from "./messageId";
import { SendIcon, PlusIcon, XIcon, PaperclipIcon } from "./icons";
import { logger } from "./logger";
import { isDesktopApp } from "./runtimeConfig";
import {
  pickChatAttachmentDesktop,
  fileBasename,
  looksLikeFullFilesystemPath,
  CHAT_ALLOWED_ATTACHMENT_EXTS,
  CHAT_ATTACHMENT_ACCEPT,
} from "./chatAttachmentPicker";

interface Props {
  onSend: (message: Message) => void;
  updateLastMessage: (updater: (message: Message) => Message) => void;
  messages: Message[] | [];
  onLoadingChange: (
    isLoading: boolean,
    action: string | null,
  ) => void;
  selectedConversationId: string | null;
  activeDeepResearchConversations: Set<string>;
  setSelectedConversationId: (id: string | null) => void;
  setDeepResearchActive: (conversationId: string | null) => void;
  setDeepResearchInactive: (conversationId: string | null) => void;
  applyDeepResearchLive: (
    conversationId: string,
    patch: DeepResearchLivePatch | null,
    messageId?: string,
  ) => void;
  onConversationCreated?: () => void;
}

const ACTIONS = [
  "Web Search",
  "Deep Research"
];

function fileExtensionLower(path: string): string {
  const name = path.replace(/\\/g, "/").split("/").pop() ?? "";
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i).toLowerCase() : "";
}

export default function MessageInput({ onSend, updateLastMessage, messages, onLoadingChange, selectedConversationId, activeDeepResearchConversations, setSelectedConversationId, setDeepResearchActive, setDeepResearchInactive, applyDeepResearchLive, onConversationCreated }: Props) {
  const [text, setText] = useState("");
  const [selectedAction, setSelectedAction] = useState<string | null>(null);
  const [chatUploadLocalPath, setChatUploadLocalPath] = useState<string | null>(null);
  const [chatUploadDisplayPath, setChatUploadDisplayPath] = useState<string | null>(null);
  const [chatUploadFileName, setChatUploadFileName] = useState<string | null>(null);
  const [showUploadMenu, setShowUploadMenu] = useState(false);
  const [reminderMessage, setReminderMessage] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const currentAssistantMessageRef = useRef<Message | null>(null);
  const currentConversationIdRef = useRef<string | null>(null);
  const isNewConversationRef = useRef<boolean>(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const abortReasonRef = useRef<"navigation" | null>(null);
  const deepResearchInFlightRef = useRef(false);
  const selectedConversationIdRef = useRef<string | null>(selectedConversationId);
  /** Persists Web Search intent across null→id assignment when a new conversation is created. */
  const webSearchModeRef = useRef(false);
  const uploadMenuRef = useRef<HTMLDivElement>(null);
  const plusButtonRef = useRef<HTMLButtonElement>(null);
  const chatAttachmentInputRef = useRef<HTMLInputElement>(null);

  // Close upload menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        uploadMenuRef.current &&
        !uploadMenuRef.current.contains(event.target as Node) &&
        plusButtonRef.current &&
        !plusButtonRef.current.contains(event.target as Node)
      ) {
        setShowUploadMenu(false);
      }
    };

    if (showUploadMenu) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => {
        document.removeEventListener("mousedown", handleClickOutside);
      };
    }
  }, [showUploadMenu]);

  const abortInFlightRequest = (reason: "navigation" | null = null) => {
    abortReasonRef.current = reason;
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
  };

  useEffect(() => {
    return () => abortInFlightRequest("navigation");
  }, []);

  const prevConversationIdRef = useRef(selectedConversationId);
  useEffect(() => {
    selectedConversationIdRef.current = selectedConversationId;
  }, [selectedConversationId]);

  useEffect(() => {
    const prev = prevConversationIdRef.current;
    prevConversationIdRef.current = selectedConversationId;
    // Only reset when the user actively switches conversations,
    // not when a new conversation gets its first ID assigned (null → id).
    if (prev !== null && prev !== selectedConversationId) {
      // Deep research keeps running in the background — do not abort its stream.
      if (!deepResearchInFlightRef.current) {
        abortInFlightRequest("navigation");
      }
      webSearchModeRef.current = false;
      setSelectedAction(null);
      setShowUploadMenu(false);
    } else if (
      prev === null &&
      selectedConversationId !== null &&
      webSearchModeRef.current
    ) {
      // New conversation id assigned mid-thread — keep Web Search active.
      setSelectedAction("Web Search");
    }
  }, [selectedConversationId]);

  const isDeepResearchSelected = selectedAction === "Deep Research";
  const anyDeepResearchRunning = activeDeepResearchConversations.size > 0;
  const deepResearchBlocksCurrentChat = anyDeepResearchRunning &&
    (!selectedConversationId || !activeDeepResearchConversations.has(selectedConversationId));
  const uploadDisabled = isDeepResearchSelected || anyDeepResearchRunning;

  const releaseChatAttachment = (path: string | null) => {
    if (!path) return;
    void deleteChatAttachment(path).catch((err: unknown) => {
      logger.error("Failed to delete chat attachment:", err);
    });
  };

  useEffect(() => {
    if (!isDeepResearchSelected) return;
    setShowUploadMenu(false);
    setChatUploadLocalPath((prev) => {
      if (prev) releaseChatAttachment(prev);
      return null;
    });
    setChatUploadDisplayPath(null);
    setChatUploadFileName(null);
  }, [isDeepResearchSelected]);

  const applyChatAttachmentFromPath = (serverPath: string, displayName: string, displayPath?: string) => {
    if (!serverPath) return;
    const ext = fileExtensionLower(displayName);
    if (!ext || !CHAT_ALLOWED_ATTACHMENT_EXTS.has(ext)) {
      setReminderMessage("This file type is not supported.");
      setTimeout(() => setReminderMessage(null), 5000);
      return;
    }
    setChatUploadLocalPath((prev) => {
      if (prev && prev !== serverPath) {
        releaseChatAttachment(prev);
      }
      return serverPath;
    });
    setChatUploadDisplayPath(displayPath ?? null);
    setChatUploadFileName(displayName);
  };
    
  const saveAssistantMessageToDatabase = async (message: Message) => {
    try {
      const conversationId = currentConversationIdRef.current;
      if (conversationId && message.content.trim()) {
        await addMessageToConversation(conversationId, {
          ...message,
          role: "assistant",
          progress: undefined,
        });
      }
    } catch (error) {
      logger.error("Failed to save assistant message to database:", error);
    }
  };

  const patchDeepResearchAssistant = (
    conversationId: string | null,
    messageId: string,
    patch: DeepResearchLivePatch,
  ) => {
    if (!conversationId) return;

    if (currentAssistantMessageRef.current) {
      currentAssistantMessageRef.current = {
        ...currentAssistantMessageRef.current,
        ...patch,
        role: "assistant",
        ...(patch.isComplete ? { progress: undefined } : {}),
      };
    }

    applyDeepResearchLive(conversationId, patch, messageId);
  };

  async function handleSend() {
    if (text.trim() === "" || isSending || deepResearchBlocksCurrentChat) return;

    const uploadPathForRequest = chatUploadLocalPath;
    const uploadDisplayPath = chatUploadDisplayPath;
    
    abortInFlightRequest(null);
    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    abortReasonRef.current = null;

    setIsSending(true);
    // Bare filename persisted in history (never an absolute/local path). Prefer
    // the real picked filename; fall back to the server temp filename.
    const attachmentName = uploadDisplayPath
      ? fileBasename(uploadDisplayPath)
      : uploadPathForRequest
        ? fileBasename(uploadPathForRequest)
        : undefined;
    const userMessage: Message = {
      id: generateMessageId(),
      role: "user",
      content: text,
      ...(uploadPathForRequest ? { attachmentPath: uploadPathForRequest } : {}),
      ...(uploadDisplayPath ? { attachmentDisplayPath: uploadDisplayPath } : {}),
      ...(attachmentName ? { attachmentName } : {}),
    };
    onSend(userMessage);

    const userInput = text;
    const currentAction = selectedAction;
    const useWebSearch = webSearchModeRef.current;
    setText("");

    onLoadingChange(
      true,
      useWebSearch ? "Web Search" : currentAction || (uploadPathForRequest ? "Analyzing" : null),
    );
    
    const isDeepResearch = currentAction === "Deep Research";
    
    currentConversationIdRef.current = selectedConversationId;
    
    try {
      if (!currentConversationIdRef.current) {
        try {
          const allMessages = [...messages, userMessage];
          const conversationId = await createConversation(allMessages);
          currentConversationIdRef.current = conversationId;
          setSelectedConversationId(conversationId);
          isNewConversationRef.current = true;
          onConversationCreated?.();
        } catch (error) {
          logger.error("Failed to create conversation:", error);
          setReminderMessage("Could not save conversation. Your chat will continue but may not be persisted.");
          setTimeout(() => setReminderMessage(null), 5000);
        }
      } else {
        isNewConversationRef.current = false;
        try {
          await addMessageToConversation(currentConversationIdRef.current, userMessage);
        } catch (error) {
          logger.error("Failed to add user message to conversation:", error);
          setReminderMessage("Could not save message to conversation history.");
          setTimeout(() => setReminderMessage(null), 5000);
        }
      }

      const messageHistory = [
        ...messages.map(m => ({
          role: m.role,
          content: m.content,
          ...(m.attachmentPath ? { attachmentPath: m.attachmentPath } : {}),
        })),
        {
          role: "user",
          content: userInput,
          ...(uploadPathForRequest ? { attachmentPath: uploadPathForRequest } : {}),
        },
      ];
      
      if (isDeepResearch) {
        const assistantMessageId = generateMessageId();
        const assistantMessage: Message = { 
          id: assistantMessageId,
          role: "assistant", 
          content: "",
          isComplete: false,
          isDeepResearch: true,
          progress: ""
        };
        currentAssistantMessageRef.current = { ...assistantMessage };
        onSend(assistantMessage);
        
        const deepResearchConversationId = currentConversationIdRef.current;
        setDeepResearchActive(deepResearchConversationId);
        deepResearchInFlightRef.current = true;
        if (deepResearchConversationId) {
          applyDeepResearchLive(
            deepResearchConversationId,
            { progress: "", content: "", isComplete: false },
            assistantMessageId,
          );
        }
        
        try {
          await sendDeepResearchMessage(
            messageHistory,
            (progress: string) => {
              patchDeepResearchAssistant(
                deepResearchConversationId,
                assistantMessageId,
                { progress },
              );
            },
            (clarificationQuestion: string) => {
              patchDeepResearchAssistant(
                deepResearchConversationId,
                assistantMessageId,
                { content: clarificationQuestion, isComplete: true },
              );
              if (currentAssistantMessageRef.current) {
                void saveAssistantMessageToDatabase(currentAssistantMessageRef.current);
              }
              if (deepResearchConversationId) {
                applyDeepResearchLive(deepResearchConversationId, null);
              }
              setDeepResearchInactive(deepResearchConversationId);
            },
            (finalReport: string) => {
              patchDeepResearchAssistant(
                deepResearchConversationId,
                assistantMessageId,
                { content: finalReport, isComplete: true },
              );
              if (currentAssistantMessageRef.current) {
                void saveAssistantMessageToDatabase(currentAssistantMessageRef.current);
              }
              if (deepResearchConversationId) {
                applyDeepResearchLive(deepResearchConversationId, null);
              }
              setDeepResearchInactive(deepResearchConversationId);
            },
            (error: string) => {
              const errorContent = `Error: ${error}`;
              patchDeepResearchAssistant(
                deepResearchConversationId,
                assistantMessageId,
                { content: errorContent, isComplete: true },
              );
              if (currentAssistantMessageRef.current) {
                void saveAssistantMessageToDatabase(currentAssistantMessageRef.current);
              }
              if (deepResearchConversationId) {
                applyDeepResearchLive(deepResearchConversationId, null);
              }
              setDeepResearchInactive(deepResearchConversationId);
            },
            () => {
              if (
                currentAssistantMessageRef.current &&
                !currentAssistantMessageRef.current.isComplete &&
                currentAssistantMessageRef.current.content.trim()
              ) {
                void saveAssistantMessageToDatabase(currentAssistantMessageRef.current);
              }
              if (deepResearchConversationId) {
                applyDeepResearchLive(deepResearchConversationId, null);
              }
              setDeepResearchInactive(deepResearchConversationId);
            },
            uploadPathForRequest,
            abortController.signal,
          );
        } catch (deepResearchError) {
          if (abortReasonRef.current === "navigation") {
            return;
          }
          const errorContent = `Error: Failed to get response from server${deepResearchError instanceof Error ? `: ${deepResearchError.message}` : ''}`;
          patchDeepResearchAssistant(
            deepResearchConversationId,
            assistantMessageId,
            { content: errorContent, isComplete: true },
          );
          if (currentAssistantMessageRef.current) {
            void saveAssistantMessageToDatabase(currentAssistantMessageRef.current);
          }
          if (deepResearchConversationId) {
            applyDeepResearchLive(deepResearchConversationId, null);
          }
          setDeepResearchInactive(deepResearchConversationId);
          throw deepResearchError;
        } finally {
          deepResearchInFlightRef.current = false;
        }
      } else {
        const search = useWebSearch;
        
        const assistantMessage: Message = { 
          id: generateMessageId(),
          role: "assistant", 
          content: "",
          isComplete: false
        };
        currentAssistantMessageRef.current = { ...assistantMessage };
        onSend(assistantMessage);
        
        let accumulatedContent = "";
        await sendStreamingMessage(
          messageHistory,
          search,
          (chunk: string) => {
            accumulatedContent += chunk;
            if (currentAssistantMessageRef.current) {
              currentAssistantMessageRef.current.content = accumulatedContent;
            }
            updateLastMessage((msg) => ({
              ...msg,
              content: accumulatedContent,
            }));
          },
          // Attachments now travel per-message inside `messageHistory`, so the
          // request-level path is omitted to avoid attaching the file twice.
          undefined,
          { signal: abortController.signal },
        );
        
        if (currentAssistantMessageRef.current) {
          currentAssistantMessageRef.current.isComplete = true;
          saveAssistantMessageToDatabase(currentAssistantMessageRef.current);
        }
        updateLastMessage((msg) => ({
          ...msg,
          isComplete: true
        }));
      }
    } catch (error) {
      if (abortReasonRef.current === "navigation") {
        return;
      }

      const isTimeout =
        error instanceof Error && error.name === "StreamTimeoutError";
      const errorContent = isTimeout
        ? "Error: The request timed out. Try again or start a new chat."
        : `Error: Failed to get response from server${error instanceof Error ? `: ${error.message}` : ""}`;

      const lastMessage = messages[messages.length - 1];
      if (lastMessage && lastMessage.isDeepResearch && !lastMessage.isComplete) {
        const conversationId = currentConversationIdRef.current;
        patchDeepResearchAssistant(
          conversationId,
          lastMessage.id,
          { content: errorContent, isComplete: true },
        );
        if (currentAssistantMessageRef.current) {
          void saveAssistantMessageToDatabase(currentAssistantMessageRef.current);
        }
        if (conversationId) {
          applyDeepResearchLive(conversationId, null);
        }
        setDeepResearchInactive(conversationId);
      } else if (currentAssistantMessageRef.current) {
        currentAssistantMessageRef.current.content = errorContent;
        currentAssistantMessageRef.current.isComplete = true;
        saveAssistantMessageToDatabase(currentAssistantMessageRef.current);
        updateLastMessage((msg) => ({
          ...msg,
          content: errorContent,
          isComplete: true,
        }));
      } else {
        const errorMessage: Message = {
          id: generateMessageId(),
          role: "assistant",
          content: errorContent,
          isComplete: true,
        };
        onSend(errorMessage);
        await saveAssistantMessageToDatabase(errorMessage);
      }
    } finally {
      abortControllerRef.current = null;
      abortReasonRef.current = null;
      onLoadingChange(false, null);
      setIsSending(false);
    }
  }

  return (
    <div
      style={{
        padding: "0rem 1.5rem",
        background: "#fcfaf9",
        display: "flex",
        flexDirection: "column",
        gap: "0.75rem",
      }}
    >
      <input
        ref={chatAttachmentInputRef}
        type="file"
        style={{ display: "none" }}
        accept={CHAT_ATTACHMENT_ACCEPT}
        onChange={async (e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (!file) {
            setShowUploadMenu(false);
            return;
          }
          try {
            const path = await uploadChatAttachmentFromBrowser(file);
            applyChatAttachmentFromPath(path, file.name);
          } catch {
            // ignore upload failures
          }
          setShowUploadMenu(false);
        }}
      />
      {deepResearchBlocksCurrentChat && (
        <div
          style={{
            padding: "0.6rem 0.85rem",
            background: "#fef3c7",
            border: "1px solid #fbbf24",
            borderRadius: "8px",
            fontSize: "0.84rem",
            color: "#92400e",
            lineHeight: 1.45,
          }}
        >
          Deep research is currently running in another conversation. Due to memory constraints, it is not possible to send messages in other conversations until it completes.
        </div>
      )}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.5rem"
        }}
      >
        {ACTIONS.map((action) => {
          const isSelected = selectedAction === action;
          return (
            <button
              key={action}
              type="button"
              className={`action-mode-button${isSelected ? " action-mode-button--selected" : ""}`}
              onClick={() => {
                const next = isSelected ? null : action;
                setSelectedAction(next);
                if (action === "Web Search") {
                  webSearchModeRef.current = next === "Web Search";
                } else if (next === "Deep Research") {
                  webSearchModeRef.current = false;
                }
              }}
              style={{
                borderRadius: "8px",
                border: isSelected ? "1px solid #111" : "1px solid #d2d6db",
                background: isSelected ? "#111" : "#fff",
                color: isSelected ? "#fff" : "#111",
                padding: "0.4rem 0.9rem",
                fontSize: "0.85rem",
                cursor: "pointer",
                transition: "all 0.2s ease"
              }}
            >
              {action}
            </button>
          );
        })}
      </div>

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: "0.5rem",
          position: "relative"
        }}
      >
        <div
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            gap: "0.4rem",
          }}
        >
          <div style={{ flex: 1, minWidth: 0, position: "relative" }}>
            <div style={{ position: "relative" }}>
            {showUploadMenu && (
              <div
                ref={uploadMenuRef}
                style={{
                  position: "absolute",
                  bottom: "100%",
                  left: 0,
                  marginBottom: "0.5rem",
                  background: "#fff",
                  border: "1px solid #d2d6db",
                  borderRadius: "8px",
                  boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)",
                  zIndex: 1000,
                  minWidth: "150px",
                  padding: "0.5rem 0"
                }}
              >
                <button
                  type="button"
                  disabled={uploadDisabled}
                  onClick={async () => {
                    if (uploadDisabled) return;
                    if (isDesktopApp()) {
                      setShowUploadMenu(false);
                      try {
                        const result = await pickChatAttachmentDesktop();
                        if (result) {
                          applyChatAttachmentFromPath(result.serverPath, fileBasename(result.displayPath), result.displayPath);
                        }
                        return;
                      } catch {
                        // Desktop picker unavailable — fall through to browser input
                      }
                    }
                    const input = chatAttachmentInputRef.current;
                    if (input) input.value = "";
                    input?.click();
                  }}
                  title={
                    uploadDisabled
                      ? isDeepResearchSelected
                        ? "Upload photos & files is not available with Deep Research"
                        : "Upload photos & files is unavailable while deep research is in progress"
                      : undefined
                  }
                  style={{
                    width: "100%",
                    padding: "0.5rem 1rem",
                    textAlign: "left",
                    border: "none",
                    background: "transparent",
                    color: uploadDisabled ? "#9ca3af" : "#111",
                    cursor: uploadDisabled ? "not-allowed" : "pointer",
                    fontSize: "0.9rem",
                    transition: "background-color 0.2s",
                    display: "flex",
                    alignItems: "center",
                    gap: "0.5rem",
                    opacity: uploadDisabled ? 0.65 : 1,
                  }}
                  onMouseEnter={(e) => {
                    if (uploadDisabled) return;
                    e.currentTarget.style.backgroundColor = "#fcfaf9";
                  }}
                  onMouseLeave={(e) => {
                    if (uploadDisabled) return;
                    e.currentTarget.style.backgroundColor = "transparent";
                  }}
                >
                  <PaperclipIcon width={18} height={18} color="currentColor" />
                  <span>Upload photos & files</span>
                </button>
              </div>
            )}
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                borderRadius: "8px",
                border: "1px solid #d2d6db",
                background: "#fff",
                overflow: "hidden",
              }}
            >
              <div style={{ position: "relative", display: "flex", alignItems: "flex-start" }}>
                <button
                  ref={plusButtonRef}
                  type="button"
                  onClick={() => setShowUploadMenu(!showUploadMenu)}
                  aria-label="Attach file"
                  style={{
                    position: "absolute",
                    left: "0.75rem",
                    top: "0.85rem",
                    height: "1.5rem",
                    width: "1.5rem",
                    borderRadius: "4px",
                    border: "1px solid #d2d6db",
                    background: "#fff",
                    color: "#111",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: "0",
                    transition: "all 0.2s ease",
                    zIndex: 1
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = "#fcfaf9";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = "#fff";
                  }}
                >
                  <PlusIcon 
                    width="14" 
                    height="14" 
                    color="currentColor"
                  />
                </button>
                <textarea
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      handleSend();
                    }
                  }}
                  disabled={deepResearchBlocksCurrentChat}
                  placeholder={
                    deepResearchBlocksCurrentChat
                      ? "Unavailable while deep research is running..."
                      : selectedAction
                        ? `Ask with "${selectedAction}"...`
                        : "Ask anything..."
                  }
                  style={{
                    flex: 1,
                    padding: "0.85rem 1rem 0.85rem 3rem",
                    border: "none",
                    outline: "none",
                    fontSize: "1rem",
                    background: "transparent",
                    resize: "vertical",
                    minHeight: "2.5rem",
                    fontFamily: "inherit",
                    ...(deepResearchBlocksCurrentChat ? { opacity: 0.5, cursor: "not-allowed" } : {}),
                  }}
                />
              </div>
              {chatUploadLocalPath && (
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "flex-start",
                    gap: "0.15rem",
                    padding: "0.25rem 0.75rem 0.5rem 0.75rem",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <span style={{ color: "#3b82f6", fontSize: "0.9rem", fontWeight: 500 }}>
                    {chatUploadFileName || "Attached file"}
                  </span>
                  <button
                    type="button"
                    aria-label="Remove attachment"
                    onClick={(e) => {
                      e.stopPropagation();
                      releaseChatAttachment(chatUploadLocalPath);
                      setChatUploadLocalPath(null);
                      setChatUploadDisplayPath(null);
                      setChatUploadFileName(null);
                    }}
                    style={{
                      background: "transparent",
                      border: "none",
                      color: "#3b82f6",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      padding: "0.25rem"
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.opacity = "0.7";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.opacity = "1";
                    }}
                  >
                    <XIcon width="14" height="14" color="currentColor" />
                  </button>
                  </div>
                  {chatUploadDisplayPath && looksLikeFullFilesystemPath(chatUploadDisplayPath) && (
                    <span
                      style={{
                        color: "#6b7280",
                        fontSize: "0.75rem",
                        fontFamily: "ui-monospace, monospace",
                        maxWidth: "100%",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                      title={chatUploadDisplayPath}
                    >
                      {chatUploadDisplayPath}
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
        <button
          type="button"
          onClick={handleSend}
          aria-label="Send message"
          disabled={isSending || deepResearchBlocksCurrentChat}
          style={{
            height: "2rem",
            width: "2rem",
            borderRadius: "50%",
            border: "none",
            background: (!isSending && !deepResearchBlocksCurrentChat) ? "#fcfaf9" : "#d2d6db",
            color: "#111",
            fontWeight: 600,
            cursor: (!isSending && !deepResearchBlocksCurrentChat) ? "pointer" : "not-allowed",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "0.35rem",
            flexShrink: 0,
            transition: "background-color 0.2s",
          }}
          onMouseEnter={(e) => {
            if (!isSending && !deepResearchBlocksCurrentChat) {
              e.currentTarget.style.backgroundColor = "#f3f0ec";
            }
          }}
          onMouseLeave={(e) => {
            if (!isSending && !deepResearchBlocksCurrentChat) {
              e.currentTarget.style.backgroundColor = "#fcfaf9";
            }
          }}
        >
          <SendIcon 
            width={18}
            height={18}
            color={(isSending || deepResearchBlocksCurrentChat) ? "#6b7280" : "#111"}
          />
        </button>
        </div>
          {reminderMessage && (
            <div
              style={{
                marginTop: "0.5rem",
                marginLeft: "0.75rem",
                padding: "0.5rem 0.75rem",
                background: "#fef3c7",
                border: "1px solid #fbbf24",
                borderRadius: "6px",
                fontSize: "0.85rem",
                color: "#92400e",
                alignSelf: "flex-start"
              }}
            >
              {reminderMessage}
            </div>
          )}
      </div>
    </div>
  );
}
