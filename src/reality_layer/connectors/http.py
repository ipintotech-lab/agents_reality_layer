import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    payload: dict[str, Any]


class HttpTransport(Protocol):
    def request(
        self, method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None = None
    ) -> HttpResponse:
        ...


class UrlLibTransport:
    def request(
        self, method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None = None
    ) -> HttpResponse:
        encoded = json.dumps(body).encode() if body is not None else None
        request = Request(url, data=encoded, headers=headers, method=method)
        with urlopen(request, timeout=15) as response:
            raw = response.read()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Connector response must be a JSON object")
        return HttpResponse(response.status, payload)
