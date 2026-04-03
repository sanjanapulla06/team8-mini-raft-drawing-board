import os

import uvicorn


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value)


if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host=os.getenv("GATEWAY_HOST", "0.0.0.0"),
        port=int(os.getenv("GATEWAY_PORT", "8090")),
        reload=_get_bool("GATEWAY_RELOAD", False),
        ws="wsproto",
        ws_ping_interval=_get_float("GATEWAY_WS_PING_INTERVAL", 600.0),
        ws_ping_timeout=_get_float("GATEWAY_WS_PING_TIMEOUT", 600.0),
    )