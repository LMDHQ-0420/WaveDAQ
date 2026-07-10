import socket
from .frame_parser import parse_frame
from .data_manager import DataManager

UDP_PORT = 8080
BUFFER_SIZE = 20_000_000


def udp_receive_thread(data_manager: DataManager, sock: socket.socket):
    while True:
        try:
            data, _ = sock.recvfrom(BUFFER_SIZE)
            if not data_manager.is_collecting:
                continue
            arr = parse_frame(data)  # shape (8, 128) float32, or None
            if arr is not None:
                with data_manager.history_lock:
                    for ch in range(8):
                        data_manager.live_history_buf[ch].extend(arr[ch])
        except Exception:
            pass
