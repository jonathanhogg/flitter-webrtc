# Flitter WebRTC

[![CI lint](https://github.com/jonathanhogg/flitter-webrtc/actions/workflows/ci-lint.yml/badge.svg?)](https://github.com/jonathanhogg/flitter-webrtc/actions/workflows/ci-lint.yml)

This package provides a plugin for sending and receiving video streams in
[Flitter](https://flitter.readthedocs.io/).

The additional `!window`/`!offscreen` provided by this plugin are:

## `!webrtc`

This provides a two-way video "call" endpoint. Nodes within this will be
rendered, composited and then transmitted as the outgoing video track, the
incoming video track will be rendered to the output image of this node. If no
WebRTC connection is currently active, the node will return its composited
input (similar to a bare `!shader` node).

Video streams between `!webrtc` nodes are always two-way. If a `!webrtc` node
contains no (visible) render nodes then it will transmit a black video stream.
For one-way streams, just ignore the blank output at the other end. A program
may contain multiple `!webrtc` nodes, including nested nodes that pass
(possibly manipulated) video through from one instance to another. See
[examples/tranceiver.fl](https://github.com/jonathanhogg/flitter-webrtc/blob/main/examples/tranceiver.fl)
for an example of this.

The `!webrtc` node supports the single attribute:

- `state=` *KEY* \
This provides a state key that will be used to store the current WebRTC
connection state. If no connection is active, this key will be empty (i.e.,
will return `null`). If a connection is active then the value will be one of:
`:connected`, `:connecting`, `:closed`, `:failed`, `:new`. As re-connection is
attempted immediately, this state key will normally resolve to either
`:connected` or `:connecting`.

Setting up a WebRTC connection between two endpoints is controlled by a
separate *signalling* protocol, defined by adding a signalling node within
the `!webrtc` node. Signalling protocols can be added through the **Flitter**
plugin API. The following signalling nodes are provided by this plugin:

Note that `!webrtc` nodes are *always* 8-bit sRGB and will ignore any direct
setting of a `colorbits=` attribute or the `!window` default `colorbits=`
setting.

### `!broadcast`

This provides a simple local-network signalling protocol based on broadcasting
messages between UDP sockets. The following attributes are supported:

- `call=` *STRING* \
Indicates that this WebRTC node is to make an outgoing connection to another
node with the given identifier.

- `answer=` *STRING* \
Indicates that this WebRTC node is to wait for an incoming connection made with
this identifier.

- `secret=` *STRING* \
Provides an arbitrary string value that will be used for encrypting the
signalling messages; both endpoints *must* use the same value; default is
`flitter_webrtc`.

- `port=` *INTEGER* \
Specifies the UDP port to bind to if awaiting a connection or to send broadcast
messages to if originating a connection; default is port 5111.

- `host=` *STRING* \
Specifies a hostname or IP address of the local interface that should be used
for communication (this is *not* the address of the host being called);
default is the "any" IP address.

All signalling messages are encrypted using the
[Fernet](https://github.com/fernet/spec/) algorithm with a key that is derived
from the `call=`/`answer=` connection *ID* and the value of `secret=`. As the
*ID* is used for key derivation, secrecy generally can be guaranteed by
simply using unguessable values for the connection *ID*. However, supplying
the `secret=` attribute allows a group of nodes to share a common secret (like
a private chat room name) and then use public *ID* values (like a user name) to
establish connections.

If both `answer=` and `call=` are provided, then `call=` takes priority and
this endpoint will attempt an outgoing connection. Changes to any of the
attribute values will cause any current connection to be torn down and
restarts the signalling protocol.

### `!websocket`

This provides a signalling protocol that will work across the Internet, based
on a WebSocket server. The server is also included (see below for details). The
following attributes are supported:

- `url=` *URL* \
This is a required attribute that specifies the address of the signalling
server to connect to. This should be either an `http`/`https` or `ws`/`wss`
schema URL – either will result in an attempted WebSocket connection.

- `verify=` *BOOLEAN* \
Specifies whether to verify the certificate when making an SSL/TLS connection.
The default is `true` and this should only be set to `false` if testing against
a server with a self-signed certificate. Encryption will still be used, but
clients will have no protection against server impersonation.

- `room=` *STRING* \
This is a required attribute that specifies the name of a "room" that should
be joined for making or receiving connections. This is an arbitrary string
value.

- `id=` *STRING* \
This is a required attribute that specifies the endpoint ID to use when making
and receiving calls. This ID must be unique within the specified room.

- `call=` *STRING* \
This is an optional attribute that specifies the endpoint ID to initiate a
WebRTC connection to. This should be the ID of another endpoint in the same
room. If this is not specified, then the peer will wait for a connection to
be initiated by another endpoint.

Note that no video is sent to or from the signalling server. It serves only
as a mechanism for peers to find each other.

#### Running a signalling server

To run a WebSocket signalling server, execute:

```shell
% flitter_webrtc [...]
```

The supported command-line options are:

- `--trace` | `--debug` | `--verbose` | `--quiet` \
Specifies the level of logging to output to the console.

- `--host=` *HOST* \
Specifies the IP address/hostname of the interface to listen for WebSocket
connections on. Default is the "any" IP address.

- `--port=` *PORT* \
Specifies the port number to listen on. Default is `8080` if no certificate is
specified or `8443` otherwise.

- `--certificate=` *CERTFILE* \
Specifies an SSL/TLS PEM certificate file to use. Client connections must use
the `https` or `wss` schemas.

- `--key=` *KEYFILE* \
Optionally specifies the matching PEM private key for the certificate. If this
option is not provided then the certificate file is expected to also contain
the private key.
