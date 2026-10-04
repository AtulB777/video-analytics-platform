"""Print the WebSocket feed:  python scripts/ws_client.py [ws://localhost:8000/ws] [type ...]"""
import asyncio
import json
import sys

import websockets


async def main(url: str, types: set[str]) -> None:
    async with websockets.connect(url) as ws:
        async for raw in ws:
            msg = json.loads(raw)
            if not types or msg.get("type") in types:
                print(json.dumps(msg)[:300])


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:8000/ws"
    asyncio.run(main(url, set(sys.argv[2:])))
