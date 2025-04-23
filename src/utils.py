import json
from enum import Enum
from typing import Any, Optional, Union

import msgpack
import psutil
import zmq
import zmq.asyncio
import zstandard as zstd


class MsgType(bytes, Enum):
    READY = b"R"
    STATUS = b"S"
    OUTPUT = b"O"
    TASK = b"T"
    REPLY = b"P"
    # BATCH = b"B"


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

class ZstdMsgpackEncoder:
    def __init__(self, level: int = 3):
        self.cctx = zstd.ZstdCompressor(level=level)
    def __call__(self, obs):
        # 1. Serialize with msgpack
        packed_data = msgpack.packb(obs, use_bin_type=True)
        # 2. Compress with Zstandard
        compressed_data = self.cctx.compress(packed_data)
        return compressed_data

class ZstdMsgpackDecoder:
    def __init__(self):
        self.dctx = zstd.ZstdDecompressor()

    def __call__(self, compressed_data):
        # 1. Decompress with Zstandard
        packed_data = self.dctx.decompress(compressed_data)
        # 2. Deserialize with msgpack
        obj = msgpack.unpackb(packed_data, raw=False)
        return obj

if __name__ == "__main__":
    d = {'task_id': 'task_6d3d0e99', 'context_id': 'context_21a2bc2a', 'page_id': '9b59ab14-785c-468d-9632-1ac904ffba95', 'command': 'browser_observation', 'params': {'observation_type': 'html'}, 'engine_recv_timestamp': 1745349913.0101, 'engine_send_timestamp': 1745349913.0202243, 'worker_recv_timestamp': 1745349913.020963, 'worker_start_process_timestamp': None, 'worker_finish_process_timestamp': None, 'worker_send_timestamp': None}
    encoded = MsgpackEncoder()(d)
    # print(len(encoded))
    assert type(encoded) == bytes

    decoded = MsgpackDecoder()(encoded)
    assert decoded == d

    zstd_encoded = ZstdMsgpackEncoder()(d)
    # print(len(zstd_encoded))
    assert type(zstd_encoded) == bytes

    zstd_decoded = ZstdMsgpackDecoder()(zstd_encoded)
    assert zstd_decoded == d
    
