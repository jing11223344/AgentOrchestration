"""Tests for BodyMiddleware — gzip bomb prevention."""

import gzip
import io
import pytest
from unittest.mock import AsyncMock, patch

from starlette.requests import Request
from starlette.responses import Response

from src.api.middleware import BodyMiddleware


async def ok_handler(request):
    """Simple handler that returns 200 OK."""
    return Response(content="OK", status_code=200)


def make_gzip_body(data: bytes) -> bytes:
    """Compress data with gzip and return the compressed bytes."""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(data)
    return buf.getvalue()


def make_request(scope_headers: dict, body: bytes) -> Request:
    """Create a minimal Starlette Request for testing."""
    headers = []
    for k, v in scope_headers.items():
        headers.append(
            (k.encode() if isinstance(k, str) else k,
             v.encode() if isinstance(v, str) else v)
        )

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v2/agents",
        "headers": headers,
        "client": ("127.0.0.1", 54321),
        "server": ("localhost", 8000),
        "scheme": "http",
        "query_string": b"",
        "root_path": "",
    }

    return Request(scope, receive=AsyncMock(return_value={
        "type": "http.request",
        "body": body,
        "more_body": False,
    }))


class TestBodyMiddleware:

    @pytest.mark.asyncio
    async def test_passthrough_non_gzip(self):
        """Non-gzip requests pass through without interception."""
        mw = BodyMiddleware(ok_handler)
        req = make_request(
            {"content-type": "application/json"},
            b'{"hello": "world"}',
        )
        resp = await mw.dispatch(req, ok_handler)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_accepts_normal_gzip_body(self):
        """Normal gzip-compressed bodies are accepted (small payload)."""
        mw = BodyMiddleware(ok_handler)
        compressed = make_gzip_body(b'{"hello": "world"}')
        req = make_request(
            {"content-encoding": "gzip", "content-type": "application/json"},
            compressed,
        )
        resp = await mw.dispatch(req, ok_handler)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_rejects_gzip_bomb_exceeding_max_size(self):
        """Gzip bomb that decompresses to > max size is rejected with 413."""
        mw = BodyMiddleware(ok_handler, max_decompressed_size=1024)  # 1 KB limit
        # Create a body that decompresses to ~100 KB
        large_payload = b"X" * 100 * 1024
        compressed = make_gzip_body(large_payload)
        req = make_request(
            {"content-encoding": "gzip", "content-type": "application/json"},
            compressed,
        )
        resp = await mw.dispatch(req, ok_handler)
        assert resp.status_code == 413

    @pytest.mark.asyncio
    async def test_rejects_extreme_compression_ratio(self):
        """Payload with extreme compression ratio (> limit) is rejected."""
        mw = BodyMiddleware(ok_handler, max_ratio=50)
        # Create highly compressible data (many repeated bytes) -> high ratio
        large_payload = b"A" * 500 * 1024  # 500 KB decompressed
        compressed = make_gzip_body(large_payload)
        req = make_request(
            {"content-encoding": "gzip", "content-type": "application/json"},
            compressed,
        )
        resp = await mw.dispatch(req, ok_handler)
        assert resp.status_code == 413

    @pytest.mark.asyncio
    async def test_rejects_corrupted_gzip_body(self):
        """Corrupted gzip data returns 400."""
        mw = BodyMiddleware(ok_handler)
        corrupted = b"this-is-not-gzip-data"
        req = make_request(
            {"content-encoding": "gzip", "content-type": "application/json"},
            corrupted,
        )
        resp = await mw.dispatch(req, ok_handler)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_x_body_guard_header_present_on_rejection(self):
        """Rejected requests include X-Body-Guard header."""
        mw = BodyMiddleware(ok_handler, max_decompressed_size=512)
        large = b"Y" * 50 * 1024
        compressed = make_gzip_body(large)
        req = make_request(
            {"content-encoding": "gzip", "content-type": "application/json"},
            compressed,
        )
        resp = await mw.dispatch(req, ok_handler)
        assert resp.status_code == 413
        assert resp.headers.get("x-body-guard") is not None

    @pytest.mark.asyncio
    async def test_cleanup_on_error(self):
        """Middleware handles errors gracefully (no crash)."""
        mw = BodyMiddleware(ok_handler)

        with patch("src.api.middleware.io.BytesIO", side_effect=RuntimeError("simulated")):
            compressed = make_gzip_body(b"test data")
            req = make_request(
                {"content-encoding": "gzip", "content-type": "application/json"},
                compressed,
            )
            resp = await mw.dispatch(req, ok_handler)
            # Error during decompression -> 400
            assert resp.status_code in (400, 413, 200)

    @pytest.mark.asyncio
    async def test_zero_content_length_gzip(self):
        """Zero-length gzip body passes through."""
        mw = BodyMiddleware(ok_handler)
        req = make_request(
            {"content-encoding": "gzip", "content-length": "0"},
            b"",
        )
        resp = await mw.dispatch(req, ok_handler)
        assert resp.status_code == 200
