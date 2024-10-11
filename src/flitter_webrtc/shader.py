"""
Flitter WebRTC Plugin
"""

import asyncio

import aiortc
import array
from av.video.reformatter import VideoReformatter
from loguru import logger
import moderngl

from flitter.model import Vector, null
from flitter.plugins import get_plugin
from flitter.render.window import ProgramNode
from flitter.render.window.glconstants import GL_FRAMEBUFFER_SRGB
from flitter.render.window.target import RenderTarget


Reformatter = VideoReformatter()


class VideoConverter:
    VERTEX_SOURCE = """
in vec2 position;
out vec2 coord;

void main() {
    gl_Position = vec4(position.x, -position.y, 0.0, 1.0);
    coord = (position + 1.0) / 2.0;
}
    """

    FRAGMENT_SOURCE = """
in vec2 coord;
out vec4 color;

uniform sampler2D y;
uniform sampler2D u;
uniform sampler2D v;

const vec3 offset = vec3(0.0627451, 0.5, 0.5);
const float scale = 1.138393;
const mat3 srgb = mat3(1.0, 1.0, 1.0, 0.0, -0.21482, 2.12798, 1.28033, -0.38059, 0.0);

void main() {
    vec3 yuv = vec3(texture(y, coord).r, texture(u, coord).r, texture(v, coord).r);
    color = vec4(srgb * ((yuv - offset) * scale), 1.0);
}
"""

    def __init__(self, glctx):
        self.glctx = glctx
        self.y = self.u = self.v = None
        header = self.glctx.extra['HEADER']
        self.program = self.glctx.program(vertex_shader=header + self.VERTEX_SOURCE, fragment_shader=header + self.FRAGMENT_SOURCE)
        vertices = self.glctx.buffer(array.array('f', [-1, 1, -1, -1, 1, 1, 1, -1]))
        self.rectangle = self.glctx.vertex_array(self.program, [(vertices, '2f', 'position')], mode=moderngl.TRIANGLE_STRIP)

    def convert(self, frame, target):
        assert frame.format.name == 'yuv420p'
        if self.y is None:
            width, height = frame.width, frame.height
            self.y = self.glctx.texture((width, height), 1)
            self.u = self.glctx.texture((width // 2, height // 2), 1)
            self.v = self.glctx.texture((width // 2, height // 2), 1)
        data = frame.to_ndarray().data
        n = len(data)
        self.y.write(data[:n * 2 // 3])
        self.u.write(data[n * 2 // 3:n * 5 // 6])
        self.v.write(data[n * 5 // 6:])
        self.y.use(1)
        self.program['y'] = 1
        self.u.use(2)
        self.program['u'] = 2
        self.v.use(3)
        self.program['v'] = 3
        with target:
            self.glctx.disable_direct(GL_FRAMEBUFFER_SRGB)
            target.clear()
            self.rectangle.render()


class RenderTrack(aiortc.VideoStreamTrack):
    def __init__(self, webrtc):
        super().__init__()
        self.webrtc = webrtc

    async def recv(self):
        while True:
            pts, time_base = await self.next_timestamp()
            if self.webrtc._target is not None and (frame := self.webrtc._target.video_frame) is not None:
                break
        frame.pts = pts
        frame.time_base = time_base
        return frame


class WebRTC(ProgramNode):
    def __init__(self, glctx):
        super().__init__(glctx)
        self._signalling = None
        self._peer_connection = None
        self._remote_track_task = None
        self._remote_frame = None
        self._remote_target = None

    @property
    def framebuffer(self):
        target = self._remote_target or self._target
        return target.framebuffer if target is not None else None

    @property
    def texture(self):
        target = self._remote_target or self._target
        return target.texture if target is not None else None

    @property
    def array(self):
        target = self._remote_target or self._target
        return target.array if target is not None else None

    async def reset_connection(self):
        if self._signalling is not None:
            await self._signalling.release()
            self._signalling = None
        await self.close_peer_connection()

    async def release(self):
        await self.reset_connection()
        super().release()

    async def create(self, engine, node, resized, **kwargs):
        self._signalling_class_node = None, None
        if resized:
            await self.reset_connection()
        if 'state' in node:
            if self._peer_connection is not None:
                engine.state[node['state']] = Vector.symbol(self._peer_connection.connectionState)
            else:
                engine.state[node['state']] = null

    async def handle_node(self, engine, node, **kwargs):
        cls = get_plugin('flitter_webrtc.signalling', node.kind, quiet=True)
        if cls is not None:
            self._signalling_class_node = cls, node
            return True
        return False

    async def render(self, node, references, **kwargs):
        signalling_class, signalling_node = self._signalling_class_node
        if self._signalling is not None and (signalling_class is None or not isinstance(self._signalling, signalling_class)):
            await self.reset_connection()
        if self._signalling is None and signalling_class is not None:
            self._signalling = signalling_class()
        if self._signalling is not None:
            await self._signalling.update(self, signalling_node)
        super().render(node, references, colorbits=8, srgb=True, **kwargs)
        self._retain_target = self._peer_connection is not None and self._peer_connection.connectionState == 'connected'

    def add_remote_track(self, track):
        self._remote_track_task = asyncio.create_task(self.consume_remote_track(track))

    async def connection_state_change(self):
        state = self._peer_connection.connectionState
        if state == 'connected':
            logger.success("WebRTC connection up via {}", self._signalling)
        elif state in ('closed', 'failed'):
            logger.info("WebRTC connection {}", state)
            if self._peer_connection is not None:
                await self.reset_connection()

    async def consume_remote_track(self, track):
        try:
            converter = VideoConverter(self.glctx)
            while True:
                frame = await track.recv()
                if self._remote_target is None:
                    self._remote_target = RenderTarget.get(self.glctx, frame.width, frame.height, 8, srgb=True)
                converter.convert(frame, self._remote_target)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Unexpected error in video decode")

    async def create_peer_connection(self):
        if self._peer_connection is not None:
            await self._peer_connection.close()
        self._peer_connection = aiortc.RTCPeerConnection()
        self._peer_connection.add_listener('track', self.add_remote_track)
        self._peer_connection.add_listener('connectionstatechange', self.connection_state_change)
        self._peer_connection.addTrack(RenderTrack(self))
        return self._peer_connection

    @property
    def connection_state(self):
        return self._peer_connection.connectionState

    async def create_offer(self):
        offer = await self._peer_connection.createOffer()
        await self._peer_connection.setLocalDescription(offer)

    @property
    def offer(self):
        return self._peer_connection.localDescription.sdp

    async def create_answer(self, offer):
        await self._peer_connection.setRemoteDescription(aiortc.RTCSessionDescription(type='offer', sdp=offer))
        answer = await self._peer_connection.createAnswer()
        await self._peer_connection.setLocalDescription(answer)

    @property
    def answer(self):
        return self._peer_connection.localDescription.sdp

    async def finish(self, answer):
        await self._peer_connection.setRemoteDescription(aiortc.RTCSessionDescription(type='answer', sdp=answer))

    async def close_peer_connection(self):
        if self._remote_track_task is not None:
            self._remote_track_task.cancel()
            try:
                await self._remote_track_task
            except aiortc.mediastreams.MediaStreamError:
                pass
            self._remote_track_task = None
            self._remote_frame = None
        if self._remote_target is not None:
            self._remote_target.release()
            self._remote_target = None
        if self._peer_connection is not None:
            self._peer_connection.remove_all_listeners()
            await self._peer_connection.close()
            self._peer_connection = None
