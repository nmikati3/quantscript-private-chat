import asyncio
import ipaddress
import logging
import re
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse, urlunparse
import requests
from requests.adapters import HTTPAdapter
import trafilatura
from bs4 import BeautifulSoup
from webserp.cli import search as _webserp_search

logger = logging.getLogger(__name__)

_BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

_MAX_FETCH_BYTES = 1_500_000  # 1.5 MB hard cap
_MAX_REDIRECTS = 3
_ALLOWED_PORTS = {80, 443, None}
_MAX_ARTICLE_CHARS = 2_500  # ~625 tokens per article; 5 articles ≈ 3k tokens total

_OFFICIAL_DOMAIN_PATTERNS_FILE = Path(__file__).resolve().parent / "official_domain_patterns.txt"


def _load_official_domain_patterns() -> list[str]:
    """Load hostname regex patterns from official_domain_patterns.txt (one per line)."""
    if not _OFFICIAL_DOMAIN_PATTERNS_FILE.is_file():
        logger.warning("Official domain patterns file not found: %s", _OFFICIAL_DOMAIN_PATTERNS_FILE)
        return []
    patterns: list[str] = []
    for line in _OFFICIAL_DOMAIN_PATTERNS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


_OFFICIAL_DOMAIN_PATTERNS = _load_official_domain_patterns()


def _is_ip_blocked(addr) -> bool:
    mapped_ipv4 = getattr(addr, "ipv4_mapped", None)
    if mapped_ipv4 is not None:
        addr = mapped_ipv4
    for network in _BLOCKED_IP_NETWORKS:
        if addr in network:
            return True
    return False


def _resolve_safe_ip(hostname: str) -> str | None:
    """Resolve a hostname and return a single validated IP to connect to.

    Returns None if resolution fails or if ANY resolved address falls in a
    blocked (private/reserved/loopback) range. Rejecting when *any* record is
    unsafe prevents multi-record DNS tricks. The returned IP is then pinned for
    the actual connection so a second resolution can't swap in a private IP
    (DNS-rebinding TOCTOU).
    """
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except (socket.gaierror, OSError):
        return None

    safe_ip: str | None = None
    for info in infos:
        ip_str = info[4][0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return None
        if _is_ip_blocked(addr):
            logger.warning("Blocked SSRF attempt to %s (resolved to %s)", hostname, addr)
            return None
        if safe_ip is None:
            safe_ip = ip_str
    return safe_ip


def _validate_url_and_resolve_ip(url: str) -> str | None:
    """Single SSRF chokepoint: validate a URL and return a safe IP to connect to.

    Performs every SSRF check in one place — scheme allow-list, hostname
    presence, port allow-list, and DNS resolution that rejects any
    private/reserved address — and returns the validated IP to pin the
    connection to. Returns None if the URL violates policy.

    Callers MUST connect to the returned IP rather than re-resolving the
    hostname; that pinning is what closes the DNS-rebinding TOCTOU window.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return None
        hostname = parsed.hostname
        if not hostname:
            return None
        if parsed.port not in _ALLOWED_PORTS:
            return None
    except ValueError:
        return None
    return _resolve_safe_ip(hostname)


def _is_url_safe(url: str) -> bool:
    """Boolean view of the SSRF policy for callers that only need a verdict.

    NOTE: a True result is only a *pre-filter*. The actual fetch path
    (_fetch_html_with_redirect_guards) re-runs _validate_url_and_resolve_ip and
    pins to the returned IP, because a bare yes/no can't prevent DNS rebinding.
    """
    return _validate_url_and_resolve_ip(url) is not None


def _pin_url_to_ip(url: str, ip: str) -> str:
    """Rewrite a URL's host to a fixed IP (preserving scheme/port/path/query).

    The original hostname is still sent in the Host header and used for TLS SNI
    / cert verification (see _PinnedHostHTTPSAdapter), so only the connection
    target is pinned.
    """
    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    netloc = f"[{ip}]:{port}" if ":" in ip else f"{ip}:{port}"
    return urlunparse(parsed._replace(netloc=netloc))


class _PinnedHostHTTPSAdapter(HTTPAdapter):
    """HTTPS adapter that keeps SNI + certificate verification bound to the
    original hostname even though the socket connects to a pinned IP."""

    def __init__(self, server_hostname: str, **kwargs):
        self._server_hostname = server_hostname
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        # urllib3 uses these to drive SNI and hostname verification against the
        # real hostname rather than the IP we connect to.
        kwargs["server_hostname"] = self._server_hostname
        kwargs["assert_hostname"] = self._server_hostname
        super().init_poolmanager(*args, **kwargs)


def _fetch_html_with_redirect_guards(url: str) -> str:
    """Fetch HTML while validating each redirect target against SSRF policy.

    Each hop is resolved and validated once, then the connection is pinned to
    the validated IP so DNS rebinding between check and connect cannot redirect
    us to an internal address.
    """
    current_url = url

    for _ in range(_MAX_REDIRECTS + 1):
        # Single SSRF chokepoint: validate + resolve in one place, then pin to
        # the returned IP so a re-resolution can't swap in an internal address.
        safe_ip = _validate_url_and_resolve_ip(current_url)
        if safe_ip is None:
            return ""

        parsed = urlparse(current_url)
        hostname = parsed.hostname

        pinned_url = _pin_url_to_ip(current_url, safe_ip)
        headers = {"User-Agent": "Mozilla/5.0", "Host": parsed.netloc}

        session = requests.Session()
        try:
            if parsed.scheme == "https":
                session.mount("https://", _PinnedHostHTTPSAdapter(hostname))

            response = session.get(
                pinned_url,
                headers=headers,
                timeout=(5, 10),
                allow_redirects=False,
                stream=True,
            )

            if 300 <= response.status_code < 400:
                location = response.headers.get("location")
                if not location:
                    return ""
                # Resolve relative redirects against the ORIGINAL url, not the
                # IP-pinned one, so the next hop validates the real hostname.
                current_url = requests.compat.urljoin(current_url, location)
                continue

            if response.status_code != 200:
                return ""

            chunks = []
            total = 0
            for chunk in response.iter_content(chunk_size=8192, decode_unicode=False):
                if not chunk:
                    continue
                total += len(chunk)
                if total > _MAX_FETCH_BYTES:
                    logger.warning("Aborting oversized article fetch (%s bytes): %s", total, hostname)
                    return ""
                chunks.append(chunk)

            encoding = response.encoding or response.apparent_encoding or "utf-8"
            return b"".join(chunks).decode(encoding, errors="replace")
        finally:
            session.close()

    return ""


def _official_score(url: str) -> int:
    """Return 1 if the URL belongs to a known official/authoritative domain, 0 otherwise."""
    hostname = (urlparse(url).hostname or "").lower()
    for pattern in _OFFICIAL_DOMAIN_PATTERNS:
        if re.search(pattern, hostname):
            return 1
    return 0


def _rank_results(results: list) -> list:
    """Stable-sort results so official/authoritative sources appear first."""
    return sorted(results, key=lambda r: _official_score(r.get("url", "")), reverse=True)


def web_search(query, n=5):
    """Sync variant — safe to call only when no event loop is running (e.g. regular chat search)."""
    result = asyncio.run(_webserp_search(query=query, max_results=n))
    return result["results"]


async def web_search_async(query, n=5):
    """Async variant — use inside an already-running event loop (e.g. deep research)."""
    result = await _webserp_search(query=query, max_results=n)
    return result["results"]


def fetch_article(url):
    """Extract main content from a URL using trafilatura, with BeautifulSoup fallback."""
    try:
        html = _fetch_html_with_redirect_guards(url)
        if not html:
            return ""

        text = trafilatura.extract(html, include_links=True, include_tables=True)

        if not text:
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            article = soup.find("article")
            text = (article or soup).get_text(separator="\n")

        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()[:_MAX_ARTICLE_CHARS]

    except Exception:
        return ""


def _build_articles(results):
    """Fetch articles in parallel, re-rank so official sources come first."""
    ranked = _rank_results(results)
    with ThreadPoolExecutor(max_workers=len(ranked) or 1) as pool:
        futures = {pool.submit(fetch_article, r["url"]): r for r in ranked}
        article_map = {}
        for future in as_completed(futures):
            r = futures[future]
            article_map[r["url"]] = future.result()

    return [
        {"title": r["title"], "url": r["url"], "content": article_map[r["url"]], "official": bool(_official_score(r["url"]))}
        for r in ranked
    ]


def web_search_and_fetch_articles(query, n=5):
    """Sync variant for the regular chat search path."""
    results = web_search(query, n)
    return _build_articles(results)


async def web_search_and_fetch_articles_async(query, n=5):
    """Async variant for deep research (avoids nested asyncio.run)."""
    results = await web_search_async(query, n)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _build_articles, results)

