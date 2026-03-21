from fastapi import FastAPI, WebSocket
import json
import requests

app = FastAPI()

clients = set()
LEADER_URL = "http://localhost:5001"

last_sent_index = 0


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    global last_sent_index

    await ws.accept()
    clients.add(ws)
    print("Client connected")

    try:
        while True:
            data = json.loads(await ws.receive_text())
            print("Received stroke:", data)

            # Forward stroke to leader
            try:
                requests.post(f"{LEADER_URL}/stroke", json={"stroke": data})
                print("Forwarded to leader")
            except:
                print("Leader not reachable")

            # Get committed strokes
            try:
                response = requests.get(f"{LEADER_URL}/get_strokes")
                strokes = response.json().get("strokes", [])
            except:
                strokes = []

            # Broadcast only new strokes
            new_strokes = strokes[last_sent_index:]
            last_sent_index = len(strokes)

            print("Broadcasting new strokes")

            for stroke in new_strokes:
                for client in clients:
                    try:
                        await client.send_text(json.dumps(stroke))
                    except:
                        pass

    except:
        clients.remove(ws)
        print("Client disconnected")


@app.get("/")
def root():
    return {"message": "Gateway running"}
