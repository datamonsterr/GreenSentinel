"""Bounded urllib transport that refuses credential-bearing redirects."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward credentials, log the target, or retain its headers/body.
        raise HTTPError("", code, "Provider redirect blocked", {}, None)


class _BoundedResponse:
    def __init__(self, response: Any):
        self._response = response
        self.status = response.status

    def read(self) -> bytes:
        body = self._response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("Provider response exceeds limit")
        return body


@contextmanager
def safe_urlopen(url: Any, *, timeout: float) -> Iterator[_BoundedResponse]:
    req = Request(url, headers={"User-Agent": "AI20K-GreenSentinel-Simulation/1.0"}) if isinstance(url, str) else url
    with build_opener(_NoRedirect()).open(req, timeout=timeout) as response:
        yield _BoundedResponse(response)


@contextmanager
def safe_urlpost(
    path: str, body: bytes, *, timeout: float, content_type: str = "application/json"
) -> Iterator[_BoundedResponse]:
    request = Request(path, data=body, method="POST", headers={"Content-Type": content_type})
    with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
        yield _BoundedResponse(response)
