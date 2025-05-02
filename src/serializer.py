import json
import random
import re
import time

import orjson

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


class Serializer:
    def __init__(self, serializer: str = DEFAULT_SERIALIZER):
        self.serializer = serializer
        if serializer == "orjson":
            self.dumps = OrjsonSerializer().dumps
            self.loads = OrjsonSerializer().loads
        elif serializer == "json":
            self.dumps = JsonSerializer().dumps
            self.loads = JsonSerializer().loads
        else:
            raise ValueError(f"Invalid serializer: {serializer}")


if __name__ == "__main__":

    # Create a large test object
    test_obj = {
        "id": 6,
        "result": {
            "cookies": [],
            "origins": [
                {
                    "origin": f"http://localhost:{random.randint(10000, 99999)}",
                    "localStorage": [
                        {"name": "foo", "value": str(random.randint(1000, 9999))}
                        for _ in range(1000)
                    ],
                }
                for _ in range(100)
            ],
        },
    }

    # Test OrjsonSerializer
    orjson_serializer = OrjsonSerializer()
    start = time.time()
    for _ in range(100):
        s = orjson_serializer.dumps(test_obj)
        obj = orjson_serializer.loads(s)
    orjson_time = time.time() - start
    print(
        f"OrjsonSerializer with try-except: {orjson_time:.4f} seconds for 100 dumps+loads"
    )

    start = time.time()
    for _ in range(100):
        s = orjson.dumps(test_obj).decode("utf-8")
        obj = orjson.loads(s)
    orjson_time = time.time() - start
    print(f"OrjsonSerializer: {orjson_time:.4f} seconds for 100 dumps+loads")

    # Test JsonSerializer
    json_serializer = JsonSerializer()
    start = time.time()
    for _ in range(100):
        s = json_serializer.dumps(test_obj)
        obj = json_serializer.loads(s)
    json_time = time.time() - start
    print(f"JsonSerializer: {json_time:.4f} seconds for 100 dumps+loads")
