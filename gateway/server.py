# from fastapi import FastAPI, WebSocket, WebSocketDisconnect
# import asyncio
# import httpx

# app = FastAPI()

# clients = []

# LEADER_URL = "http://localhost:3001/stroke"  # can change later


# async def forward_to_leader(data: dict):
#     """Fire-and-forget: send stroke to leader without blocking broadcast."""
#     try:
#         async with httpx.AsyncClient() as client:
#             await client.post(LEADER_URL, json=data, timeout=2.0)
#     except Exception:
#         pass  # Leader not up yet — silently ignore


# @app.websocket("/ws")
# async def websocket_endpoint(websocket: WebSocket):
#     await websocket.accept()
#     clients.append(websocket)

#     try:
#         while True:
#             data = await websocket.receive_json()

#             # Broadcast to all clients IMMEDIATELY — don't wait for leader
#             for client in list(clients):
#                 try:
#                     await client.send_json(data)
#                 except Exception:
#                     clients.remove(client)

#             # Forward to leader in the background (non-blocking)
#             asyncio.create_task(forward_to_leader(data))

#     except WebSocketDisconnect:
#         if websocket in clients:
#             clients.remove(websocket)
#         print("Client disconnected")


# @app.get("/")
# def home():
#     return {"status": "Gateway running"}


from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import asyncio
import httpx

app = FastAPI()

clients = []

LEADER_URL = "http://localhost:3001/stroke"  # can change later


async def forward_to_leader(data: dict):
    """Fire-and-forget: send stroke to leader without blocking broadcast."""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(LEADER_URL, json=data, timeout=2.0)
    except Exception:
        pass  # Leader not up yet — silently ignore


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.append(websocket)

    try:
        while True:
            data = await websocket.receive_json()

            # Handle both a single stroke dict and a batched list of strokes
            strokes = data if isinstance(data, list) else [data]

            # Broadcast to all clients IMMEDIATELY — don't wait for leader
            for client in list(clients):
                try:
                    await client.send_json(strokes)
                except Exception:
                    clients.remove(client)

            # Forward each stroke to leader in the background (non-blocking)
            for stroke in strokes:
                asyncio.create_task(forward_to_leader(stroke))

    except WebSocketDisconnect:
        if websocket in clients:
            clients.remove(websocket)
        print("Client disconnected")


@app.get("/")
def home():
    return {"status": "Gateway running"}