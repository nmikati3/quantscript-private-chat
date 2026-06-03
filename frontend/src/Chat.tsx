import { type Message } from "./App";
import ReactMarkdown, { type ExtraProps } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { type HTMLAttributes, useRef, useEffect, useState } from "react";
import { exportMessageToPDF } from "./pdfExport";
import { DownloadIcon, SpinnerIcon, CheckCircleIcon } from "./icons";
import { logger } from "./logger";
import { isDesktopApp } from "./runtimeConfig";

// eslint-disable-next-line no-control-regex
const UNSAFE_CONTROL_CHARS = /[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g;

type MdProps = HTMLAttributes<HTMLElement> & ExtraProps;

function stripNode({ node, ...rest }: MdProps) { void node; return rest; }

const markdownTableComponents = {
  table: (props: MdProps) => (
    <div style={{ overflowX: "auto", margin: "0.5rem 0" }}>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: "0.85rem" }} {...stripNode(props)} />
    </div>
  ),
  thead: (props: MdProps) => <thead style={{ borderBottom: "2px solid #e5e7eb" }} {...stripNode(props)} />,
  th: (props: MdProps) => (
    <th style={{ padding: "0.5rem 0.75rem", textAlign: "left", fontWeight: 600, color: "#374151", whiteSpace: "nowrap" }} {...stripNode(props)} />
  ),
  td: (props: MdProps) => (
    <td style={{ padding: "0.5rem 0.75rem", borderBottom: "1px solid #f3f4f6", color: "#4b5563" }} {...stripNode(props)} />
  ),
  tr: (props: MdProps) => <tr {...stripNode(props)} />,
};

function sanitizeMarkdown(text: string): string {
  return text.replace(UNSAFE_CONTROL_CHARS, "");
}

interface MessageItemProps {
  message: Message;
  messageIndex: number;
  conversationTitle?: string | null;
}

function MessageItem({ message, messageIndex, conversationTitle }: MessageItemProps) {
  const [isExporting, setIsExporting] = useState(false);
  const [showSaved, setShowSaved] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = (msg: string) => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToastMessage(msg);
    toastTimer.current = setTimeout(() => setToastMessage(null), 3000);
  };

  useEffect(() => {
    return () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
      if (savedTimer.current) clearTimeout(savedTimer.current);
    };
  }, []);

  const handleExportPDF = async () => {
    if (message.role === "assistant") {
      setIsExporting(true);
      try {
        await exportMessageToPDF(message, messageIndex, conversationTitle ?? undefined);
        setShowSaved(true);
        savedTimer.current = setTimeout(() => setShowSaved(false), 2000);
        showToast("PDF saved to Downloads");
      } catch (error) {
        logger.error("Error exporting to PDF:", error);
        showToast("Failed to export PDF");
      } finally {
        setIsExporting(false);
      }
    }
  };

  return (
    <div
      style={{
        marginBottom: "1.5rem",
        alignSelf: message.role === "user" ? "flex-end" : "flex-start",
        maxWidth: message.role === "user" ? "70%" : "95%",
        display: "flex",
        flexDirection: "column",
        gap: "0.5rem"
      }}
    >
      {/* PDF Download Button - only for assistant messages that are complete */}
      {message.role === "assistant" && message.isComplete  && (
        <div style={{ display: "flex", justifyContent: "flex-start" }}>
          <button
            onClick={handleExportPDF}
            disabled={isExporting || showSaved}
            aria-label="Download as PDF"
            style={{
              padding: "0.4rem 0.6rem",
              background: showSaved ? "#ecfdf5" : isExporting ? "#d2d6db" : "#fcfaf9",
              color: showSaved ? "#059669" : "#111",
              border: "none",
              borderRadius: "6px",
              cursor: isExporting || showSaved ? "default" : "pointer",
              fontSize: "0.75rem",
              fontWeight: 500,
              display: "flex",
              alignItems: "center",
              gap: "0.4rem",
              transition: "background-color 0.3s, color 0.3s",
            }}
            onMouseEnter={(e) => {
              if (!isExporting && !showSaved) {
                e.currentTarget.style.backgroundColor = "#f3f0ec";
              }
            }}
            onMouseLeave={(e) => {
              if (!isExporting && !showSaved) {
                e.currentTarget.style.backgroundColor = "#fcfaf9";
              }
            }}
            title="Download as PDF"
          >
            {showSaved ? (
              <>
                <CheckCircleIcon width="14" height="14" color="#059669" />
                Saved!
              </>
            ) : (
              <>
                <DownloadIcon width="14" height="14" color={isExporting ? "#6b7280" : "#111"} />
                {isExporting ? "Exporting..." : ""}
              </>
            )}
          </button>
        </div>
      )}
      <div
        style={{
          padding: "0rem 1rem",
          background: message.role === "user" ? "#f3f0ec" : "#fcfaf9",
          borderRadius: message.role === "user" ? "8px" : "0px",
        }}
      >
        {message.role === "user" && (message.attachmentName || message.attachmentDisplayPath || message.attachmentPath) ? (
          <div
            style={{
              fontSize: "0.72rem",
              color: "#4b5563",
              fontFamily: "ui-monospace, monospace",
              marginBottom: "0.35rem",
              wordBreak: "break-all",
            }}
            title={message.attachmentName || message.attachmentDisplayPath || message.attachmentPath}
          >
            Attachment: {message.attachmentName || message.attachmentDisplayPath || message.attachmentPath}
          </div>
        ) : null}

      {message.isDeepResearch && message.progress !== undefined ? (
        // Deep research in progress: show progress with loading bar
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          {/* Progress text in lighter font */}
          <div style={{ 
            color: "#9ca3af", 
            fontSize: "0.9rem",
            lineHeight: "1.5",
            fontStyle: "italic"
          }}>
            {message.progress || "Researching (this may take a moment)..."}
          </div>
          {/* Loading bar */}
          <div className="deep-research-loading-bar">
            <div className="deep-research-loading-bar-fill" />
          </div>
        </div>
      ) : (
        <ReactMarkdown
          remarkPlugins={[remarkGfm, remarkMath]}
          rehypePlugins={[rehypeKatex]}
          components={{
            a: ({ node, ...props }) => {
              void node;
              const href = props.href ?? "";
              const isSafeScheme = /^https?:\/\//i.test(href);
              return (
                <a
                  {...props}
                  href={isSafeScheme ? href : undefined}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => {
                    if (isSafeScheme && isDesktopApp()) {
                      e.preventDefault();
                      import("@tauri-apps/plugin-opener")
                        .then((m) => m.openUrl(href))
                        .catch((err) => logger.error("Failed to open URL:", err));
                    } else if (!isSafeScheme) {
                      e.preventDefault();
                    }
                  }}
                />
              );
            },
            img: ({ node, ...props }) => {
              void node;
              const src = props.src ?? "";
              const isSafeSrc = /^(https?:\/\/|data:image\/)/i.test(src);
              return isSafeSrc ? <img {...props} /> : <img {...props} src={undefined} alt={props.alt ?? "image"} />;
            },
            p: (props: MdProps) => <p style={{ margin: "0.5rem 0" }} {...stripNode(props)} />,
            ul: (props: MdProps) => <ul style={{ margin: "0.25rem 0" }} {...stripNode(props)} />,
            li: (props: MdProps) => <li style={{ margin: "0.15rem 0" }} {...stripNode(props)} />,
            h1: (props: MdProps) => <h1 style={{ margin: "0.4rem 0", fontSize: "1.1rem" }} {...stripNode(props)} />,
            h2: (props: MdProps) => <h2 style={{ margin: "0.3rem 0", fontSize: "1rem" }} {...stripNode(props)} />,
            ...markdownTableComponents,
          }}
        >
          {sanitizeMarkdown(message.content)}
        </ReactMarkdown>
      )}
      </div>
      {toastMessage && (
        <div className="pdf-toast">{toastMessage}</div>
      )}
    </div>
  );
}

interface Props {
  messages: Message[];
  isLoading: boolean;
  loadingAction: string | null;
  isLoadingConversation?: boolean;
  selectedConversationId?: string | null;
  activeDeepResearchConversations?: Set<string>;
  conversationTitle?: string | null;
}

export default function Chat({
  messages,
  isLoading,
  loadingAction,
  isLoadingConversation = false,
  selectedConversationId,
  activeDeepResearchConversations,
  conversationTitle,
}: Props) {
  
  const getLoadingMessage = () => {
    if (loadingAction === "Web Search") {
      return "Searching the Web";
    }
    if (loadingAction === "Analyzing") {
      return "Analyzing";
    }
    return "Generating";
  };

  const hasInProgressDeepResearchMessage = messages.some(
    (m) => m.isDeepResearch && m.progress !== undefined && !m.isComplete,
  );

  const containerRef = useRef<HTMLDivElement>(null);
  const shouldAutoScrollRef = useRef(true);

  const SCROLL_BOTTOM_THRESHOLD_PX = 80;

  const syncAutoScrollPreference = () => {
    const el = containerRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    shouldAutoScrollRef.current = distanceFromBottom <= SCROLL_BOTTOM_THRESHOLD_PX;
  };

  // Pin to bottom when switching conversations; user can scroll away during streaming.
  useEffect(() => {
    shouldAutoScrollRef.current = true;
  }, [selectedConversationId]);

  useEffect(() => {
    if (!shouldAutoScrollRef.current || !containerRef.current) return;
    containerRef.current.scrollTop = containerRef.current.scrollHeight;
  }, [messages, isLoading]);

  useEffect(() => {
    if (!isLoadingConversation && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
      shouldAutoScrollRef.current = true;
    }
  }, [isLoadingConversation]);
    
  return (
    <div 
      ref={containerRef}
      role="log"
      aria-live="polite"
      aria-label="Chat messages"
      onScroll={syncAutoScrollPreference}
      style={{ padding: "1rem", overflowY: "auto", flex: 1, display: "flex", flexDirection: "column" }}
    >
      {isLoadingConversation ? (
        <div
          style={{
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            height: "100%",
            flexDirection: "column",
            gap: "1rem"
          }}
        >
          <div className="loading-spinner" />
          <div style={{ color: "#6b7280", fontSize: "0.95rem" }}>Loading conversation...</div>
        </div>
      ) : messages.length === 0 && !isLoading ? (
        <div
          style={{
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            height: "100%",
            color: "#21354",
            fontSize: "1.5rem",
            padding: "2rem",
            textAlign: "center"
          }}
        >
          How can I help you today?
        </div>
      ) : null}
      {messages.map((message, i) => (
        <MessageItem key={message.id} message={message} messageIndex={i} conversationTitle={conversationTitle} />
      ))}
      {isLoading && loadingAction !== "Deep Research" && (
        <div
          style={{
            marginBottom: "1.5rem",
            padding: "1rem",
            background: "#fcfaf9",
            borderRadius: "0px",
            alignSelf: "flex-start",
            maxWidth: "80%"
          }}
        >
          <div style={{ 
            color: "#6b7280",
            fontSize: "0.95rem",
            display: "flex",
            alignItems: "center",
            gap: "0.25rem"
          }}>
            <span>{getLoadingMessage()}</span>
            <span className="loading-dots">
              <span>.</span>
              <span>.</span>
              <span>.</span>
            </span>
          </div>
        </div>
      )}
      {selectedConversationId && activeDeepResearchConversations && activeDeepResearchConversations.has(selectedConversationId) && !hasInProgressDeepResearchMessage && (
        <div
          style={{
            marginBottom: "1.5rem",
            padding: "1rem",
            background: "#fcfaf9",
            borderRadius: "0px",
            alignSelf: "flex-start",
            maxWidth: "80%",
            display: "flex",
            flexDirection: "column",
            gap: "0.75rem"
          }}
        >
          <div style={{ 
            color: "#9ca3af",
            fontSize: "0.9rem",
            lineHeight: "1.5",
            fontStyle: "italic",
            display: "flex",
            alignItems: "center",
            gap: "0.5rem"
          }}>
            <SpinnerIcon width="16" height="16" color="#3b82f6" />
            <span>Researching (this may take a moment)...</span>
          </div>
        </div>
      )}
    </div>
  );
}
