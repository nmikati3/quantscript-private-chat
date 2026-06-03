import { Component, type ReactNode, type ErrorInfo } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Uncaught render error:", error, info.componentStack);
  }

  private handleReload = () => {
    window.location.reload();
  };

  private handleDismiss = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            height: "100vh",
            padding: "2rem",
            fontFamily: "system-ui, sans-serif",
            background: "#fcfaf9",
            color: "#111",
            textAlign: "center",
          }}
        >
          <h1 style={{ fontSize: "1.4rem", fontWeight: 700, margin: "0 0 0.75rem" }}>
            Something went wrong
          </h1>
          <p style={{ color: "#6b7280", fontSize: "0.95rem", margin: "0 0 0.5rem", maxWidth: "420px" }}>
            An unexpected error occurred while rendering the interface.
          </p>
          {this.state.error && (
            <pre
              style={{
                background: "#f3f0ec",
                borderRadius: "6px",
                padding: "0.75rem 1rem",
                fontSize: "0.8rem",
                color: "#92400e",
                maxWidth: "500px",
                overflow: "auto",
                margin: "0.5rem 0 1.25rem",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              {this.state.error.message}
            </pre>
          )}
          <div style={{ display: "flex", gap: "0.75rem" }}>
            <button
              onClick={this.handleDismiss}
              style={{
                padding: "0.5rem 1rem",
                border: "1px solid #d2d6db",
                borderRadius: "6px",
                background: "#fff",
                color: "#111",
                cursor: "pointer",
                fontSize: "0.9rem",
                fontWeight: 500,
              }}
            >
              Try to continue
            </button>
            <button
              onClick={this.handleReload}
              style={{
                padding: "0.5rem 1rem",
                border: "none",
                borderRadius: "6px",
                background: "#111",
                color: "#fff",
                cursor: "pointer",
                fontSize: "0.9rem",
                fontWeight: 500,
              }}
            >
              Reload app
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
