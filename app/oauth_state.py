from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict


class StateSigner:
    def __init__(self, secret: str) -> None:
        self.secret = secret.encode("utf-8")

    def dumps(self, payload: Dict[str, Any]) -> str:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        signature = hmac.new(self.secret, body, hashlib.sha256).hexdigest().encode("ascii")
        return base64.urlsafe_b64encode(body + b"." + signature).decode("ascii")

    def loads(self, token: str) -> Dict[str, Any]:
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
        body, provided = raw.rsplit(b".", 1)
        expected = hmac.new(self.secret, body, hashlib.sha256).hexdigest().encode("ascii")
        if not hmac.compare_digest(provided, expected):
            raise ValueError("Invalid state signature")
        payload = json.loads(body.decode("utf-8"))
        exp = int(payload.get("exp", 0))
        if exp and exp < int(time.time()):
            raise ValueError("State expired")
        return payload
