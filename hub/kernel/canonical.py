"""JSON canonique et empreintes : clés triées, sans espaces, UTF-8."""

import hashlib
import json
from typing import Any


def dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(dumps(value).encode()).hexdigest()
