import struct
import numpy as np
from . import state


def udp_receive_thread():
    """接收 UDP 数据的线程函数（保持原有逻辑）。"""
    while True:
        try:
            data, addr = state.sock.recvfrom(state.BUFFER_SIZE)
            if not state.is_collecting:  # 如果没有在采集中，则忽略数据
                continue

            start = data.find(state.FRAME_HEAD)
            end = data.find(state.FRAME_TAIL, start + len(state.FRAME_HEAD))
            if start != -1 and end != -1:
                payload = data[start + len(state.FRAME_HEAD) + state.HEADER_SIZE:end]
                part_len = len(payload) // 2
                part1 = payload[:part_len]
                part2 = payload[part_len:part_len * 2]

                def part_to_4x128(part):
                    arr = []
                    for i in range(0, len(part), 2):
                        group = part[i:i + 2]
                        value = struct.unpack('<h', group)[0]
                        arr.append(value)
                    arr_2d = [arr[i * 4:(i + 1) * 4] for i in range(128)]
                    arr_2d_T = [[arr_2d[row][col] for row in range(128)] for col in range(4)]
                    return arr_2d_T

                arr1 = part_to_4x128(part1)
                arr2 = part_to_4x128(part2)
                arr_8x128 = arr1 + arr2

                with state.history_lock:
                    for ch in range(8):
                        norm_data = np.array(arr_8x128[ch], dtype=np.float32) / 3276.8
                        state.live_history[ch] = np.concatenate((state.live_history[ch], norm_data))
            else:
                pass
        except Exception:
            # 保持与原代码类似的鲁棒性：超时或其它问题时继续循环
            pass
