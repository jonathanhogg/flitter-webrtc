
import asyncio
import json

import aiohttp
from aiohttp import web
from loguru import logger


class Room:
    def __init__(self, name):
        self.name = name
        self._members = {}

    async def notify_all(self):
        msg = json.dumps({'type': 'members', 'members': list(self._members)})
        await asyncio.gather(*(ws.send_str(msg) for ws in self._members.values()))

    async def add(self, user, ws):
        if user in self._members:
            raise ValueError("User already taken")
        self._members[user] = ws
        logger.info("User '{}' joined room '{}'", user, self.name)
        await self.notify_all()

    async def remove(self, user):
        del self._members[user]
        logger.info("User '{}' left room '{}'", user, self.name)
        await self.notify_all()

    async def send(self, user, msg):
        if user in self._members:
            await self._members[user].send_str(json.dumps(msg))


class SignallingServer:
    def __init__(self):
        self._app = web.Application()
        self._app.add_routes([web.get('/', self.handle_client)])
        self._rooms = {}

    def run(self, **kwargs):
        web.run_app(self._app, **kwargs)

    async def handle_client(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        room = None
        user = None
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    msg = json.loads(msg.data)
                    logger.debug("Received from client: {}", msg)
                    if msg.get('type') == 'join' and (user := msg.get('id')) is not None:
                        room_name = msg.get('room')
                        if room_name not in self._rooms:
                            room = self._rooms[room_name] = Room(room_name)
                        else:
                            room = self._rooms[room_name]
                        await room.add(user, ws)
                    elif user and (to := msg.get('to')) is not None:
                        msg['from'] = user
                        await room.send(to, msg)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"Connection closed with exception: {ws.exception()}")
                    break
        finally:
            if room is not None:
                await room.remove(user)
        return ws
