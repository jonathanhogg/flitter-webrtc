
import asyncio
import json
import socket
import zlib

from loguru import logger

from . import Signalling
from .cipher import Cipher, DecryptionError


class Broadcast(Signalling):
    DEFAULT_PORT = 5111
    DEFAULT_SECRET = 'flitter_webrtc'
    BUFSIZE = 1500
    WAIT = 5

    def __init__(self):
        self._port = None
        self._host = None
        self._call_id = None
        self._answer_id = None
        self._secret = None
        self._run_task = None

    def __str__(self):
        if self._call_id:
            return f"broadcast call to '{self._call_id}' at :{self._port}"
        elif self._answer_id:
            return f"broadcast answer to '{self._answer_id}' at :{self._port}"
        return "broadcast signalling"

    async def release(self):
        if self._run_task is not None:
            self._run_task.cancel()
            await self._run_task
            self._run_task = None

    async def update(self, webrtc, node):
        port = node.get('port', 1, int, self.DEFAULT_PORT)
        host = node.get('host', 1, str, '')
        call_id = node.get('call', 1, str)
        answer_id = node.get('answer', 1, str)
        secret = node.get('secret', 1, str, self.DEFAULT_SECRET)
        if port != self._port or host != self._host or call_id != self._call_id or answer_id != self._answer_id or secret != self._secret:
            await webrtc.close_peer_connection()
            if self._run_task is not None:
                if not self._run_task.done():
                    self._run_task.cancel()
                await self._run_task
                self._run_task = None
            self._port = port
            self._host = host
            self._call_id = call_id
            self._answer_id = answer_id
            self._secret = secret
            if self._call_id or self._answer_id:
                self._run_task = asyncio.create_task(self.run(webrtc))

    async def run(self, webrtc):
        try:
            logger.debug("Started broadcast signalling")
            loop = asyncio.get_event_loop()
            cipher = Cipher(self._secret, self._call_id or self._answer_id)
            while True:
                await webrtc.create_peer_connection()
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setblocking(False)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    if self._call_id:
                        sock.bind((self._host, 0))
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                        send_address = ('<broadcast>', self._port)
                    else:
                        sock.bind((self._host, self._port))
                except (OSError, OverflowError):
                    logger.error("Unable to bind socket")
                logger.trace("Using UDP socket on {}:{}", *sock.getsockname())
                if self._call_id:
                    await webrtc.create_offer()
                    state = 'offer'
                else:
                    state = 'wait'
                retries = 5
                while webrtc.connection_state in ('new', 'connecting'):
                    message = None
                    if state == 'offer':
                        message = {'offer': webrtc.offer}
                    elif state == 'answer':
                        message = {'answer': webrtc.answer}
                    if message is not None:
                        if retries == 0:
                            logger.debug("Too many retries; reset signalling")
                            break
                        logger.trace("Send: {}", message)
                        data = cipher.encrypt(zlib.compress(json.dumps(message).encode('utf8'), 9))
                        await loop.sock_sendto(sock, data, send_address)
                        retries -= 1
                    while True:
                        try:
                            data, address = await asyncio.wait_for(loop.sock_recvfrom(sock, self.BUFSIZE), self.WAIT)
                            message = json.loads(zlib.decompress(cipher.decrypt(data, ttl=self.WAIT*2)).decode('utf8'))
                            logger.trace("Received: {}", message)
                            if state == 'wait' and (offer := message.get('offer')) is not None:
                                await webrtc.create_answer(offer)
                                state = 'answer'
                                send_address = address
                                retries = 5
                                break
                            elif state == 'offer' and (answer := message.get('answer')) is not None:
                                await webrtc.finish(answer)
                                state = 'done'
                                break
                            else:
                                logger.debug("Ignoring unexpected message")
                        except (zlib.error, UnicodeDecodeError, json.JSONDecodeError):
                            logger.warning("Ignoring badly encoded message")
                        except DecryptionError:
                            logger.warning("Ignoring incorrectly encrypted message (may not be intended for us)")
                        except asyncio.TimeoutError:
                            break
                sock.close()
                if webrtc.connection_state == 'connected':
                    break
                await webrtc.close_peer_connection()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Unexpected error in broadcast signalling")
            await webrtc.close_peer_connection()
        finally:
            logger.debug("Stopped broadcast signalling")
