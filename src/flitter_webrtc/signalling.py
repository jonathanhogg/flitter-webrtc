
import asyncio
import hashlib
import json
import socket
import zlib

import aiortc
from loguru import logger


class Signalling:
    async def release(self):
        raise NotImplementedError()

    async def update(self, node):
        raise NotImplementedError()


def message_digest(auth, message):
    hash = hashlib.sha256()
    hash.update(auth.encode('utf8'))
    for key in sorted(message.keys()):
        if key != 'digest':
            hash.update(key.encode('utf8'))
            hash.update(str(message[key]).encode('utf8'))
    return hash.hexdigest()


class Socket(Signalling):
    BUFSIZE = 4096

    def __init__(self):
        self._port = None
        self._host = None
        self._my_id = None
        self._call_id = None
        self._auth = None
        self._run_task = None

    async def release(self):
        if self._run_task is not None:
            self._run_task.cancel()
            await self._run_task
            self._run_task = None

    async def update(self, webrtc, node):
        port = node.get('port', 1, int)
        host = node.get('host', 1, str)
        my_id = node.get('id', 1, str)
        call_id = node.get('call', 1, str)
        auth = node.get('auth', 1, str)
        if port != self._port or host != self._host or my_id != self._my_id or call_id != self._call_id or auth != self._auth:
            await webrtc.close_peer_connection()
            if self._run_task is not None:
                if not self._run_task.done():
                    self._run_task.cancel()
                await self._run_task
                self._run_task = None
            self._port = port
            self._host = host
            self._my_id = my_id
            self._call_id = call_id
            self._auth = auth
            if self._my_id is not None and self._port is not None:
                self._run_task = asyncio.create_task(self.run(webrtc))

    async def run(self, webrtc):
        logger.debug("Using socket signalling on {}:{}", self._host, self._port)
        try:
            loop = asyncio.get_event_loop()
            while True:
                pc = await webrtc.create_peer_connection()
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setblocking(False)
                if self._call_id is None:
                    if self._host:
                        address = self._host, self._port
                    else:
                        address = '', self._port
                else:
                    address = '', 0
                try:
                    sock.bind(address)
                except (OSError, OverflowError):
                    logger.error("Unable to bind to {}:{}", host, port)
                if self._call_id and not self._host:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                    send_address = '<broadcast>', self._port
                else:
                    send_address = self._host, self._port
                if self._call_id is not None:
                    await pc.setLocalDescription(await pc.createOffer())
                    state = 'offer'
                else:
                    state = 'wait'
                retries = 5
                peer_id = self._call_id
                while pc.connectionState in {'new', 'connecting'}:
                    message = None
                    if state == 'offer':
                        message = {'offer': pc.localDescription.sdp}
                    elif state == 'answer':
                        message = {'answer': pc.localDescription.sdp}
                    if message is not None:
                        if retries == 0:
                            logger.debug("Too many retries; reset signalling")
                            break
                        logger.debug("Send: {}", message)
                        message['from'] = self._my_id
                        message['to'] = peer_id
                        if self._auth:
                            message['digest'] = message_digest(self._auth, message)
                        data = zlib.compress(json.dumps(message).encode('utf8'))
                        await loop.sock_sendto(sock, data, send_address)
                        retries -= 1
                    while True:
                        try:
                            message, address = await asyncio.wait_for(loop.sock_recvfrom(sock, self.BUFSIZE), 5)
                            message = json.loads(zlib.decompress(message).decode('utf8'))
                            if self._auth and (digest := message_digest(self._auth, message)) != message.pop('digest', None):
                                logger.warning("Rejecting message with auth mismatch")
                                continue
                            if message.pop('to', None) != self._my_id:
                                logger.warning("Rejecting message with id mismatch")
                                continue
                            logger.debug("Received: {}", message)
                            if state == 'wait':
                                if (offer := message.get('offer')) is not None:
                                    await pc.setRemoteDescription(aiortc.RTCSessionDescription(type='offer', sdp=offer))
                                    await pc.setLocalDescription(await pc.createAnswer())
                                    state = 'answer'
                                    peer_id = message['from']
                                    send_address = address
                                    retries = 5
                                    break
                            elif state == 'offer':
                                if (answer := message.get('answer')) is not None:
                                    await pc.setRemoteDescription(aiortc.RTCSessionDescription(type='answer', sdp=answer))
                                    state = 'done'
                                    break
                        except (zlib.error, UnicodeDecodeError, json.JSONDecodeError):
                            pass
                        except asyncio.TimeoutError:
                            break
                sock.close()
                if pc.connectionState == 'connected':
                    break
                await webrtc.close_peer_connection()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Unexpected error in WebRTC broadcast signalling")
            await webrtc.close_peer_connection()
        logger.debug("Stopped socket signalling")
