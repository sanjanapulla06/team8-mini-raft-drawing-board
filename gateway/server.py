from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import json
import requests
import threading
import time

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

clients = set()

REPLICA_URLS = [
    "http://localhost:5001",
    "http://localhost:5002",
    "http://localhost:5003",
]

current_leader = None


def find_leader():
    global current_leader
    while True:
        found = False
        for url in REPLICA_URLS:
            try:
                r = requests.get(f"{url}/status", timeout=1.0)
                data = r.json()
                if data.get("state") == "leader":
                    if current_leader != url:
                        print(f"[GATEWAY] ⚡ Leader changed: {current_leader} → {url}")
                        current_leader = url
                    found = True
                    break
            except:
                pass
        if not found:
            print("[GATEWAY] No leader found, waiting for election...")
            current_leader = None
        time.sleep(1.0)


threading.Thread(target=find_leader, daemon=True).start()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    last_sent_index = 0
    print("[GATEWAY] Client connected")

    try:
        while True:
            data = json.loads(await ws.receive_text())
            print("[GATEWAY] Received stroke:", data)

            if current_leader is None:
                print("[GATEWAY] No leader available, skipping...")
                continue

            # Forward stroke to current leader
            try:
                requests.post(
                    f"{current_leader}/stroke",
                    json={"stroke": data},
                    timeout=1.0
                )
                print(f"[GATEWAY] Forwarded to leader {current_leader}")
            except:
                print("[GATEWAY] Leader not reachable, waiting for re-election...")
                continue

            # Get committed strokes from leader
            try:
                response = requests.get(
                    f"{current_leader}/get_strokes",
                    timeout=1.0
                )
                strokes = response.json().get("strokes", [])
            except:
                strokes = []

            # Broadcast only new strokes
            new_strokes = strokes[last_sent_index:]
            last_sent_index = len(strokes)

            print(f"[GATEWAY] Broadcasting {len(new_strokes)} new stroke(s)")

            for stroke in new_strokes:
                for client in list(clients):
                    try:
                        await client.send_text(json.dumps(stroke))
                    except:
                        clients.discard(client)

    except WebSocketDisconnect:
        clients.discard(ws)
        print("[GATEWAY] Client disconnected")


@app.get("/")
def root():
    return {"message": "Gateway running", "leader": current_leader}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "leader": current_leader,
        "connected_clients": len(clients)
    }


@app.get("/leader")
def leader():
    return {"leader": current_leader}