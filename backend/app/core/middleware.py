from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import hmac
import os


def compute_allowed_origins() -> list[str]:
    """Origins permitted to call the API from a browser context.

    Always includes the Vite dev origin; desktop mode injects the Tauri origins
    via CORS_ORIGINS. Shared by the CORS layer and the cross-origin guard so the
    two can never drift apart.
    """
    origins = ["http://localhost:5173"]
    extra = os.environ.get("CORS_ORIGINS", "")
    origins.extend([o.strip() for o in extra.split(",") if o.strip()])
    # De-dupe while preserving order.
    return list(dict.fromkeys(origins))


def _allow_request_during_startup(path: str) -> bool:
    if path in ("/startup_status", "/startup_status_probe", "/healthz"):
        return True
    if path.startswith("/docs") or path.startswith("/redoc") or path == "/openapi.json":
        return True
    return False


class StartupGateMiddleware(BaseHTTPMiddleware):
    """Return 503 until background startup has finished (except allowlisted paths)."""

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path
        if _allow_request_during_startup(path):
            return await call_next(request)
        from app.core.startup_state import is_ready

        if not is_ready():
            return JSONResponse(
                {"detail": "Service is starting up. Please retry shortly."},
                status_code=503,
            )
        return await call_next(request)


class SidecarTokenMiddleware(BaseHTTPMiddleware):
    """In desktop mode, reject requests that don't carry the shared sidecar token."""

    async def dispatch(self, request: Request, call_next):
        expected = os.environ.get("QUANTSCRIPT_SIDECAR_TOKEN")
        if not expected:
            return await call_next(request)
        if request.method == "OPTIONS":
            return await call_next(request)
        if request.url.path in ("/startup_status_probe", "/healthz"):
            return await call_next(request)
        actual = request.headers.get("x-sidecar-token") or ""
        # Constant-time comparison to avoid leaking the token via timing.
        if not hmac.compare_digest(actual, expected):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)


class CrossOriginGuardMiddleware(BaseHTTPMiddleware):
    """Reject state-changing cross-origin requests (CSRF defense-in-depth).

    CORS stops a foreign site from *reading* responses, but it does not stop a
    "simple" request (e.g. a ``multipart/form-data`` upload, which is not
    preflighted) from *executing* its side effects. In browser mode there is no
    sidecar token, so this guard is the backstop: if a request carries an Origin
    header that isn't in our allowlist, we refuse to run it. Requests with no
    Origin header (curl, native clients, same-origin navigations) are allowed.
    """

    SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

    def __init__(self, app, allowed_origins: list[str]):
        super().__init__(app)
        self._allowed_origins = set(allowed_origins)

    async def dispatch(self, request: Request, call_next):
        if request.method not in self.SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin and origin not in self._allowed_origins:
                return JSONResponse(
                    {"detail": "Cross-origin request blocked"},
                    status_code=403,
                )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add standard security headers to all responses.

    For this local-only API, these headers are hygiene rather than meaningful
    protection (sidecar token, CORS, and localhost binding do the real work).
    """
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


def attach_middlewares(app: FastAPI) -> None:
    """Attach shared middlewares to the provided FastAPI app.

    Includes:
    - Security headers
    - Trusted hosts
    - CORS
    """
    # Innermost: gate API routes until models/data are loaded (CORS still wraps the 503).
    app.add_middleware(StartupGateMiddleware)

    # Sidecar token auth (desktop mode) — runs before startup gate.
    if os.environ.get("QUANTSCRIPT_SIDECAR_TOKEN"):
        app.add_middleware(SidecarTokenMiddleware)

    # Security headers middleware
    app.add_middleware(SecurityHeadersMiddleware)
    
    # TrustedHostMiddleware — ALWAYS on (every deployment mode), not just desktop.
    # Validating the Host header is the standard defense against DNS-rebinding
    # attacks: without it, a malicious website can rebind its domain to
    # 127.0.0.1:<port> and, because the browser then treats requests as
    # same-origin, bypass CORS to read/exfiltrate local conversation data.
    # Defaults to loopback only; can be extended (never replaced) via ALLOWED_HOSTS.
    allowed_hosts = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]
    for default_host in ("127.0.0.1", "localhost"):
        if default_host not in allowed_hosts:
            allowed_hosts.append(default_host)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=allowed_hosts,
    )
    
    # CORS middleware — locked down.
    # Auth is header-based (X-Sidecar-Token), not cookie-based. No session
    # cookies are ever issued, so allow_credentials is disabled: enabling it
    # would instruct browsers to attach ambient credentials (cookies, HTTP
    # auth) on cross-origin requests for no benefit, only added attack surface.
    origins = compute_allowed_origins()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Sidecar-Token"],
        allow_credentials=False,
    )

    # Cross-origin guard — outermost so it short-circuits forged cross-site
    # writes (incl. non-preflighted multipart uploads) before they run.
    app.add_middleware(CrossOriginGuardMiddleware, allowed_origins=origins)