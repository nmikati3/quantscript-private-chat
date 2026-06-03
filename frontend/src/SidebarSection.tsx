import { useState, useEffect, useLayoutEffect, useRef, useId, useCallback } from "react";
import { createPortal } from "react-dom";
import { getConversations, updateConversationTitle, deleteConversation, type Conversation } from "./api";
import { PencilIcon, ThreeDotsIcon, DeleteIcon, ChevronRightIcon, ChevronDownIcon, SpinnerIcon } from "./icons";
import { logger } from "./logger";

const sidebarButton = {
  border: "none",
  padding: "0.5rem 0.75rem",
  borderRadius: "8px",
  background: "#fcfaf9",
  color: "#111",
  cursor: "pointer",
  textAlign: "left" as const,
  fontSize: "0.9rem",
};

const sidebarItemButton = {
  ...sidebarButton,
  background: "#fcfaf9",
  fontWeight: 400,
};

const isChatSection = (title: string) => title === "Chats" || title === "";

export function SidebarSection({
  title,
  items,
  itemsWithIds,
  onConversationSelect,
  selectedConversationId,
  refreshTrigger,
  isExpanded: externalIsExpanded,
  onExpandedChange,
  isCollapsed,
  activeDeepResearchConversations,
  onChatListOverlayChange,
}: {
  title: string;
  items: string[];
  itemsWithIds?: Array<{ id: string; title: string }>;
  onConversationSelect?: (conversationId: string, conversationTitle?: string) => void;
  selectedConversationId?: string | null;
  refreshTrigger?: number;
  isExpanded?: boolean;
  onExpandedChange?: (expanded: boolean) => void;
  isCollapsed?: boolean;
  activeDeepResearchConversations?: Set<string>;
  /** When the ⋮ menu or inline rename is active, parent can raise z-index above main content. */
  onChatListOverlayChange?: (elevated: boolean) => void;
}) {
  const [internalIsExpanded, setInternalIsExpanded] = useState(false);
  const isExpanded = externalIsExpanded !== undefined ? externalIsExpanded : internalIsExpanded;

  const setIsExpanded = (expanded: boolean) => {
    if (onExpandedChange) {
      onExpandedChange(expanded);
    } else {
      setInternalIsExpanded(expanded);
    }
  };
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [isLoadingConversations, setIsLoadingConversations] = useState(() => isChatSection(title));
  const [conversationsError, setConversationsError] = useState<string | null>(null);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [editingConversationId, setEditingConversationId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState<string>("");
  const [deleteConfirmation, setDeleteConfirmation] = useState<{ conversation: Conversation | null }>({
    conversation: null,
  });
  const menuRefs = useRef<{ [key: string]: HTMLDivElement | null }>({});
  const sidebarSectionRef = useRef<HTMLDivElement | null>(null);
  const buttonRefs = useRef<{ [key: string]: HTMLButtonElement | null }>({});
  const inputRef = useRef<HTMLInputElement | null>(null);
  const deleteModalCancelRef = useRef<HTMLButtonElement | null>(null);
  const deleteDialogTitleId = useId();
  const isCancellingRef = useRef(false);

  const fetchConversations = useCallback(() => {
    if (!isChatSection(title)) return;

    logger.log("Calling get_all_conversations to refresh sidebar");
    getConversations()
      .then((convs) => {
        logger.log("Received conversations:", convs.length);
        setConversations(convs);
        setConversationsError(null);
        setIsLoadingConversations(false);
      })
      .catch((error) => {
        logger.error("Failed to fetch conversations:", error);
        setConversationsError(error.message || "Failed to load conversations");
        setIsLoadingConversations(false);
      });
  }, [title]);

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  useEffect(() => {
    if (refreshTrigger !== undefined && refreshTrigger > 0) {
      fetchConversations();
    }
  }, [refreshTrigger, fetchConversations]);

  useEffect(() => {
    if (!isChatSection(title) || !onChatListOverlayChange) return;
    const elevated = openMenuId !== null || editingConversationId !== null;
    onChatListOverlayChange(elevated);
    return () => onChatListOverlayChange(false);
  }, [title, openMenuId, editingConversationId, onChatListOverlayChange]);

  useLayoutEffect(() => {
    if (!deleteConfirmation.conversation) return;
    const previous = document.activeElement;
    deleteModalCancelRef.current?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setDeleteConfirmation({ conversation: null });
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (previous instanceof HTMLElement && document.contains(previous)) {
        previous.focus({ preventScroll: true });
      }
    };
  }, [deleteConfirmation.conversation]);

  useEffect(() => {
    if (!openMenuId) return;

    const handleClickOutside = (event: MouseEvent) => {
      const menuElement = menuRefs.current[openMenuId];
      const buttonElement = buttonRefs.current[openMenuId];
      const target = event.target as Node;

      if (menuElement && menuElement.contains(target)) {
        return;
      }
      if (buttonElement && buttonElement.contains(target)) {
        return;
      }

      setOpenMenuId(null);
    };

    const timeoutId = setTimeout(() => {
      document.addEventListener("mousedown", handleClickOutside);
    }, 0);

    return () => {
      clearTimeout(timeoutId);
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [openMenuId]);

  const handleRename = (conversation: Conversation) => {
    setEditingConversationId(conversation.id);
    setEditingTitle(conversation.title);
    setOpenMenuId(null);
    setTimeout(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    }, 0);
  };

  const handleSaveRename = async (itemId: string) => {
    const trimmedTitle = editingTitle.trim();
    if (!trimmedTitle) {
      setEditingConversationId(null);
      return;
    }

    if (isChatSection(title)) {
      const conversation = conversations.find((c) => c.id === itemId);
      if (conversation && trimmedTitle !== conversation.title) {
        try {
          await updateConversationTitle(itemId, trimmedTitle);
          fetchConversations();
        } catch (error) {
          logger.error("Failed to rename conversation:", error);
        }
      }
      setEditingConversationId(null);
    }
  };

  const handleCancelRename = () => {
    isCancellingRef.current = true;
    setEditingConversationId(null);
    setEditingTitle("");
    setTimeout(() => {
      isCancellingRef.current = false;
    }, 0);
  };

  const handleDelete = (conversation: Conversation) => {
    setDeleteConfirmation({ conversation });
    setOpenMenuId(null);
  };

  const confirmDelete = async () => {
    if (deleteConfirmation.conversation) {
      try {
        await deleteConversation(deleteConfirmation.conversation.id);
        fetchConversations();
      } catch (error) {
        logger.error("Failed to delete conversation:", error);
      }
    }
    setDeleteConfirmation({ conversation: null });
  };

  const cancelDelete = () => {
    setDeleteConfirmation({ conversation: null });
  };

  const rowItems: Array<Conversation | { id: string; title: string }> = isChatSection(title)
    ? conversations
    : itemsWithIds || items.map((name, idx) => ({ id: idx.toString(), title: name }));

  const emptyLabel = isChatSection(title)
    ? (title.trim() ? title.toLowerCase() : "chats")
    : title.toLowerCase();

  return (
    <>
      {typeof document !== "undefined" &&
        deleteConfirmation.conversation &&
        createPortal(
          <div
            style={{
              position: "fixed",
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              backgroundColor: "rgba(0, 0, 0, 0.5)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              zIndex: 2147483646,
            }}
            onClick={cancelDelete}
            onMouseDown={(e) => {
              if (e.target === e.currentTarget) e.preventDefault();
            }}
          >
            <div
              role="dialog"
              aria-modal="true"
              aria-labelledby={deleteDialogTitleId}
              onClick={(e) => e.stopPropagation()}
              style={{
                background: "#fff",
                borderRadius: "8px",
                padding: "1.5rem",
                minWidth: "400px",
                maxWidth: "500px",
                boxShadow:
                  "0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)",
              }}
            >
              <h3 id={deleteDialogTitleId} style={{ margin: "0 0 1rem 0", fontSize: "1.25rem", fontWeight: 600 }}>
                Delete conversation
              </h3>
              <p style={{ margin: "0 0 1.5rem 0", color: "#6b7280", fontSize: "0.875rem" }}>
                Are you sure you want to delete &quot;{deleteConfirmation.conversation?.title || ""}&quot;? This
                action cannot be undone.
              </p>
              <div style={{ display: "flex", gap: "0.75rem", justifyContent: "flex-end" }}>
                <button
                  ref={deleteModalCancelRef}
                  type="button"
                  onClick={cancelDelete}
                  style={{
                    padding: "0.5rem 1rem",
                    border: "1px solid #e5e7eb",
                    borderRadius: "6px",
                    background: "#fff",
                    color: "#111",
                    cursor: "pointer",
                    fontSize: "0.875rem",
                    fontWeight: 500,
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = "#f3f0ec";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "#fff";
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={confirmDelete}
                  style={{
                    padding: "0.5rem 1rem",
                    border: "none",
                    borderRadius: "6px",
                    background: "#ef4444",
                    color: "#fff",
                    cursor: "pointer",
                    fontSize: "0.875rem",
                    fontWeight: 500,
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = "#dc2626";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "#ef4444";
                  }}
                >
                  Delete
                </button>
              </div>
            </div>
          </div>,
          document.body
        )}

      {isCollapsed ? null : (
        <div
          ref={(el) => {
            sidebarSectionRef.current = el;
          }}
          style={{
            display: "flex",
            flexDirection: "column",
            flexShrink: 0,
            minHeight: "max-content",
          }}
        >
          <div
            style={{
              fontWeight: 600,
              marginBottom: "0.5rem",
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
              cursor: "pointer",
            }}
            onClick={() => setIsExpanded(!isExpanded)}
          >
            {isExpanded ? (
              <ChevronDownIcon color="#6b7280" style={{ display: "inline-block" }} />
            ) : (
              <ChevronRightIcon color="#6b7280" style={{ display: "inline-block" }} />
            )}
            <span>{title || "Chats"}</span>
          </div>

          {isExpanded && (
            <div
              onClick={(e) => {
                if (openMenuId) {
                  const target = e.target as HTMLElement;
                  const menuElement = menuRefs.current[openMenuId];
                  if (menuElement && !menuElement.contains(target)) {
                    setOpenMenuId(null);
                  }
                }
              }}
              style={{
                marginLeft: "0.5rem",
                marginRight: "0.5rem",
                display: "flex",
                flexDirection: "column",
                gap: "0.25rem",
              }}
            >
              {isLoadingConversations && (
                <div style={{ fontSize: "0.8rem", color: "#6b7280", padding: "0.5rem 0.75rem" }}>
                  Loading conversations...
                </div>
              )}

              {conversationsError && (
                <div style={{ fontSize: "0.8rem", color: "#ef4444", padding: "0.5rem 0.75rem" }}>
                  {conversationsError}
                </div>
              )}

              {!isLoadingConversations &&
                !conversationsError &&
                rowItems.map((item) => {
                  const conversation = "createdAt" in item ? (item as Conversation) : null;
                  const generic = !conversation ? (item as { id: string; title: string }) : null;
                  const displayName = conversation ? conversation.title : generic!.title;
                  const itemId = conversation ? conversation.id : generic!.id;
                  const isMenuOpen = openMenuId === itemId;

                  return (
                    <div
                      key={itemId}
                      style={{
                        display: "flex",
                        alignItems: "flex-start",
                        gap: "0.25rem",
                        overflow: "visible",
                      }}
                    >
                      {conversation && editingConversationId === conversation.id ? (
                        <input
                          ref={inputRef}
                          type="text"
                          value={editingTitle}
                          onChange={(e) => setEditingTitle(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              handleSaveRename(itemId);
                            } else if (e.key === "Escape") {
                              e.preventDefault();
                              handleCancelRename();
                            }
                          }}
                          onBlur={() => {
                            if (!isCancellingRef.current) {
                              handleSaveRename(itemId);
                            }
                          }}
                          style={{
                            ...sidebarItemButton,
                            flex: 1,
                            outline: "none",
                            cursor: "text",
                          }}
                        />
                      ) : (
                        <button
                          className="sidebar-button"
                          style={{
                            ...sidebarItemButton,
                            flex: 1,
                            background: selectedConversationId === itemId ? "#f3f0ec" : sidebarItemButton.background,
                            fontWeight: selectedConversationId === itemId ? 600 : sidebarItemButton.fontWeight,
                            display: "flex",
                            alignItems: "center",
                            gap: "0.5rem",
                          }}
                          onClick={() => {
                            if (openMenuId) {
                              setOpenMenuId(null);
                            }
                            if (onConversationSelect && conversation) {
                              onConversationSelect(conversation.id, conversation.title);
                            } else if (onConversationSelect && generic) {
                              onConversationSelect(generic.id);
                            }
                          }}
                        >
                          {conversation &&
                            activeDeepResearchConversations &&
                            activeDeepResearchConversations.has(itemId) && (
                              <SpinnerIcon width="14" height="14" color="#3b82f6" style={{ flexShrink: 0 }} />
                            )}
                          <span style={{ flex: 1, textAlign: "left" }}>{displayName}</span>
                        </button>
                      )}
                      {conversation && (
                        <div
                          style={{
                            position: "relative",
                            paddingRight: "0.25rem",
                            marginTop: "0.25rem",
                          }}
                          ref={(el) => {
                            menuRefs.current[itemId] = el;
                          }}
                        >
                          <button
                            ref={(el) => {
                              buttonRefs.current[itemId] = el;
                            }}
                            aria-label={`Options for ${displayName}`}
                            aria-expanded={isMenuOpen}
                            onClick={(e) => {
                              e.preventDefault();
                              e.stopPropagation();
                              setOpenMenuId(isMenuOpen ? null : itemId);
                            }}
                            style={{
                              border: "none",
                              background: "transparent",
                              cursor: "pointer",
                              padding: "0.25rem",
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                              borderRadius: "4px",
                            }}
                            onMouseEnter={(e) => {
                              e.currentTarget.style.background = "#f3f0ec";
                            }}
                            onMouseLeave={(e) => {
                              e.currentTarget.style.background = "transparent";
                            }}
                          >
                            <ThreeDotsIcon />
                          </button>
                          {isMenuOpen && (
                            <div
                              role="menu"
                              onClick={(e) => e.stopPropagation()}
                              style={{
                                position: "absolute",
                                right: "0",
                                top: "100%",
                                marginTop: "0.25rem",
                                background: "#fff",
                                border: "1px solid #e5e7eb",
                                borderRadius: "8px",
                                boxShadow:
                                  "0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)",
                                zIndex: 1000,
                                minWidth: "150px",
                                padding: "0.25rem",
                              }}
                            >
                              <button
                                role="menuitem"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  if (conversation) {
                                    handleRename(conversation);
                                  }
                                }}
                                style={{
                                  width: "100%",
                                  border: "none",
                                  background: "transparent",
                                  padding: "0.5rem 0.75rem",
                                  cursor: "pointer",
                                  display: "flex",
                                  alignItems: "center",
                                  gap: "0.5rem",
                                  fontSize: "0.875rem",
                                  color: "#111",
                                  borderRadius: "4px",
                                }}
                                onMouseEnter={(e) => {
                                  e.currentTarget.style.background = "#f3f0ec";
                                }}
                                onMouseLeave={(e) => {
                                  e.currentTarget.style.background = "transparent";
                                }}
                              >
                                <PencilIcon color="#6b7280" />
                                Rename
                              </button>
                              <button
                                type="button"
                                role="menuitem"
                                onMouseDown={(e) => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                }}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  if (conversation) {
                                    handleDelete(conversation);
                                  }
                                }}
                                style={{
                                  width: "100%",
                                  border: "none",
                                  background: "transparent",
                                  padding: "0.5rem 0.75rem",
                                  cursor: "pointer",
                                  display: "flex",
                                  alignItems: "center",
                                  gap: "0.5rem",
                                  fontSize: "0.875rem",
                                  color: "#ef4444",
                                  borderRadius: "4px",
                                }}
                                onMouseEnter={(e) => {
                                  e.currentTarget.style.background = "#fee2e2";
                                }}
                                onMouseLeave={(e) => {
                                  e.currentTarget.style.background = "transparent";
                                }}
                              >
                                <DeleteIcon />
                                Delete
                              </button>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}

              {!isLoadingConversations &&
                !conversationsError &&
                rowItems.length === 0 &&
                (isChatSection(title) ? (
                  <div style={{ fontSize: "0.8rem", color: "#6b7280", padding: "0.5rem 0.75rem" }}>
                    No {emptyLabel} yet.
                  </div>
                ) : items.length === 0 ? (
                  <div style={{ fontSize: "0.8rem", color: "#6b7280", padding: "0.5rem 0.75rem" }}>
                    No {emptyLabel} yet.
                  </div>
                ) : null)}
            </div>
          )}
        </div>
      )}
    </>
  );
}
