from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import contextlib
import json
import requests
import threading
import time
from typing import Any, Optional, Set
from starlette.websockets import WebSocketState

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

clients: Set[WebSocket] = set()
clients_lock = asyncio.Lock()

REPLICA_URLS = [
    "http://localhost:5001",
    "http://localhost:5002",
    "http://localhost:5003",
]

current_leader: Optional[str] = None
leader_epoch = 0
leader_lock = threading.Lock()
replication_poller_task: Optional[asyncio.Task] = None
leader_miss_count = 0
LEADER_MISS_THRESHOLD = 6
leader_failure_count = 0
LEADER_FAILURE_THRESHOLD = 5

STATUS_TIMEOUT_SECONDS = 2.0
GET_TIMEOUT_SECONDS = 2.5
POST_TIMEOUT_SECONDS = 4.0
HTTP_RETRY_ATTEMPTS = 3
HTTP_RETRY_BACKOFF_SECONDS = 0.25
WS_KEEPALIVE_INTERVAL_SECONDS = 15.0
WS_KEEPALIVE_PAYLOAD = json.dumps({"type": "ping"})

# Bonus: observability globals
leader_history: list[dict[str, Any]] = []
stroke_count = 0
gateway_start_time = time.time()


def _stroke_log_fields(stroke: Any) -> str:
    if not isinstance(stroke, dict):
        return f"payload={stroke}"

    return (
        f"type={stroke.get('type')} "
        f"x={stroke.get('x')} y={stroke.get('y')} "
        f"x0={stroke.get('x0')} y0={stroke.get('y0')} "
        f"color={stroke.get('color')} size={stroke.get('size')} "
        f"erase={stroke.get('erase')}"
    )


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def find_leader():
    global current_leader, leader_epoch, leader_miss_count, leader_failure_count
    while True:
        discovered_leader: Optional[str] = None
        leader_candidates: list[tuple[int, int, str]] = []

        for url in REPLICA_URLS:
            try:
                r = requests.get(f"{url}/status", timeout=STATUS_TIMEOUT_SECONDS)
                data = r.json()
                is_leader = (
                    data.get("state") == "leader" or
                    data.get("role") == "leader"
                )
                if is_leader:
                    term = _to_int(data.get("term"), -1)
                    node_id = _to_int(data.get("id"), 10**9)
                    leader_candidates.append((term, -node_id, url))
            except Exception:
                pass

        if leader_candidates:
            # Prefer highest term; on ties pick the lowest node id deterministically.
            leader_candidates.sort(reverse=True)
            discovered_leader = leader_candidates[0][2]
            leader_miss_count = 0
        else:
            leader_miss_count += 1
            if leader_miss_count < LEADER_MISS_THRESHOLD:
                time.sleep(1.0)
                continue

        with leader_lock:
            if discovered_leader != current_leader:
                print(f"[GATEWAY] Leader changed: {current_leader} -> {discovered_leader}")
                leader_history.append(
                    {
                        "from": current_leader,
                        "to": discovered_leader,
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )
                current_leader = discovered_leader
                leader_epoch += 1
                leader_failure_count = 0
            elif discovered_leader is not None:
                # Any healthy status response for the current leader clears transient failure debt.
                leader_failure_count = 0

        if discovered_leader is None:
            print("[GATEWAY] No leader found, waiting for election...")
        time.sleep(1.0)


threading.Thread(target=find_leader, daemon=True).start()


def get_leader_snapshot() -> tuple[Optional[str], int]:
    with leader_lock:
        return current_leader, leader_epoch


def mark_leader_failure(url: str, *, hard: bool = False) -> None:
    global current_leader, leader_epoch, leader_failure_count
    with leader_lock:
        if current_leader != url:
            return

        increment = LEADER_FAILURE_THRESHOLD if hard else 1
        leader_failure_count += increment

        if leader_failure_count < LEADER_FAILURE_THRESHOLD:
            return

        print(f"[GATEWAY] Clearing unstable leader after failures: {url}")
        current_leader = None
        leader_epoch += 1
        leader_failure_count = 0


def mark_leader_success(url: str) -> None:
    global leader_failure_count
    with leader_lock:
        if current_leader == url:
            leader_failure_count = 0


async def _http_get_json(url: str, timeout: float = GET_TIMEOUT_SECONDS) -> dict[str, Any]:
    last_exception: Optional[Exception] = None
    for attempt in range(1, HTTP_RETRY_ATTEMPTS + 1):
        try:
            response = await asyncio.to_thread(requests.get, url, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_exception = exc
            if attempt < HTTP_RETRY_ATTEMPTS:
                await asyncio.sleep(HTTP_RETRY_BACKOFF_SECONDS * attempt)
    if last_exception is not None:
        raise last_exception
    raise RuntimeError("GET request failed without exception")


async def _http_post_json(url: str, payload: dict[str, Any], timeout: float = POST_TIMEOUT_SECONDS) -> dict[str, Any]:
    last_exception: Optional[Exception] = None
    for attempt in range(1, HTTP_RETRY_ATTEMPTS + 1):
        try:
            response = await asyncio.to_thread(requests.post, url, json=payload, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_exception = exc
            if attempt < HTTP_RETRY_ATTEMPTS:
                await asyncio.sleep(HTTP_RETRY_BACKOFF_SECONDS * attempt)
    if last_exception is not None:
        raise last_exception
    raise RuntimeError("POST request failed without exception")


async def _websocket_keepalive_loop(ws: WebSocket) -> None:
    while True:
        await asyncio.sleep(WS_KEEPALIVE_INTERVAL_SECONDS)
        sent = await _safe_send_text(ws, WS_KEEPALIVE_PAYLOAD)
        if not sent:
            return


async def register_client(ws: WebSocket) -> None:
    async with clients_lock:
        clients.add(ws)


async def unregister_client(ws: WebSocket) -> None:
    async with clients_lock:
        clients.discard(ws)


def _is_ws_connected(ws: WebSocket) -> bool:
    return (
        ws.client_state == WebSocketState.CONNECTED and
        ws.application_state == WebSocketState.CONNECTED
    )


async def _safe_send_text(ws: WebSocket, payload: str) -> bool:
    if not _is_ws_connected(ws):
        return False
    try:
        await ws.send_text(payload)
        return True
    except Exception:
        return False


async def broadcast_strokes(strokes: list[Any]) -> None:
    if not strokes:
        return

    async with clients_lock:
        client_list = list(clients)

    if not client_list:
        return

    for stroke in strokes:
        payload = json.dumps(stroke)
        dead_clients: list[WebSocket] = []
        for client in client_list:
            if not await _safe_send_text(client, payload):
                dead_clients.append(client)

        if dead_clients:
            async with clients_lock:
                for dead in dead_clients:
                    clients.discard(dead)
            client_list = [client for client in client_list if client not in dead_clients]


async def send_current_snapshot(ws: WebSocket) -> None:
    # Wait up to 3 seconds for a leader to be elected
    leader, _ = get_leader_snapshot()
    if leader is None:
        print("[GATEWAY] No leader available, waiting for election...")
        for attempt in range(30):  # 30 * 0.1 = 3 seconds
            await asyncio.sleep(0.1)
            leader, _ = get_leader_snapshot()
            if leader is not None:
                print(f"[GATEWAY] Leader elected at attempt {attempt + 1}: {leader}")
                break
        if leader is None:
            print("[GATEWAY] Timeout waiting for leader, sending empty snapshot")
            # Send empty snapshot so client is at least ready
            await _safe_send_text(ws, json.dumps({"type": "snapshot-reset"}))
            return
    try:
        strokes_response = await _http_get_json(f"{leader}/get_strokes", timeout=GET_TIMEOUT_SECONDS)
    except Exception as e:
        print(f"[GATEWAY] Failed to get strokes from leader: {e}")
        mark_leader_failure(leader)
        return

    mark_leader_success(leader)

    strokes = strokes_response.get("strokes", [])
    payload = {
        "type": "snapshot",
        "strokes": strokes,
    }

    sent = await _safe_send_text(ws, json.dumps(payload))
    if not sent:
        return

    print(f"[GATEWAY] Snapshot sent to new client ({len(strokes)} strokes)")


async def forward_stroke_to_leader(stroke: Any) -> bool:
    global stroke_count
    leader, _ = get_leader_snapshot()
    if leader is None:
        return False

    try:
        result = await _http_post_json(f"{leader}/stroke", {"stroke": stroke}, timeout=POST_TIMEOUT_SECONDS)
    except Exception:
        mark_leader_failure(leader)
        return False

    if result.get("success") is not True:
        mark_leader_failure(leader, hard=(result.get("error") == "not leader"))
        return False

    mark_leader_success(leader)
    stroke_count += 1
    return True


def _normalize_incoming_strokes(data: Any) -> list[Any]:
    items = data if isinstance(data, list) else [data]
    normalized: list[Any] = []

    for item in items:
        payload = item.get("stroke", item) if isinstance(item, dict) else item
        if payload is None:
            continue

        if isinstance(payload, list):
            for inner in payload:
                if inner is not None:
                    normalized.append(inner)
        else:
            normalized.append(payload)

    return normalized


async def poll_and_broadcast_committed_strokes() -> None:
    last_seen_epoch = -1
    last_sent_index = 0
    last_sent_index_by_leader: dict[str, int] = {}

    while True:
        leader, epoch = get_leader_snapshot()

        if leader is None:
            await asyncio.sleep(0.3)
            continue

        if epoch != last_seen_epoch:
            last_seen_epoch = epoch
            last_sent_index = last_sent_index_by_leader.get(leader, 0)

        try:
            strokes_response = await _http_get_json(f"{leader}/get_strokes", timeout=GET_TIMEOUT_SECONDS)
            strokes = strokes_response.get("strokes", [])
        except Exception:
            mark_leader_failure(leader)
            await asyncio.sleep(0.3)
            continue

        mark_leader_success(leader)

        if leader not in last_sent_index_by_leader:
            # On first observation of a leader, treat existing committed strokes as baseline.
            # New clients already receive a snapshot via send_current_snapshot().
            last_sent_index = len(strokes)
            last_sent_index_by_leader[leader] = last_sent_index
            await asyncio.sleep(0.2)
            continue

# ----------------------------------------------------------------
# editing for bonus - shreya
#  incase of undo, incremental updates are invalid ; force canvas reset, replay curr state 
#  clients consistent with committed log.
        # if len(strokes) < last_sent_index:
        #     last_sent_index = 0
        if len(strokes) < last_sent_index:
            await broadcast_strokes([{"type": "snapshot-reset"}])
            await broadcast_strokes(strokes)
            last_sent_index = len(strokes)
            last_sent_index_by_leader[leader] = last_sent_index
            await asyncio.sleep(0.2)
            continue
# ----------------------------------------------------------------

        new_strokes = strokes[last_sent_index:]
        if new_strokes:
            print(f"[GATEWAY] Broadcasting {len(new_strokes)} committed stroke(s)")
            for index, stroke in enumerate(new_strokes, start=1):
                print(f"[GATEWAY] committed[{index}/{len(new_strokes)}] {_stroke_log_fields(stroke)}")
            await broadcast_strokes(new_strokes)
            last_sent_index = len(strokes)
            last_sent_index_by_leader[leader] = last_sent_index
        else:
            last_sent_index_by_leader[leader] = len(strokes)

        await asyncio.sleep(0.2)


@app.on_event("startup")
async def on_startup() -> None:
    global replication_poller_task
    if replication_poller_task is None or replication_poller_task.done():
        replication_poller_task = asyncio.create_task(poll_and_broadcast_committed_strokes())


@app.on_event("shutdown")
async def on_shutdown() -> None:
    global replication_poller_task
    if replication_poller_task is not None:
        replication_poller_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await replication_poller_task
        replication_poller_task = None


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    
    # Send snapshot BEFORE registering for live broadcasts
    await send_current_snapshot(ws)
    if not _is_ws_connected(ws):
        return

    # NOW register for live updates after snapshot is complete
    await register_client(ws)
    print("[GATEWAY] Client registered and ready for live updates")
    keepalive_task = asyncio.create_task(_websocket_keepalive_loop(ws))

    try:
        while True:
            raw_data = await ws.receive_text()
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                sent = await _safe_send_text(ws, json.dumps({"error": "invalid json"}))
                if not sent:
                    break
                continue

            print("[GATEWAY] Received stroke:", data)

            if isinstance(data, dict) and data.get("type") in {"ping", "pong", "keepalive"}:
                if data.get("type") == "ping":
                    sent = await _safe_send_text(ws, json.dumps({"type": "pong"}))
                    if not sent:
                        break
                continue

            stroke_payloads = _normalize_incoming_strokes(data)
            if not stroke_payloads:
                sent = await _safe_send_text(ws, json.dumps({"error": "empty payload"}))
                if not sent:
                    break
                continue

            forwarded = True
            for stroke_payload in stroke_payloads:
                if not await forward_stroke_to_leader(stroke_payload):
                    forwarded = False
                    break

            if not forwarded:
                sent = await _safe_send_text(ws, json.dumps({"error": "no leader available"}))
                if not sent:
                    break

    except WebSocketDisconnect:
        print("[GATEWAY] Client disconnected")
    except RuntimeError as exc:
        # Starlette may raise a RuntimeError during close races.
        if "not connected" in str(exc).lower() or "accept" in str(exc).lower():
            print("[GATEWAY] Client disconnected")
        else:
            print(f"[GATEWAY] Client connection error: {exc}")
    except Exception as exc:
        print(f"[GATEWAY] Client connection error: {exc}")
    finally:
        keepalive_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await keepalive_task
        await unregister_client(ws)


@app.get("/")
def root():
    leader, _ = get_leader_snapshot()
    return {"message": "Gateway running", "leader": leader}


@app.get("/health")
def health():
    leader, _ = get_leader_snapshot()
    return {
        "status": "ok",
        "leader": leader,
        "connected_clients": len(clients),
        "clients": len(clients)
    }


@app.get("/leader")
def leader():
    current, epoch = get_leader_snapshot()
    return {"leader": current, "epoch": epoch}


@app.get("/stats")
def stats():
    leader, epoch = get_leader_snapshot()
    return {
        "uptime_seconds": round(time.time() - gateway_start_time),
        "leader": leader,
        "leader_epoch": epoch,
        "connected_clients": len(clients),
        "total_strokes_forwarded": stroke_count,
        "replica_urls": REPLICA_URLS,
        "total_leader_changes": len(leader_history),
    }


@app.get("/history")
def history():
    return {"leader_changes": leader_history}


@app.post("/committed")
async def committed(data: dict[str, Any]):
    stroke = data.get("stroke")
    if stroke is not None:
        print(f"[GATEWAY] Commit pushed from replica {_stroke_log_fields(stroke)}")
        await broadcast_strokes([stroke])
    return {"status": "ok"}
