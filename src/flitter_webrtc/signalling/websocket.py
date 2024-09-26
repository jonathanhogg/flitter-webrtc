
import asyncio
import aiohttp
import json

from loguru import logger

from . import Signalling


class WebSocket(Signalling):
    def __init__(self):
        self._url = None
        self._verify = True
        self._call_id = None
        self._answer_id = None
        self._peer_id = None
        self._room = None
        self._run_task = None

    def __str__(self):
        if self._peer_id:
            return f"websocket signalling with '{self._peer_id}' at {self._url}"
        return "websocket signalling"

    async def release(self):
        if self._run_task is not None:
            self._run_task.cancel()
            await self._run_task
            self._run_task = None

    async def update(self, webrtc, node):
        url = node.get('url', 1, str)
        verify = node.get('verify', 1, bool, True)
        answer_id = node.get('id', 1, str)
        call_id = node.get('call', 1, str)
        room = node.get('room', 1, str)
        if url != self._url or verify != self._verify or call_id != self._call_id or answer_id != self._answer_id or room != self._room:
            await webrtc.close_peer_connection()
            if self._run_task is not None:
                if not self._run_task.done():
                    self._run_task.cancel()
                await self._run_task
                self._run_task = None
            self._url = url
            self._verify = verify
            self._call_id = call_id
            self._answer_id = answer_id
            self._room = room
            if self._url and self._room and self._answer_id:
                self._run_task = asyncio.create_task(self.run(webrtc))

    async def run(self, webrtc):
        try:
            logger.debug("Started websocket signalling")
            self._peer_id = None
            async with aiohttp.ClientSession() as session:
                while True:
                    try:
                        async with session.ws_connect(self._url, ssl=self._verify) as ws:
                            logger.debug("Connection made to {}", self._url)
                            msg = {'type': 'join', 'id': self._answer_id}
                            if self._room:
                                msg['room'] = self._room
                            await ws.send_str(json.dumps(msg))
                            await webrtc.create_peer_connection()
                            state = 'make_call' if self._call_id else 'wait_call'
                            async for msg in ws:
                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    msg = json.loads(msg.data)
                                    logger.trace("Received: {}", msg)
                                    match (msg['type'], state):
                                        case ('error', _):
                                            raise ConnectionError(msg['error'])
                                        case ('members', 'make_call') if self._call_id in msg['members']:
                                            self._peer_id = self._call_id
                                            logger.debug("Sending offer to peer '{}'", self._peer_id)
                                            await webrtc.create_offer()
                                            msg = {'type': 'call', 'to': self._peer_id, 'offer': webrtc.offer}
                                            await ws.send_str(json.dumps(msg))
                                            logger.trace("Sent: {}", msg)
                                            state = 'wait_answer'
                                        case ('members', _) if self._peer_id and self._peer_id not in msg['members']:
                                            raise ConnectionError(f"Peer '{self._peer_id}' disappeared")
                                        case ('call', 'make_call') | ('call', 'wait_call'):
                                            self._peer_id = msg['from']
                                            logger.debug("Sending answer to peer '{}'", self._peer_id)
                                            await webrtc.create_answer(msg['offer'])
                                            msg = {'type': 'answer', 'to': self._peer_id, 'answer': webrtc.answer}
                                            await ws.send_str(json.dumps(msg))
                                            logger.trace("Sent: {}", msg)
                                            state = 'wait_finished'
                                        case ('answer', 'wait_answer') if msg['from'] == self._peer_id:
                                            await webrtc.finish(msg['answer'])
                                            msg = {'type': 'finished', 'to': self._peer_id}
                                            await ws.send_str(json.dumps(msg))
                                            logger.trace("Sent: {}", msg)
                                            break
                                        case ('finished', 'wait_finished') if msg['from'] == self._peer_id:
                                            break
                                elif msg.type == aiohttp.WSMsgType.ERROR:
                                    raise ws.exception()
                            else:
                                raise ConnectionError("Server closed socket")
                    except (KeyError, json.JSONDecodeError):
                        logger.error("Message encoding error")
                        await webrtc.close_peer_connection()
                        self._peer_id = None
                        await asyncio.sleep(1)
                    except (ConnectionError, aiohttp.client_exceptions.ClientConnectorError, aiohttp.client_exceptions.ServerDisconnectedError) as exc:
                        logger.error("Connection error: {}", str(exc))
                        await webrtc.close_peer_connection()
                        self._peer_id = None
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
