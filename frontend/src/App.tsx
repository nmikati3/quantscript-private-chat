import { useState, useEffect, useRef, useCallback } from "react";
import { flushSync } from "react-dom";
import Chat from "./Chat";
import MessageInput from "./MessageInput";
import { SidebarSection } from "./SidebarSection";
import {
  getConversationMessages,
  fetchStartupStatus,
  type StartupStatusPayload,
} from "./api";
import InitializingScreen from "./InitializingScreen";
import { PencilIcon, ChevronLeftIcon, ChevronRightIcon } from "./icons";
import { logger } from "./logger";
import { generateMessageId } from "./messageId";
import {
  isDesktopApp,
  restartDesktopSidecar,
  safeExitDesktopApp,
} from "./runtimeConfig";
import type { DeepResearchLivePatch, DeepResearchLiveState } from "./deepResearchLive";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** Server-side temp path for the uploaded attachment (sent in API requests) */
  attachmentPath?: string;
  /** Real filesystem path on the user's machine (for display only) */
  attachmentDisplayPath?: string;
  /** Bare attachment filename persisted in history (no directory/path). */
  attachmentName?: string;
  isComplete?: boolean;
  progress?: string;
  isDeepResearch?: boolean;
}

function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loadingAction, setLoadingAction] = useState<string | null>(null);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [sidebarRefreshTrigger, setSidebarRefreshTrigger] = useState(0);
  const [isLoadingConversation, setIsLoadingConversation] = useState(false);
  const [isChatsExpanded, setIsChatsExpanded] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [activeDeepResearchConversations, setActiveDeepResearchConversations] = useState<Set<string>>(new Set());
  const [conversationTitle, setConversationTitle] = useState<string | null>(null);
  const [appInitializing, setAppInitializing] = useState(true);
  const [startupSnapshot, setStartupSnapshot] = useState<StartupStatusPayload | null>(null);
  const [waitingForServer, setWaitingForServer] = useState(true);
  const [startupErrorMessage, setStartupErrorMessage] = useState<string | null>(null);
  const [startupRetryToken, setStartupRetryToken] = useState(0);
  /** Lift Chats above main content while ⋮ menu or inline rename is open. */
  const [isChatsListElevated, setIsChatsListElevated] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const showToast = (msg: string, durationMs = 4000) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), durationMs);
  };

  const previousMessagesRef = useRef<Message[]>([]);
  const selectedConversationIdRef = useRef<string | null>(null);
  const deepResearchLiveRef = useRef<Map<string, DeepResearchLiveState>>(new Map());

  useEffect(() => {
    selectedConversationIdRef.current = selectedConversationId;
  }, [selectedConversationId]);

  const applyDeepResearchLive = useCallback((
    conversationId: string,
    patch: DeepResearchLivePatch | null,
    messageId?: string,
  ) => {
    if (patch === null) {
      deepResearchLiveRef.current.delete(conversationId);
      return;
    }

    const prev = deepResearchLiveRef.current.get(conversationId);
    const next: DeepResearchLiveState = {
      messageId: messageId ?? prev?.messageId ?? generateMessageId(),
      progress: patch.progress ?? prev?.progress ?? "",
      content: patch.content ?? prev?.content ?? "",
      isComplete: patch.isComplete ?? prev?.isComplete ?? false,
    };
    deepResearchLiveRef.current.set(conversationId, next);

    if (selectedConversationIdRef.current !== conversationId) {
      return;
    }

    setMessages((msgs) => {
      const idx = msgs.findIndex((m) => m.id === next.messageId);
      const assistantMessage: Message = {
        id: next.messageId,
        role: "assistant",
        content: next.content,
        isDeepResearch: true,
        isComplete: next.isComplete,
        ...(next.isComplete ? {} : { progress: next.progress }),
      };

      if (idx >= 0) {
        const updated = [...msgs];
        updated[idx] = assistantMessage;
        return updated;
      }

      return [...msgs, assistantMessage];
    });
  }, []);

  // Poll backend until models are ready
  useEffect(() => {
    let cancelled = false;
    let consecutiveConnectionFailures = 0;

    const poll = async () => {
      while (!cancelled) {
        try {
          const s = await fetchStartupStatus();
          if (cancelled) return;
          consecutiveConnectionFailures = 0;
          setStartupSnapshot(s);
          setWaitingForServer(false);
          setStartupErrorMessage(s.error ?? null);
          if (s.ready) {
            setAppInitializing(false);
            return;
          }
          if (s.error) {
            return;
          }
        } catch {
          if (cancelled) return;
          consecutiveConnectionFailures += 1;
          setWaitingForServer(true);
          if (consecutiveConnectionFailures >= 12) {
            setStartupErrorMessage(`Backend is unreachable.`);
          }
        }
        await new Promise((r) => setTimeout(r, 450));
      }
    };

    poll();

    return () => {
      cancelled = true;
    };
  }, [startupRetryToken]);

  const handleRetryStartup = async () => {
    setStartupErrorMessage(null);
    setWaitingForServer(true);
    setStartupSnapshot(null);
    setAppInitializing(true);
    if (isDesktopApp()) {
      try {
        await restartDesktopSidecar();
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        setStartupErrorMessage(`Failed to restart backend sidecar: ${message}`);
        return;
      }
    }
    setStartupRetryToken((value) => value + 1);
  };

  const handleExitStartup = async () => {
    if (isDesktopApp()) {
      await safeExitDesktopApp();
      return;
    }
    window.close();
  };

  // Watch for assistant messages being completed and refresh sidebar
  useEffect(() => {
    // Skip on initial mount (when previousMessagesRef is empty)
    if (previousMessagesRef.current.length === 0) {
      previousMessagesRef.current = messages;
      return;
    }
    
    // Check if any assistant message has just been marked as complete
    const previousMessages = previousMessagesRef.current;
    
    // Find the last assistant message in current messages
    const lastAssistantMessage = [...messages].reverse().find(msg => msg.role === "assistant");
    const previousLastAssistantMessage = [...previousMessages].reverse().find(msg => msg.role === "assistant");
    
    // If we have a new assistant message that is complete, refresh sidebar
    // This handles both cases:
    // 1. New complete message added (non-streaming)
    // 2. Existing message transitioned from incomplete to complete (streaming)
    if (lastAssistantMessage && lastAssistantMessage.isComplete) {
      const wasCompleteBefore = previousLastAssistantMessage?.isComplete ?? false;
      const isCompleteNow = lastAssistantMessage.isComplete;
      
      // Refresh if this is a new message or if it just became complete
      if (!previousLastAssistantMessage || (!wasCompleteBefore && isCompleteNow)) {
        // Trigger sidebar refresh
        setSidebarRefreshTrigger(prev => prev + 1);
      }
    }
    
    // Update ref for next comparison
    previousMessagesRef.current = messages;
  }, [messages]);

  if (appInitializing) {
    return (
      <InitializingScreen
        snapshot={startupSnapshot}
        waitingForServer={waitingForServer}
        startupErrorMessage={startupErrorMessage}
        onRetry={handleRetryStartup}
        onExit={isDesktopApp() ? handleExitStartup : undefined}
      />
    );
  }

  const addMessage = (message: Message) => {
    setMessages((prev) => [...prev, message]);
  };

  const updateLastMessage = (updater: (message: Message) => Message) => {
    setMessages((prev) => {
      if (prev.length === 0) return prev;
      const updated = [...prev];
      updated[updated.length - 1] = updater(updated[updated.length - 1]);
      return updated;
    });
  };

  const handleLoadingChange = (
    loading: boolean,
    action: string | null,
  ) => {
    setIsLoading(loading);
    setLoadingAction(action);
  };

  const setDeepResearchActive = (conversationId: string | null) => {
    if (conversationId) {
      setActiveDeepResearchConversations(prev => new Set(prev).add(conversationId));
    }
  };

  const setDeepResearchInactive = (conversationId: string | null) => {
    if (conversationId) {
      setActiveDeepResearchConversations(prev => {
        const newSet = new Set(prev);
        newSet.delete(conversationId);
        return newSet;
      });
    }
  };

  const handleNewChat = () => {
    setSelectedConversationId(null);
    setConversationTitle(null);
    setMessages([]);
    setIsLoading(false);
    setLoadingAction(null);
    setIsChatsExpanded(true);
  };

  const handleConversationSelect = async (conversationId: string, title?: string) => {
    setConversationTitle(title ?? null);
    // Clear messages and reset chat loading immediately (force synchronous render)
    flushSync(() => {
      setMessages([]);
      setSelectedConversationId(conversationId);
      setIsLoadingConversation(true);
      setIsLoading(false);
      setLoadingAction(null);
    });
    
    try {
      const conversationMessages = await getConversationMessages(conversationId);
      // Convert API messages to Message format
      const formattedMessages: Message[] = conversationMessages.map((msg) => ({
        id: generateMessageId(),
        role: msg.role as "user" | "assistant",
        content: msg.content,
        isComplete: true,
        ...(msg.attachmentName ? { attachmentName: msg.attachmentName } : {}),
      }));

      const live = deepResearchLiveRef.current.get(conversationId);
      if (live && activeDeepResearchConversations.has(conversationId) && !live.isComplete) {
        formattedMessages.push({
          id: live.messageId,
          role: "assistant",
          content: live.content,
          progress: live.progress,
          isDeepResearch: true,
          isComplete: false,
        });
      }

      setMessages(formattedMessages);
    } catch (error) {
      logger.error("Failed to load conversation messages:", error);
      const errorMessage = error instanceof Error ? error.message : "Unknown error";
      showToast(`Failed to load conversation: ${errorMessage}`);
    } finally {
      setIsLoadingConversation(false);
    }
  };

  return (
    <div
      style={{
        display: "flex",
        width: "100vw",
        height: "100vh",
        overflow: "hidden",
        background: "#fcfaf9",
      }}
    >
      {/* ---------- Sidebar ---------- */}
      <div
        style={{
          width: isSidebarCollapsed ? "60px" : "250px",
          background: "#fcfaf9",
          color: "#111", 
          padding: isSidebarCollapsed ? "1rem 0.5rem" : "1rem",
          display: "flex",
          flexDirection: "column",
          height: "100vh",
          overflow: "hidden",
          transition: "width 0.2s ease, padding 0.2s ease",
          position: "relative",
          borderRight: "1px solid #e5e7eb",
        }}
      >
        {/* Collapse/Expand Toggle Button - only when expanded */}
        {!isSidebarCollapsed && (
          <button
            onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
            style={{
              position: "absolute",
              top: "1rem",
              right: "0.5rem",
              border: "none",
              padding: "0.5rem",
              borderRadius: "6px",
              background: "#fcfaf9",
              color: "#111",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              zIndex: 10,
              transition: "background 0.2s ease",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "#f3f0ec";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "#fcfaf9";
            }}
            title="Collapse sidebar"
            aria-label="Collapse sidebar"
          >
            <ChevronLeftIcon color="#111" />
          </button>
        )}

        {/* Top section - app title, New Chat */}
        <div style={{ flexShrink: 0 }}>
          {!isSidebarCollapsed && (
            <>
              <h1
                style={{
                  margin: 0,
                  marginTop: "0.25rem",
                  paddingRight: "2.25rem",
                  fontSize: "1.2rem",
                  fontWeight: 700,
                  color: "#111",
                  letterSpacing: "-0.02em",
                  lineHeight: 1.25,
                }}
              >
                QuantScript
              </h1>
              <p
                style={{
                  margin: 0,
                  marginTop: "0.45rem",
                  paddingRight: "2.25rem",
                  fontSize: "0.74rem",
                  fontWeight: 400,
                  color: "#6b7280",
                  lineHeight: 1.45,
                }}
              >
                Private, free, almost sustainable.
              </p>
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "0.5rem",
                  marginTop: "1.85rem",
                }}
              >
                <button
                  type="button"
                  className="sidebar-nav-button"
                  onClick={handleNewChat}
                  style={{
                    border: "none",
                    padding: "0.5rem 0.75rem",
                    borderRadius: "8px",
                    background: "#fcfaf9",
                    color: "#111",
                    cursor: "pointer",
                    textAlign: "left",
                    fontSize: "0.9rem",
                    display: "flex",
                    alignItems: "center",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = "#f3f0ec";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "#fcfaf9";
                  }}
                >
                  <PencilIcon color="#111" style={{ marginRight: "0.5rem" }} />
                  New Chat
                </button>
              </div>
            </>
          )}

          {/* Icon-only buttons when collapsed */}
          {isSidebarCollapsed && (
            <>
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "0.5rem",
                  marginTop: "0.5rem",
                  alignItems: "center",
                }}
              >
                <div
                  title="QuantScript — Private, free, almost sustainable."
                  style={{
                    fontSize: "0.62rem",
                    fontWeight: 700,
                    color: "#111",
                    textAlign: "center",
                    lineHeight: 1.15,
                    letterSpacing: "-0.02em",
                    maxWidth: "100%",
                    padding: "0 2px",
                  }}
                >
                  QuantScript
                </div>
                <button
                  onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
                  style={{
                    border: "none",
                    padding: "0.5rem",
                    borderRadius: "8px",
                    background: "#fcfaf9",
                    color: "#111",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    transition: "background 0.2s ease",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = "#f3f0ec";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "#fcfaf9";
                  }}
                  title="Expand sidebar"
                  aria-label="Expand sidebar"
                >
                  <ChevronRightIcon color="#111" />
                </button>
                <button
                  type="button"
                  className="sidebar-nav-button"
                  onClick={handleNewChat}
                  style={{
                    border: "none",
                    padding: "0.5rem",
                    borderRadius: "8px",
                    background: "#fcfaf9",
                    color: "#111",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = "#f3f0ec";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "#fcfaf9";
                  }}
                  title="New Chat"
                  aria-label="New Chat"
                >
                  <PencilIcon color="#111" />
                </button>
              </div>
            </>
          )}
        </div>

        {/* Scrollable middle section - Chats */}
        <div
          style={{
            flex: 1,
            overflowY: "auto",
            overflowX: "hidden",
            display: "flex",
            flexDirection: "column",
            gap: "1rem",
            minHeight: 0,
            marginTop: "1rem",
          }}
        >
          {!isSidebarCollapsed ? (
            <div
              style={{
                flexShrink: 0,
                alignSelf: "stretch",
                minHeight: "max-content",
                position: "relative",
                zIndex: isChatsListElevated ? 20 : 1,
                ...(isChatsListElevated ? { transform: "translateZ(0)" } : {}),
              }}
            >
              <SidebarSection
                title="Chats"
                items={[]}
                onConversationSelect={handleConversationSelect}
                selectedConversationId={selectedConversationId}
                refreshTrigger={sidebarRefreshTrigger}
                isExpanded={isChatsExpanded}
                onExpandedChange={setIsChatsExpanded}
                activeDeepResearchConversations={activeDeepResearchConversations}
                onChatListOverlayChange={setIsChatsListElevated}
              />
            </div>
          ) : (
            <SidebarSection
              title=""
              items={[]}
              onConversationSelect={handleConversationSelect}
              selectedConversationId={selectedConversationId}
              refreshTrigger={sidebarRefreshTrigger}
              isExpanded={false}
              onExpandedChange={setIsChatsExpanded}
              isCollapsed={true}
              activeDeepResearchConversations={activeDeepResearchConversations}
            />
          )}
        </div>

      </div>

      {/* ---------- Main Content Area ---------- */}

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          width: "60%",
          minWidth: "320px",
          height: "92vh",
          borderRadius: "8px",
          overflow: "hidden",
          background: "#fcfaf9",
          margin: "auto",
        }}
      >
        <Chat 
          messages={messages} 
          isLoading={isLoading} 
          loadingAction={loadingAction}
          isLoadingConversation={isLoadingConversation}
          selectedConversationId={selectedConversationId}
          activeDeepResearchConversations={activeDeepResearchConversations}
          conversationTitle={conversationTitle}
        />
        <MessageInput 
          onSend={addMessage} 
          updateLastMessage={updateLastMessage} 
          messages={messages} 
          onLoadingChange={handleLoadingChange}
          selectedConversationId={selectedConversationId}
          activeDeepResearchConversations={activeDeepResearchConversations}
          setSelectedConversationId={setSelectedConversationId}
          setDeepResearchActive={setDeepResearchActive}
          setDeepResearchInactive={setDeepResearchInactive}
          applyDeepResearchLive={applyDeepResearchLive}
          deepResearchAvailable={startupSnapshot?.deepResearchAvailable ?? true}
          onConversationCreated={() => setSidebarRefreshTrigger(prev => prev + 1)}
        />
      </div>

      {toastMessage && (
        <div className="pdf-toast" role="alert">{toastMessage}</div>
      )}
    </div>
  );
}


export default App;
