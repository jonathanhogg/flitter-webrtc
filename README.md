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
input (and thus acts like a bare `!shader` node).

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

### `!broadcast`

This provides a simple local-network signalling protocol based on broadcasting
messages between UDP sockets. The following attributes are supported:

- `call=` *ID* \
Indicates that this WebRTC node is to make an outgoing connection to another
node with the identifier *ID*.

- `answer=` *ID* \
Indicates that this WebRTC node is to wait for an incoming connection made with
the identifier *ID*.

- `secret=` *SECRET* \
Provides an arbitrary string value that will be used for encrypting the
signalling messages; both endpoints *must* use the same *SECRET* value; default
is `flitter_webrtc`.

- `port=` *PORT* \
Specifies the UDP port to bind to if awaiting a connection or to send broadcast
messages to if originating a connection; default is port 5111.

- `host=` *HOST* \
Specifies a hostname or IP address of the local interface that should be used
for communication (this is *not* the address of the host being called);
default is the "any" IP address.

All signalling messages are encrypted using the
[Fernet](https://github.com/fernet/spec/) algorithm with a key that is derived
from the `call=`/`answer=` connection *ID* and the value of `secret=`. As the
*ID* is used for key derivation, secrecy generally can be guaranteed by
simply using unguessable values for the connection *ID*. However, supplying
the `secret=` attribute allows a group of nodes to share a common secret and
then use public *ID* values (such as a host or user name) to establish
connections.

If both `answer=` and `call=` are provided, then `call=` takes priority and
this endpoint will attempt an outgoing connection. Changes to any of the
attribute values will cause any current connection to be torn down and
restarts the signalling protocol.
