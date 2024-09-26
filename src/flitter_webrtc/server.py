
import asyncio
import json

import aiohttp
from aiohttp import web
from loguru import logger


class Room:
    def __init__(self, name):
        self.name = name
        self._members = {}

    def __contains__(self, user):
        return user in self._members

    async def notify_all(self):
        msg = json.dumps({'type': 'members', 'members': list(self._members)})
        await asyncio.gather(*(ws.send_str(msg) for ws in self._members.values()))

    async def add(self, user, ws):
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

    def get_room(self, name):
        if name not in self._rooms:
            room = self._rooms[name] = Room(name)
        else:
            room = self._rooms[name]
        return room

    async def handle_client(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        room = None
        user = None
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    msg = json.loads(msg.data)
                    logger.trace("Received from client: {}", msg)
                    if room is None:
                        if msg['type'] == 'join':
                            user = msg['id']
                            requested_room = self.get_room(msg['room'])
                            if user not in requested_room:
                                room = requested_room
                                await room.add(user, ws)
                            else:
                                await ws.send_str(json.dumps({'type': 'error', 'error': 'User ID already taken'}))
                                break
                    elif (to := msg.get('to')) is not None:
                        msg['from'] = user
                        await room.send(to, msg)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error("Connection closed with exception: {}", str(ws.exception()))
                    break
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.error("Protocol error: {}", str(exc))
        except Exception:
            logger.exception("Unexpected error")
        finally:
            if room is not None:
                await room.remove(user)
        return ws
