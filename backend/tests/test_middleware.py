"""Tests for backend middleware behaviour."""

import os
from unittest.mock import patch

class TestStartupGate:
    def test_blocks_routes_before_ready(self, app_client):
        """With is_ready patched to False, non-allowlisted routes return 503."""
        from starlette.testclient import TestClient
        from app.api.main import app

        with patch("app.core.startup_state.is_ready", return_value=False):
            with TestClient(app, raise_server_exceptions=False) as c:
                r = c.post("/get_all_conversations")
                assert r.status_code == 503
                assert "starting up" in r.json()["detail"].lower()

    def test_allows_healthz_before_ready(self, app_client):
        from starlette.testclient import TestClient
        from app.api.main import app

        with patch("app.core.startup_state.is_ready", return_value=False):
            with TestClient(app, raise_server_exceptions=False) as c:
                assert c.get("/healthz").status_code == 200

    def test_allows_startup_status_before_ready(self, app_client):
        from starlette.testclient import TestClient
        from app.api.main import app

        with patch("app.core.startup_state.is_ready", return_value=False):
            with TestClient(app, raise_server_exceptions=False) as c:
                assert c.get("/startup_status").status_code == 200


class TestSidecarToken:
    """Test SidecarTokenMiddleware using a standalone app to avoid the
    recursion issue with patching os.environ.get on the shared app."""

    @staticmethod
    def _make_token_app(token: str):
        """Build a minimal FastAPI app with the sidecar middleware attached."""
        from fastapi import FastAPI
        from fastapi.responses import PlainTextResponse
        from app.core.middleware import SidecarTokenMiddleware

        test_app = FastAPI()
        test_app.add_middleware(SidecarTokenMiddleware)

        @test_app.get("/healthz")
        def healthz():
            return PlainTextResponse("ok")

        @test_app.post("/protected")
        def protected():
            return {"status": "ok"}

        return test_app

    def test_rejects_without_token(self):
        from starlette.testclient import TestClient

        app = self._make_token_app("secret123")
        with patch.dict(os.environ, {"QUANTSCRIPT_SIDECAR_TOKEN": "secret123"}):
            with TestClient(app, raise_server_exceptions=False) as c:
                r = c.post("/protected")
                assert r.status_code == 401

    def test_accepts_correct_token(self):
        from starlette.testclient import TestClient

        app = self._make_token_app("secret123")
        with patch.dict(os.environ, {"QUANTSCRIPT_SIDECAR_TOKEN": "secret123"}):
            with TestClient(app, raise_server_exceptions=False) as c:
                r = c.post("/protected", headers={"X-Sidecar-Token": "secret123"})
                assert r.status_code == 200

    def test_rejects_wrong_token(self):
        from starlette.testclient import TestClient

        app = self._make_token_app("secret123")
        with patch.dict(os.environ, {"QUANTSCRIPT_SIDECAR_TOKEN": "secret123"}):
            with TestClient(app, raise_server_exceptions=False) as c:
                r = c.post("/protected", headers={"X-Sidecar-Token": "wrong"})
                assert r.status_code == 401

    def test_healthz_exempt(self):
        from starlette.testclient import TestClient

        app = self._make_token_app("secret123")
        with patch.dict(os.environ, {"QUANTSCRIPT_SIDECAR_TOKEN": "secret123"}):
            with TestClient(app, raise_server_exceptions=False) as c:
                r = c.get("/healthz")
                assert r.status_code == 200

    def test_passthrough_when_no_token_configured(self):
        from starlette.testclient import TestClient

        app = self._make_token_app("secret123")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("QUANTSCRIPT_SIDECAR_TOKEN", None)
            with TestClient(app, raise_server_exceptions=False) as c:
                r = c.post("/protected")
                assert r.status_code == 200


class TestSecurityHeaders:
    def test_security_headers_present(self, app_client):
        r = app_client.get("/healthz")
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


class TestTrustedHost:
    """TrustedHostMiddleware must reject foreign Host headers in every mode
    (DNS-rebinding defense), while accepting loopback hosts."""

    def test_rejects_untrusted_host(self, app_client):
        r = app_client.get("/healthz", headers={"Host": "attacker.example.com"})
        assert r.status_code == 400

    def test_allows_loopback_host(self, app_client):
        for host in ("127.0.0.1", "localhost"):
            r = app_client.get("/healthz", headers={"Host": host})
            assert r.status_code == 200
