import zmq
import multiprocessing as mp
import time
import asyncio
import uuid

class Client:
    def __init__(self, worker_id, task_port, result_port):
        self.worker_id = worker_id
        self.task_port = task_port
        self.result_port = result_port
        self._setup_zmq()
        print(f"BrowserWorkerClient {worker_id} initialized")
        
    def _setup_zmq(self):
        """Set up ZMQ sockets for communication"""
        self.zmq_context = zmq.Context()
        
        # Socket to send tasks (PUSH)
        self.task_socket = self.zmq_context.socket(zmq.PUSH)
        self.task_socket.setsockopt(zmq.LINGER, 5000)  # Don't wait for pending messages on close
        self.task_socket.connect(f"tcp://localhost:{self.task_port}")
        
        # Socket to receive results (PULL)
        self.result_socket = self.zmq_context.socket(zmq.PULL)
        self.result_socket.setsockopt(zmq.LINGER, 5000)  # Don't wait for pending messages on close
        self.result_socket.setsockopt(zmq.RCVHWM, 10000)
        self.result_socket.connect(f"tcp://localhost:{self.result_port}")
        
    
    def send(self, message):
        """Send a message to the worker process"""
        time_ = time.time()
        message["timestamp"] = time_
        self.task_socket.send_json(message)
        print("Client sent message:", message)
    
    def receive(self, timeout=1000):
        """Receive a message from the worker process"""
        try:
            message = self.result_socket.recv_json(flags=zmq.NOBLOCK)
            print("Client received message:", message)
            return message
        except zmq.Again:
            return None


class Server:
    def __init__(self, task_port, result_port):
        self.task_port = task_port
        self.result_port = result_port
        self._setup_zmq()
        print(f"BrowserWorkerServer initialized")

        self.input_queue = asyncio.Queue()
        self.output_queue = asyncio.Queue()
        
    def _setup_zmq(self):
        """Set up ZMQ sockets for communication"""
        self.zmq_context = zmq.Context()
        
        # Socket to receive tasks (PULL)
        self.task_socket = self.zmq_context.socket(zmq.PULL)
        self.task_socket.setsockopt(zmq.LINGER, 5000)  # Don't wait for pending messages on close
        self.task_socket.bind(f"tcp://*:{self.task_port}")
        
        # Socket to send results (PUSH)
        self.result_socket = self.zmq_context.socket(zmq.PUSH)
        self.result_socket.setsockopt(zmq.LINGER, 5000)  # Don't wait for pending messages on close
        self.result_socket.bind(f"tcp://*:{self.result_port}")
        
    async def send_loop(self):
        """Send a message to the worker process"""
        while True:
            while self.output_queue.qsize() == 0:
                await asyncio.sleep(0.05)
            try:
                message = self.output_queue.get_nowait()
                message["timestamp"] = time.time()
                del message["timestamp"]
                self.result_socket.send_json(message)
                print("Server sent message:", message)
                # await asyncio.sleep(0.1)
            except zmq.Again:
                print("Server send message failed: message queue full")
                await asyncio.sleep(0.1)
            except Exception as e:
                print(f"Error sending message: {e}")
                await asyncio.sleep(0.1)
            
    async def receive_loop(self, timeout=1000):
        """Receive a message from the worker process"""
        while True:
            try:
                message = self.task_socket.recv_json(flags=zmq.NOBLOCK)
                print("Server received message:", message)
                if message:
                    self.input_queue.put_nowait(message)
            except zmq.Again:
                await asyncio.sleep(0.1)
    
    async def process_loop(self):
        while True:
            try:
                message = await self.input_queue.get()
                message["value"] += 1

                self.output_queue.put_nowait(message)
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.1)
    
    @staticmethod
    def run_background_loop(task_port, result_port):
        """Run the server in a background loop"""
        server = Server(task_port, result_port)
        print(f"Server running on ports {task_port} and {result_port}")
        tasks = [server.process_loop(), server.receive_loop(), server.send_loop()]

        async def main_loop():
            await asyncio.gather(*tasks)
        asyncio.run(main_loop())
        
    
                


if __name__ == "__main__":
    
    proc = mp.Process(target=Server.run_background_loop, args=(6000, 6001))
    proc.daemon = True
    proc.start()

    client = Client("test_worker_cfa378c0", 6000, 6001)
    client.send({"value": 0, "result": {"hello": "world", "value": 0}, "task_id": f"task_{uuid.uuid4().hex[:8]}", "context_id": f"{uuid.uuid4().hex[:8]}", "command": "create_context"})
    for i in range(1000):
        result = None
        while result is None:
            result = client.receive()
        result["value"] += 1
        client.send(result)


        
        