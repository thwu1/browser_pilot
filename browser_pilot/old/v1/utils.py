import json
from enum import Enum
from typing import Any, Optional, Union

import msgpack
import psutil
import zmq
import zmq.asyncio


class MsgType(bytes, Enum):
    READY = b"R"
    STATUS = b"S"
    OUTPUT = b"O"


# Adapted from: https://github.com/sgl-project/sglang/blob/v0.4.1/python/sglang/srt/utils.py#L783 # noqa: E501
def make_zmq_socket(
    ctx: Union[zmq.asyncio.Context, zmq.Context],  # type: ignore[name-defined]
    path: str,
    socket_type: Any,
    bind: Optional[bool] = None,
    identity: Optional[bytes] = None,
) -> Union[zmq.Socket, zmq.asyncio.Socket]:  # type: ignore[name-defined]
    """Make a ZMQ socket with the proper bind/connect semantics."""

    mem = psutil.virtual_memory()
    socket = ctx.socket(socket_type)

    # Calculate buffer size based on system memory
    total_mem = mem.total / 1024**3
    available_mem = mem.available / 1024**3
    # For systems with substantial memory (>32GB total, >16GB available):
    # - Set a large 0.5GB buffer to improve throughput
    # For systems with less memory:
    # - Use system default (-1) to avoid excessive memory consumption
    if total_mem > 32 and available_mem > 16:
        buf_size = int(0.5 * 1024**3)  # 0.5GB in bytes
    else:
        buf_size = -1  # Use system default buffer size

    if bind is None:
        bind = socket_type != zmq.PUSH

    if socket_type in (zmq.PULL, zmq.DEALER, zmq.ROUTER):
        socket.setsockopt(zmq.RCVHWM, 0)
        socket.setsockopt(zmq.RCVBUF, buf_size)

    if socket_type in (zmq.PUSH, zmq.DEALER, zmq.ROUTER):
        socket.setsockopt(zmq.SNDHWM, 0)
        socket.setsockopt(zmq.SNDBUF, buf_size)

    if identity is not None:
        socket.setsockopt(zmq.IDENTITY, identity)

    if bind:
        socket.bind(path)
    else:
        socket.connect(path)

    return socket


class JsonEncoder:
    def __call__(self, obs):
        return json.dumps(obs).encode()


class JsonDecoder:
    def __call__(self, obs):
        return json.loads(obs.decode())


class MsgpackEncoder:
    def __call__(self, obs):
        return msgpack.dumps(obs, use_bin_type=True)


class MsgpackDecoder:
    def __call__(self, obs):
        return msgpack.loads(obs, raw=False)


if __name__ == "__main__":
    d = {"a": 1, "b": 2, "c": {"d": 3}}
    encoded = MsgpackEncoder()(d)
    assert type(encoded) == bytes

    decoded = MsgpackDecoder()(encoded)
    assert decoded == d
