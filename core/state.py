import socket
import numpy as np
import threading

# 参数配置
UDP_PORT = 8080
BUFFER_SIZE = 20000000
FRAME_HEAD = bytes.fromhex("5A5A5A5A")
FRAME_TAIL = bytes.fromhex("0D0A0D0A")
HEADER_SIZE = 8
MAX_COLLECTIONS = 20

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("", UDP_PORT))
sock.settimeout(2.0)


# 全局数据缓存
live_history = [np.array([], dtype=np.float32) for _ in range(8)]  # 实时数据
collected_data = []  # 存储所有已采集的数据
history_lock = threading.Lock()
is_collecting = False  # 是否正在采集的状态标志
