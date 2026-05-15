"""WebSocket endpoint for real-time updates.

Channels:
- job_status: pipeline job progress updates
- kill_switch: kill switch status changes
- predictions: new weekly predictions available
"""

from __future__ import annotations

import asyncio
import json
from typing import Dict, Set

from fastapi import WebSocket, WebSocketDisconnect


class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, message: dict) -> None:
        """Send a message to all connected clients."""
        disconnected: list[WebSocket] = []
        payload = json.dumps(message)
        async with self._lock:
            connections = list(self._connections)
        for conn in connections:
            try:
                await conn.send_text(payload)
            except Exception:
                disconnected.append(conn)
        if disconnected:
            async with self._lock:
                for conn in disconnected:
                    self._connections.discard(conn)

    async def send_personal(self, websocket: WebSocket, message: dict) -> None:
        """Send a message to a specific client."""
        try:
            await websocket.send_text(json.dumps(message))
        except Exception:
            await self.disconnect(websocket)


manager = ConnectionManager()


async def websocket_endpoint(websocket: WebSocket) -> None:
    """Main WebSocket handler."""
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                action = msg.get("action")
                if action == "ping":
                    await manager.send_personal(websocket, {"type": "pong"})
                elif action == "subscribe":
                    channel = msg.get("channel", "all")
                    await manager.send_personal(
                        websocket,
                        {"type": "subscribed", "channel": channel},
                    )
            except json.JSONDecodeError:
                await manager.send_personal(
                    websocket,
                    {"type": "error", "message": "Invalid JSON"},
                )
    except WebSocketDisconnect:
        await manager.disconnect(websocket)


# Helper functions for broadcasting events from other parts of the app

async def broadcast_job_status(job_id: int, job_name: str, status: str, metadata: dict | None = None) -> None:
    """Broadcast a job status update."""
    await manager.broadcast({
        "type": "job_status",
        "job_id": job_id,
        "job_name": job_name,
        "status": status,
        "metadata": metadata or {},
    })


async def broadcast_kill_switch(active: bool, warnings: list[dict]) -> None:
    """Broadcast kill switch status change."""
    await manager.broadcast({
        "type": "kill_switch",
        "active": active,
        "warnings": warnings,
    })


async def broadcast_predictions(week_starting: str, count: int) -> None:
    """Broadcast new predictions available."""
    await manager.broadcast({
        "type": "predictions",
        "week_starting": week_starting,
        "count": count,
    })
