import numpy as np

FRAME_HEAD = bytes.fromhex("5A5A5A5A")
FRAME_TAIL = bytes.fromhex("0D0A0D0A")
HEADER_SIZE = 8
CHANNELS = 8
SAMPLES_PER_CHANNEL = 128
NORM_FACTOR = 3276.8


def parse_frame(data: bytes) -> "np.ndarray | None":
    """Parse one UDP datagram and return shape (8, 128) float32, or None if invalid."""
    start = data.find(FRAME_HEAD)
    if start == -1:
        return None
    end = data.find(FRAME_TAIL, start + len(FRAME_HEAD))
    if end == -1:
        return None

    payload = data[start + len(FRAME_HEAD) + HEADER_SIZE:end]
    part_len = len(payload) // 2
    part1 = payload[:part_len]
    part2 = payload[part_len:part_len * 2]

    def part_to_4x128(part: bytes) -> "np.ndarray":
        # Vectorized: unpack all int16 at once, reshape to (128, 4), transpose to (4, 128)
        expected = SAMPLES_PER_CHANNEL * 4 * 2  # 128 * 4 channels * 2 bytes
        arr = np.frombuffer(part[:expected], dtype='<i2').astype(np.float32)
        return arr.reshape(SAMPLES_PER_CHANNEL, 4).T  # shape (4, 128)

    ch1_4 = part_to_4x128(part1)  # shape (4, 128)
    ch5_8 = part_to_4x128(part2)  # shape (4, 128)
    result = np.concatenate([ch1_4, ch5_8], axis=0) / NORM_FACTOR  # shape (8, 128)
    return result
