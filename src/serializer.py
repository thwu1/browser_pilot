import json
import random
import time

import orjson
import msgpack

DEFAULT_SERIALIZER = "orjson"


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
        return json.dumps(obj)

    def loads(self, obj):
        return json.loads(obj)


class MsgpackSerializer:
    def dumps(self, obj):
        return msgpack.packb(obj)

    def loads(self, obj):
        return msgpack.unpackb(obj)


class Serializer:
    def __init__(self, serializer: str = "orjson"):
        self.serializer = serializer
        if serializer == "orjson":
            self.dumps = OrjsonSerializer().dumps
            self.loads = OrjsonSerializer().loads
        elif serializer == "json":
            raise NotImplementedError("JSON serializer is not implemented")
        elif serializer == "msgpack":
            self.dumps = MsgpackSerializer().dumps
            self.loads = MsgpackSerializer().loads
        else:
            raise ValueError(f"Invalid serializer: {serializer}")


if __name__ == "__main__":
    # Create test objects of different sizes for more comprehensive comparison
    test_objects = {
        "small": {
            "id": 6,
            "action": "click",
            "selector": "#submit-button",
            "timeout": 5000,
        },
        "medium": {
            "id": 6,
            "result": {
                "cookies": [],
                "localStorage": [
                    {"name": f"key{i}", "value": f"value{i}"} for i in range(50)
                ],
                "sessionStorage": [
                    {"name": f"session{i}", "value": f"data{i}"} for i in range(50)
                ],
            },
        },
        "large": {
            "id": 6,
            "result": {
                "cookies": [],
                "origins": [
                    {
                        "origin": f"http://localhost:{random.randint(10000, 99999)}",
                        "localStorage": [
                            {
                                "name": f"foo{i}",
                                "value": str(random.randint(1000, 9999)),
                            }
                            for i in range(1000)
                        ],
                    }
                    for _ in range(100)
                ],
            },
        },
    }
    serializer = OrjsonSerializer()
    print(serializer.dumps(test_objects["small"]))

    # # Headers for our results table
    # print(f"\n{'=' * 80}")
    # print(f"{'Object Size':<15} {'Serializer':<15} {'Bytes':<10} {'Time (s)':<10} {'Ratio vs JSON':<15}")
    # print(f"{'-' * 80}")

    # # Test each serializer with different object sizes
    # for size_name, test_obj in test_objects.items():
    #     # Get baseline JSON size for comparison
    #     json_serializer = JsonSerializer()
    #     json_data = json_serializer.dumps(test_obj)
    #     json_size = len(json_data.encode('utf-8'))  # Size in bytes

    #     # Test JSON serializer
    #     start = time.time()
    #     for _ in range(100):
    #         s = json_serializer.dumps(test_obj)
    #         obj = json_serializer.loads(s)
    #     json_time = time.time() - start
    #     print(f"{size_name:<15} {'JSON':<15} {json_size:<10} {json_time:.4f}    {1.0:<15.2f}")

    #     # Test OrjsonSerializer
    #     orjson_serializer = OrjsonSerializer()
    #     orjson_data = orjson_serializer.dumps(test_obj)
    #     orjson_size = len(orjson_data.encode('utf-8'))  # Size in bytes
    #     size_ratio = orjson_size / json_size

    #     start = time.time()
    #     for _ in range(100):
    #         s = orjson_serializer.dumps(test_obj)
    #         obj = orjson_serializer.loads(s)
    #     orjson_time = time.time() - start
    #     print(f"{size_name:<15} {'ORJSON':<15} {orjson_size:<10} {orjson_time:.4f}    {size_ratio:<15.2f}")

    #     # Test MsgpackSerializer
    #     msgpack_serializer = MsgpackSerializer()
    #     msgpack_data = msgpack_serializer.dumps(test_obj)
    #     msgpack_size = len(msgpack_data)  # Already in bytes
    #     size_ratio = msgpack_size / json_size

    #     start = time.time()
    #     for _ in range(100):
    #         s = msgpack_serializer.dumps(test_obj)
    #         obj = msgpack_serializer.loads(s)
    #     msgpack_time = time.time() - start
    #     print(f"{size_name:<15} {'MSGPACK':<15} {msgpack_size:<10} {msgpack_time:.4f}    {size_ratio:<15.2f}")

    #     print(f"{'-' * 80}")

    # print(f"{'=' * 80}")
    # print("Note: Bytes = size of serialized message, Time = seconds for 100 serialization+deserialization cycles")
    # print("Ratio = size compared to standard JSON (smaller is better)")
