from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import contextlib
import json
import requests
import threading
import time
from typing import Any, Optional, Set

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
LEADER_MISS_THRESHOLD = 3


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def find_leader():
    global current_leader, leader_epoch, leader_miss_count
    while True:
        discovered_leader: Optional[str] = None
        leader_candidates: list[tuple[int, int, str]] = []

        for url in REPLICA_URLS:
            try:
                r = requests.get(f"{url}/status", timeout=1.0)
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
                current_leader = discovered_leader
                leader_epoch += 1

        if discovered_leader is None:
            print("[GATEWAY] No leader found, waiting for election...")
        time.sleep(1.0)


threading.Thread(target=find_leader, daemon=True).start()


def get_leader_snapshot() -> tuple[Optional[str], int]:
    with leader_lock:
        return current_leader, leader_epoch


def clear_leader_if_matches(url: str) -> None:
    global current_leader, leader_epoch
    with leader_lock:
        if current_leader == url:
            print(f"[GATEWAY] Clearing unreachable leader: {url}")
            current_leader = None
            leader_epoch += 1


async def _http_get_json(url: str, timeout: float = 1.0) -> dict[str, Any]:
    response = await asyncio.to_thread(requests.get, url, timeout=timeout)
    response.raise_for_status()
    return response.json()


async def _http_post_json(url: str, payload: dict[str, Any], timeout: float = 1.0) -> dict[str, Any]:
    response = await asyncio.to_thread(requests.post, url, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


async def register_client(ws: WebSocket) -> None:
    async with clients_lock:
        clients.add(ws)


async def unregister_client(ws: WebSocket) -> None:
    async with clients_lock:
        clients.discard(ws)


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
            try:
                await client.send_text(payload)
            except Exception:
                dead_clients.append(client)

        if dead_clients:
            async with clients_lock:
                for dead in dead_clients:
                    clients.discard(dead)


async def send_current_snapshot(ws: WebSocket) -> None:
    leader, _ = get_leader_snapshot()
    if leader is None:
        return

    try:
        strokes_response = await _http_get_json(f"{leader}/get_strokes", timeout=1.0)
    except Exception:
        clear_leader_if_matches(leader)
        return

    strokes = strokes_response.get("strokes", [])
    for stroke in strokes:
        await ws.send_text(json.dumps(stroke))


async def forward_stroke_to_leader(stroke: Any) -> bool:
    leader, _ = get_leader_snapshot()
    if leader is None:
        return False

    try:
        result = await _http_post_json(f"{leader}/stroke", {"stroke": stroke}, timeout=1.0)
    except Exception:
        clear_leader_if_matches(leader)
        return False

    if result.get("success") is not True:
        clear_leader_if_matches(leader)
        return False

    return True


async def poll_and_broadcast_committed_strokes() -> None:
    last_seen_epoch = -1
    last_sent_index = 0

    while True:
        leader, epoch = get_leader_snapshot()

        if leader is None:
            await asyncio.sleep(0.3)
            continue

        if epoch != last_seen_epoch:
            last_seen_epoch = epoch
            last_sent_index = 0

        try:
            strokes_response = await _http_get_json(f"{leader}/get_strokes", timeout=1.0)
            strokes = strokes_response.get("strokes", [])
        except Exception:
            clear_leader_if_matches(leader)
            await asyncio.sleep(0.3)
            continue

        if len(strokes) < last_sent_index:
            last_sent_index = 0

        new_strokes = strokes[last_sent_index:]
        if new_strokes:
            print(f"[GATEWAY] Broadcasting {len(new_strokes)} committed stroke(s)")
            await broadcast_strokes(new_strokes)
            last_sent_index = len(strokes)

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
    await register_client(ws)
    await send_current_snapshot(ws)
    print("[GATEWAY] Client connected")

    try:
        while True:
            raw_data = await ws.receive_text()
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({"error": "invalid json"}))
                continue

            print("[GATEWAY] Received stroke:", data)

            stroke_payload = data.get("stroke", data) if isinstance(data, dict) else data
            forwarded = await forward_stroke_to_leader(stroke_payload)
            if not forwarded:
                await ws.send_text(json.dumps({"error": "no leader available"}))

    except WebSocketDisconnect:
        await unregister_client(ws)
        print("[GATEWAY] Client disconnected")
    except Exception as exc:
        await unregister_client(ws)
        print(f"[GATEWAY] Client connection error: {exc}")


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


@app.post("/committed")
async def committed(data: dict[str, Any]):
    stroke = data.get("stroke")
    if stroke is not None:
        print("[GATEWAY] Commit pushed from replica")
        await broadcast_strokes([stroke])
    return {"status": "ok"}