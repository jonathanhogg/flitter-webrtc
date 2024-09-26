
import asyncio
import aiohttp
import json

from loguru import logger

from . import Signalling


class WebSocket(Signalling):
    def __init__(self):
        self._url = None
        self._call_id = None
        self._answer_id = None
        self._caller_id = None
        self._room = None
        self._run_task = None

    def __str__(self):
        if self._call_id:
            return f"websocket call to '{self._call_id}' at {self._url}"
        elif self._caller_id:
            return f"websocket call from '{self._caller_id}' at {self._url}"
        elif self._answer_id:
            return f"websocket answer to '{self._answer_id}' at {self._url}"
        return "websocket signalling"

    async def release(self):
        if self._run_task is not None:
            self._run_task.cancel()
            await self._run_task
            self._run_task = None

    async def update(self, webrtc, node):
        url = node.get('url', 1, str)
        answer_id = node.get('id', 1, str)
        call_id = node.get('call', 1, str)
        room = node.get('room', 1, str)
        if url != self._url or call_id != self._call_id or answer_id != self._answer_id or room != self._room:
            await webrtc.close_peer_connection()
            if self._run_task is not None:
                if not self._run_task.done():
                    self._run_task.cancel()
                await self._run_task
                self._run_task = None
            self._url = url
            self._call_id = call_id
            self._answer_id = answer_id
            self._room = room
            if self._url and self._answer_id:
                self._run_task = asyncio.create_task(self.run(webrtc))

    async def run(self, webrtc):
        try:
            logger.debug("Started websocket signalling")
            async with aiohttp.ClientSession() as session:
                while True:
                    self._caller_id = None
                    try:
                        async with session.ws_connect(self._url, ssl=False) as ws:
                            msg = {'type': 'join', 'id': self._answer_id}
                            if self._room:
                                msg['room'] = self._room
                            await ws.send_str(json.dumps(msg))
                            await webrtc.create_peer_connection()
                            negotiating = False
                            async for msg in ws:
                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    msg = json.loads(msg.data)
                                    logger.trace("Received: {}", msg)
                                    match msg['type']:
                                        case 'members':
                                            if self._call_id in msg.get('members', ()):
                                                await webrtc.create_offer()
                                                msg = {'type': 'call', 'to': self._call_id, 'offer': webrtc.offer}
                                                await ws.send_str(json.dumps(msg))
                                                logger.trace("Sent: {}", msg)
                                                negotiating = True
                                            elif negotiating:
                                                raise ConnectionAbortedError("Peer disappeared")
                                        case 'call':
                                            self._caller_id = msg['from']
                                            await webrtc.create_answer(msg['offer'])
                                            msg = {'type': 'answer', 'to': msg['from'], 'answer': webrtc.answer}
                                            await ws.send_str(json.dumps(msg))
                                            logger.trace("Sent: {}", msg)
                                            negotiating = True
                                        case 'answer':
                                            await webrtc.finish(msg['answer'])
                                            msg = {'type': 'finished', 'to': msg['from']}
                                            await ws.send_str(json.dumps(msg))
                                            logger.trace("Sent: {}", msg)
                                            break
                                        case 'finished':
                                            break
                                elif msg.type == aiohttp.WSMsgType.ERROR:
                                    raise ws.exception()
                            else:
                                raise ConnectionAbortedError("Server closed socket")
                    except json.JSONDecodeError:
                        logger.error("Message encoding error")
                        await webrtc.close_peer_connection()
                        await asyncio.sleep(1)
                    except ConnectionAbortedError as exc:
                        logger.warning("Connection error: {}", str(exc))
                        await asyncio.sleep(1)
                    except aiohttp.client_exceptions.ClientConnectorError as exc:
                        logger.warning("Connection error: {}", str(exc))
                        await webrtc.close_peer_connection()
                        await asyncio.sleep(5)
                    else:
                        break
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Unexpected error in websocket signalling")
            await webrtc.close_peer_connection()
        finally:
            logger.debug("Stopped websocket signalling")
