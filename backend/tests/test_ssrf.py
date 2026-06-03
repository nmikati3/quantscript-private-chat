"""Tests for SSRF protection in web_search module."""

import ipaddress
import socket
from unittest.mock import patch

from app.engine.llm.web_search import (
    _fetch_html_with_redirect_guards,
    _is_ip_blocked,
    _is_url_safe,
    _pin_url_to_ip,
    _resolve_safe_ip,
    _validate_url_and_resolve_ip,
)


class TestIsIpBlocked:
    def test_localhost_blocked(self):
        assert _is_ip_blocked(ipaddress.ip_address("127.0.0.1")) is True

    def test_localhost_ipv6_blocked(self):
        assert _is_ip_blocked(ipaddress.ip_address("::1")) is True

    def test_ipv4_mapped_localhost_blocked(self):
        assert _is_ip_blocked(ipaddress.ip_address("::ffff:127.0.0.1")) is True

    def test_private_10_blocked(self):
        assert _is_ip_blocked(ipaddress.ip_address("10.0.0.1")) is True

    def test_private_172_blocked(self):
        assert _is_ip_blocked(ipaddress.ip_address("172.16.0.1")) is True

    def test_private_192_blocked(self):
        assert _is_ip_blocked(ipaddress.ip_address("192.168.1.1")) is True

    def test_link_local_blocked(self):
        assert _is_ip_blocked(ipaddress.ip_address("169.254.1.1")) is True

    def test_cgnat_blocked(self):
        assert _is_ip_blocked(ipaddress.ip_address("100.64.0.1")) is True

    def test_public_ip_allowed(self):
        assert _is_ip_blocked(ipaddress.ip_address("8.8.8.8")) is False

    def test_another_public_ip_allowed(self):
        assert _is_ip_blocked(ipaddress.ip_address("1.1.1.1")) is False


class TestIsUrlSafe:
    def _mock_dns(self, ip_str):
        """Return a mock for socket.getaddrinfo that resolves to the given IP."""
        info = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip_str, 80))]
        return patch("app.engine.llm.web_search.socket.getaddrinfo", return_value=info)

    def test_blocks_non_http_scheme(self):
        assert _is_url_safe("ftp://example.com/file") is False

    def test_blocks_file_scheme(self):
        assert _is_url_safe("file:///etc/passwd") is False

    def test_blocks_javascript_scheme(self):
        assert _is_url_safe("javascript:alert(1)") is False

    def test_blocks_no_hostname(self):
        assert _is_url_safe("http://") is False

    def test_blocks_non_standard_port(self):
        with self._mock_dns("93.184.216.34"):
            assert _is_url_safe("http://example.com:8080/path") is False

    def test_allows_port_80(self):
        with self._mock_dns("93.184.216.34"):
            assert _is_url_safe("http://example.com:80/path") is True

    def test_allows_port_443(self):
        with self._mock_dns("93.184.216.34"):
            assert _is_url_safe("https://example.com:443/path") is True

    def test_allows_default_port(self):
        with self._mock_dns("93.184.216.34"):
            assert _is_url_safe("https://example.com/path") is True

    def test_blocks_localhost_url(self):
        with self._mock_dns("127.0.0.1"):
            assert _is_url_safe("http://localhost/admin") is False

    def test_blocks_ipv4_mapped_localhost_url(self):
        with self._mock_dns("::ffff:127.0.0.1"):
            assert _is_url_safe("http://localhost/admin") is False

    def test_blocks_private_ip_url(self):
        with self._mock_dns("10.0.0.1"):
            assert _is_url_safe("http://internal.corp/secret") is False

    def test_allows_public_ip_url(self):
        with self._mock_dns("93.184.216.34"):
            assert _is_url_safe("https://example.com/page") is True

    def test_dns_failure_blocks(self):
        with patch(
            "app.engine.llm.web_search.socket.getaddrinfo",
            side_effect=socket.gaierror("DNS failed"),
        ):
            assert _is_url_safe("http://nonexistent.invalid") is False


class TestValidateUrlAndResolveIp:
    """The shared SSRF chokepoint used by both _is_url_safe and the fetch loop."""

    def _mock_dns(self, ip_str):
        info = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip_str, 80))]
        return patch("app.engine.llm.web_search.socket.getaddrinfo", return_value=info)

    def test_returns_pinned_ip_for_public_url(self):
        with self._mock_dns("93.184.216.34"):
            assert _validate_url_and_resolve_ip("https://example.com/page") == "93.184.216.34"

    def test_returns_none_for_private_ip(self):
        with self._mock_dns("10.0.0.1"):
            assert _validate_url_and_resolve_ip("http://internal.corp/secret") is None

    def test_returns_none_for_ipv4_mapped_private_ip(self):
        with self._mock_dns("::ffff:127.0.0.1"):
            assert _validate_url_and_resolve_ip("http://internal.corp/secret") is None

    def test_returns_none_for_bad_scheme(self):
        assert _validate_url_and_resolve_ip("file:///etc/passwd") is None

    def test_returns_none_for_disallowed_port(self):
        with self._mock_dns("93.184.216.34"):
            assert _validate_url_and_resolve_ip("http://example.com:8080/x") is None

    def test_returns_none_on_dns_failure(self):
        with patch(
            "app.engine.llm.web_search.socket.getaddrinfo",
            side_effect=socket.gaierror("DNS failed"),
        ):
            assert _validate_url_and_resolve_ip("http://nonexistent.invalid") is None


class TestFetchHtmlSsrf:
    """Exercise the real production guard, not just the boolean pre-filter.

    Each rejection is caught by _validate_url_and_resolve_ip and short-circuits
    to "" before any network call, so these need no HTTP mocking.
    """

    def _mock_dns(self, ip_str):
        info = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip_str, 80))]
        return patch("app.engine.llm.web_search.socket.getaddrinfo", return_value=info)

    def test_private_ip_is_rejected(self):
        with self._mock_dns("127.0.0.1"):
            assert _fetch_html_with_redirect_guards("http://localhost/admin") == ""

    def test_bad_scheme_is_rejected(self):
        assert _fetch_html_with_redirect_guards("file:///etc/passwd") == ""

    def test_disallowed_port_is_rejected(self):
        with self._mock_dns("93.184.216.34"):
            assert _fetch_html_with_redirect_guards("http://example.com:8080/x") == ""

    def test_dns_failure_is_rejected(self):
        with patch(
            "app.engine.llm.web_search.socket.getaddrinfo",
            side_effect=socket.gaierror("DNS failed"),
        ):
            assert _fetch_html_with_redirect_guards("http://nonexistent.invalid") == ""

    def test_redirect_to_private_ip_is_blocked(self):
        # The first hop is public and returns a 302 pointing at an internal
        # host; the redirect target resolves to a private IP and must be
        # rejected on the next hop. This is the core redirect-chain SSRF guard.
        def fake_getaddrinfo(host, *_args, **_kwargs):
            ip = "93.184.216.34" if host == "public.example" else "10.0.0.1"
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 80))]

        class _RedirectResponse:
            status_code = 302
            headers = {"location": "http://internal.corp/secret"}

        def fake_get(_self, *_args, **_kwargs):
            return _RedirectResponse()

        with patch(
            "app.engine.llm.web_search.socket.getaddrinfo",
            side_effect=fake_getaddrinfo,
        ), patch("app.engine.llm.web_search.requests.Session.get", new=fake_get):
            assert _fetch_html_with_redirect_guards("http://public.example/page") == ""


class TestResolveSafeIp:
    def _mock_dns(self, *ip_strs):
        info = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 80)) for ip in ip_strs]
        return patch("app.engine.llm.web_search.socket.getaddrinfo", return_value=info)

    def test_returns_public_ip(self):
        with self._mock_dns("93.184.216.34"):
            assert _resolve_safe_ip("example.com") == "93.184.216.34"

    def test_returns_none_for_private(self):
        with self._mock_dns("10.0.0.1"):
            assert _resolve_safe_ip("internal.corp") is None

    def test_rejects_when_any_record_is_private(self):
        # A public + private mix (DNS rebinding via multiple A records) must be
        # rejected outright, not have the public record cherry-picked.
        with self._mock_dns("93.184.216.34", "127.0.0.1"):
            assert _resolve_safe_ip("mixed.example") is None

    def test_dns_failure_returns_none(self):
        with patch(
            "app.engine.llm.web_search.socket.getaddrinfo",
            side_effect=socket.gaierror("DNS failed"),
        ):
            assert _resolve_safe_ip("nonexistent.invalid") is None


class TestPinUrlToIp:
    def test_pins_host_keeps_path_and_scheme(self):
        assert _pin_url_to_ip("https://example.com/page?q=1", "93.184.216.34") == (
            "https://93.184.216.34:443/page?q=1"
        )

    def test_pins_http_default_port(self):
        assert _pin_url_to_ip("http://example.com/x", "1.2.3.4") == "http://1.2.3.4:80/x"

    def test_preserves_explicit_port(self):
        assert _pin_url_to_ip("http://example.com:80/x", "1.2.3.4") == "http://1.2.3.4:80/x"

    def test_ipv6_is_bracketed(self):
        assert _pin_url_to_ip("https://example.com/x", "2606:2800:220:1::1") == (
            "https://[2606:2800:220:1::1]:443/x"
        )
