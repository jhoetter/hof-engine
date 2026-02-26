"""WebSocket endpoint for real-time updates."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


class ConnectionManager:
    """Manages active WebSocket connections for real-time updates."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send a message to all connected clients."""
        data = json.dumps(message, default=str)
        for connection in self.active_connections:
            try:
                await connection.send_text(data)
            except Exception:
                pass


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time flow execution updates."""
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def notify_execution_update(execution_id: str, status: str, **extra: Any) -> None:
    """Broadcast an execution status update to all connected clients."""
    await manager.broadcast({
        "type": "execution_update",
        "execution_id": execution_id,
        "status": status,
        **extra,
    })


async def notify_node_update(
    execution_id: str, node_name: str, status: str, **extra: Any
) -> None:
    """Broadcast a node status update."""
    await manager.broadcast({
        "type": "node_update",
        "execution_id": execution_id,
        "node_name": node_name,
        "status": status,
        **extra,
    })
