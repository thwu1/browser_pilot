# from typing import Dict, Any, List
# import zmq
# from utils import make_zmq_socket, JsonEncoder, JsonDecoder
# import multiprocessing as mp
# import time


# class WorkerClient:
#     def __init__(self, input_path: str, output_path: str, num_workers: int):
#         self.input_path = input_path
#         self.output_path = output_path
#         self.num_workers = num_workers
#         # Create ZMQ context
#         self.zmq_context = zmq.Context()
#         self.input_socket = make_zmq_socket(
#             self.zmq_context, self.input_path, zmq.ROUTER, bind=True
#         )
#         self.output_socket = make_zmq_socket(
#             self.zmq_context, self.output_path, zmq.PULL, bind=True
#         )
#         self.encoder = JsonEncoder()
#         self.decoder = JsonDecoder()

#         self.workers_status: Dict[int, bool] = {
#             i: {"ready": False} for i in range(self.num_workers)
#         }

#     def _worker_ready(self):
#         msg = self.input_socket.recv_multipart()
#         worker_id = msg[0]
#         self.workers_status[worker_id]["ready"] = True

#     def send(self, requests: List[Dict[str, Any]], index: int) -> str:
#         if isinstance(requests, dict):
#             requests = [requests]
#         print("client trying to send", [str(index).encode(), self.encoder(requests)])
#         self.input_socket.send_multipart([str(index).encode(), self.encoder(requests)])

#     def recv(self):
#         msg = self.output_socket.recv_multipart()
#         return self.decoder(msg)


# class Worker:
#     def __init__(self, input_path: str, output_path: str):
#         self.index = 0
#         self.input_path = input_path
#         self.output_path = output_path
#         self.zmq_context = zmq.Context()
#         self.input_socket = make_zmq_socket(
#             self.zmq_context,
#             self.input_path,
#             zmq.DEALER,
#             bind=False,
#             identity=str(self.index).encode(),
#         )
#         self.output_socket = make_zmq_socket(
#             self.zmq_context, self.output_path, zmq.PUSH, bind=False
#         )

#         self.decoder = JsonDecoder()

#     def recv(self):
#         print("worker trying to recv")
#         msgs = self.input_socket.recv_multipart()
#         print("recv", msgs)
#         return [self.decoder(msg) for msg in msgs]

#     def send(self, msg: List[Dict[str, Any]]):
#         if isinstance(msg, dict):
#             msg = [msg]
#         self.output_socket.send_multipart([self.encoder(m) for m in msg])


# def test_dealer_router():
#     client = WorkerClient(
#         "ipc://test_dealer_router_in", "ipc://test_dealer_router_out", 1
#     )
#     worker = Worker("ipc://test_dealer_router_in", "ipc://test_dealer_router_out")

#     time.sleep(1)

#     client.send({"cmd": "test"}, 0)
#     time.sleep(1)
#     print("recv", worker.recv())


# # def test_simple_connection():
# #     ctx = zmq.Context()

# #     # Create ROUTER (server)
# #     router = ctx.socket(zmq.ROUTER)
# #     router.bind("ipc://test")

# #     # Create DEALER (client)
# #     dealer = ctx.socket(zmq.DEALER)
# #     index = 0
# #     dealer.setsockopt(zmq.IDENTITY, str(index).encode())
# #     dealer.connect("ipc://test")

# #     # Wait for connection
# #     time.sleep(1)

# #     # Send test message
# #     print("Sending test message...")
# #     router.send_multipart([str(index).encode(), b"test"])

# #     time.sleep(1)

# #     # Try to receive
# #     try:
# #         print("Trying to receive...")
# #         msg = dealer.recv_multipart(flags=zmq.NOBLOCK)
# #         print(f"Received: {msg}")
# #     except zmq.Again:
# #         print("No message received")


# # if __name__ == "__main__":
# #     test_simple_connection()
