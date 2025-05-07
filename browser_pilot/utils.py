import json
from enum import Enum
from typing import Any, Optional, Union

import msgpack
import numpy as np
import orjson
import psutil
import zmq
import zmq.asyncio
import zstandard as zstd
import fcntl
import os


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


class OrjsonSerializer:
    # fallback to json if encounter lone surrogates
    def dumps(self, obj):
        try:
            return orjson.dumps(obj).decode("utf-8")
        except:
            return json.dumps(obj)

    def loads(self, obj):
        try:
            return orjson.loads(obj)
        except:
            return json.loads(obj)


class JsonSerializer:
    def dumps(self, obj):
        return json.dumps(obj).encode()

    def loads(self, obj):
        return json.loads(obj.decode())


class MsgpackSerializer:
    def dumps(self, obj):
        return msgpack.packb(obj, use_bin_type=True)

    def loads(self, obj):
        return msgpack.unpackb(obj, raw=False)


class Serializer:
    def __init__(self, serializer: str = "orjson"):
        self.serializer = serializer
        if serializer == "orjson":
            self.dumps = OrjsonSerializer().dumps
            self.loads = OrjsonSerializer().loads
        elif serializer == "msgpack":
            self.dumps = MsgpackSerializer().dumps
            self.loads = MsgpackSerializer().loads
        else:
            raise ValueError(f"Invalid serializer: {serializer}")


# Add this helper function to convert numpy arrays in complex nested structures
def numpy_safe_serializer(obj):
    if isinstance(obj, str):
        return obj
    elif isinstance(obj, dict):
        return {k: numpy_safe_serializer(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [numpy_safe_serializer(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(numpy_safe_serializer(item) for item in obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    else:
        return obj


def get_worker_id():
    lockfile = "worker_id.lock"
    if not os.path.exists(lockfile):
        # Create the file and initialize with 0
        with open(lockfile, "w") as f:
            f.write("0")

    with open(lockfile, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        content = f.read().strip()
        if content == "":
            worker_id = 0
        else:
            worker_id = int(content)
        # Write back the incremented worker id
        f.seek(0)
        f.truncate()
        f.write(str(worker_id + 1))
        f.flush()
        # Lock is released when file is closed
    return worker_id


if __name__ == "__main__":
    d = {
        "task_id": "task_6d3d0e99",
        "context_id": "context_21a2bc2a",
        "page_id": "9b59ab14-785c-468d-9632-1ac904ffba95",
        "command": "browser_observation",
        "params": {"observation_type": "html"},
        "engine_recv_timestamp": 1745349913.0101,
        "engine_send_timestamp": 1745349913.0202243,
        "worker_recv_timestamp": 1745349913.020963,
        "worker_start_process_timestamp": None,
        "worker_finish_process_timestamp": None,
        "worker_send_timestamp": None,
    }
    serializer = MsgpackSerializer()
    encoded = serializer.dumps(d)
    # print(len(encoded))
    assert type(encoded) == bytes

    decoded = serializer.loads(encoded)
    assert decoded == d
