import type { StartupPhase, StartupStatusPayload } from "./api";

interface Props {
  snapshot: StartupStatusPayload | null;
  waitingForServer: boolean;
  startupErrorMessage?: string | null;
  onRetry?: () => void;
  onExit?: () => void;
}

function phaseBarFill(phase: StartupPhase): {
  width: string;
  background: string;
  animation?: string;
} {
  switch (phase.status) {
    case "done":
      return { width: "100%", background: "#3b82f6" };
    case "running":
      if (phase.percent != null) {
        return {
          width: `${Math.max(0, Math.min(100, phase.percent))}%`,
          background: "#3b82f6",
        };
      }
      return {
        width: "100%",
        background: "#3b82f6",
        animation: "loading-bar 1.5s ease-in-out infinite",
      };
    case "error":
      return { width: "100%", background: "#dc2626" };
    default:
      return { width: "0%", background: "#3b82f6" };
  }
}

function phaseCaption(phase: StartupPhase): string {
  const text = phase.detail ?? phase.label;
  if (phase.status === "running" && phase.percent != null) {
    return `${text} (${phase.percent}%)`;
  }
  return text;
}

export default function InitializingScreen({
  snapshot,
  waitingForServer,
  startupErrorMessage,
  onRetry,
  onExit,
}: Props) {
  const fatalError = startupErrorMessage ?? snapshot?.error ?? null;
  const phases = snapshot?.phases ?? [];

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "#fcfaf9",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "1.25rem",
        zIndex: 9999,
        padding: "1.5rem",
        boxSizing: "border-box",
      }}
    >
      <div
        style={{
          width: 48,
          height: 48,
          border: "4px solid #e5e7eb",
          borderTop: "4px solid #3b82f6",
          borderRadius: "50%",
          animation: "spin 1s linear infinite",
          flexShrink: 0,
        }}
      />
      <div style={{ color: "#374151", fontSize: "1.15rem", fontWeight: 600, textAlign: "center" }}>
        Initializing application
      </div>
      <div
        style={{
          color: "#6b7280",
          fontSize: "0.9rem",
          maxWidth: 440,
          textAlign: "center",
          lineHeight: 1.55,
        }}
      >
        Loading the language model. On first use this can take several
        minutes while weights download and cache — please keep this page open.
      </div>
      {waitingForServer && !snapshot && (
        <div style={{ color: "#9ca3af", fontSize: "0.85rem" }}>Waiting for server…</div>
      )}
      {fatalError && (
        <div
          style={{
            maxWidth: 480,
            padding: "0.75rem 1rem",
            background: "#fef2f2",
            border: "1px solid #fecaca",
            borderRadius: "8px",
            color: "#991b1b",
            fontSize: "0.85rem",
            lineHeight: 1.45,
          }}
        >
          <strong style={{ display: "block", marginBottom: "0.35rem" }}>Startup failed</strong>
          {fatalError}
          <div style={{ marginTop: "0.75rem", display: "flex", gap: "0.55rem", flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={() => {
                if (onRetry) {
                  onRetry();
                } else {
                  window.location.reload();
                }
              }}
              style={{ padding: "0.4rem 0.9rem", fontSize: "0.85rem" }}
            >
              Retry startup
            </button>
            {onExit && (
              <button
                type="button"
                onClick={onExit}
                style={{ padding: "0.4rem 0.9rem", fontSize: "0.85rem" }}
              >
                Exit app
              </button>
            )}
          </div>
        </div>
      )}
      {!fatalError && phases.length > 0 && (
        <div
          style={{
            width: "100%",
            maxWidth: 520,
            display: "flex",
            flexDirection: "column",
            gap: "0.85rem",
            marginTop: "0.25rem",
          }}
        >
          {phases.map((phase) => {
            const fill = phaseBarFill(phase);
            return (
              <div key={phase.id}>
                <div
                  style={{
                    fontSize: "0.8rem",
                    color: phase.status === "error" ? "#b91c1c" : "#4b5563",
                    marginBottom: "0.35rem",
                    lineHeight: 1.35,
                  }}
                >
                  {phaseCaption(phase)}
                </div>
                <div
                  style={{
                    width: "100%",
                    height: 6,
                    backgroundColor: "#e5e7eb",
                    borderRadius: 3,
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      height: "100%",
                      borderRadius: 3,
                      transition: "width 0.35s ease",
                      transformOrigin: "left",
                      ...fill,
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
