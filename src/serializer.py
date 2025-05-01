import orjson
import json

DEFAULT_SERIALIZER = "orjson"

class OrjsonSerializer:
    def dumps(self, obj):
        return orjson.dumps(obj).decode("utf-8")

    def loads(self, obj):
        return orjson.loads(obj)

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
