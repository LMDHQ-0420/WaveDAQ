#!/usr/bin/env python3
"""
UDP数据发送测试脚本
模拟原始数据采集系统发送数据到8080端口
"""

import socket
import struct
import numpy as np
import time
import threading

class UDPDataSender:
    def __init__(self, target_host='localhost', target_port=8080):
        self.target_host = target_host
        self.target_port = target_port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.is_sending = False
        self.send_thread = None
        
        # 数据包格式参数
        self.FRAME_HEAD = bytes.fromhex("5A5A5A5A")
        self.FRAME_TAIL = bytes.fromhex("0D0A0D0A")
        self.HEADER_SIZE = 8
        
        # 模拟参数
        self.base_frequency = 60.0  # 基础频率60Hz，对应1200 RPM
        self.sampling_rate = 1000   # 采样率1000Hz
        self.samples_per_packet = 128  # 每个数据包128个采样点
        
    def generate_test_data(self):
        """生成测试数据"""
        # 生成时间序列
        t = np.linspace(0, self.samples_per_packet/self.sampling_rate, self.samples_per_packet)
        
        # 为8个通道生成数据
        channels_data = []
        for ch in range(8):
            if ch == 3:  # 第4通道（索引3）包含主要的螺旋桨信号
                # 主频率信号 + 噪声
                signal = (
                    1000 * np.sin(2 * np.pi * self.base_frequency * t) +  # 主频率
                    200 * np.sin(2 * np.pi * self.base_frequency * 2 * t) +  # 二次谐波
                    100 * np.random.normal(0, 1, len(t))  # 噪声
                )
            else:
                # 其他通道主要是噪声
                signal = 200 * np.random.normal(0, 1, len(t))
            
            # 转换为16位整数
            signal_int = np.clip(signal, -32767, 32767).astype(np.int16)
            channels_data.append(signal_int)
        
        return channels_data
    
    def pack_data(self, channels_data):
        """将数据打包成UDP数据包格式"""
        # 创建8x128的数据矩阵
        data_matrix = np.array(channels_data)  # 8 channels x 128 samples
        
        # 转置为128x8，然后重新排列为4x128的两个部分
        transposed = data_matrix.T  # 128 x 8
        
        # 分成两个4x128的部分
        part1 = transposed[:, :4].flatten()  # 前4个通道
        part2 = transposed[:, 4:].flatten()  # 后4个通道
        
        # 打包为字节
        part1_bytes = struct.pack('<' + 'h' * len(part1), *part1)
        part2_bytes = struct.pack('<' + 'h' * len(part2), *part2)
        
        # 组合载荷
        payload = part1_bytes + part2_bytes
        
        # 创建头部（8字节）
        header = b'\x00' * self.HEADER_SIZE
        
        # 组合完整数据包
        packet = self.FRAME_HEAD + header + payload + self.FRAME_TAIL
        
        return packet
    
    def send_data_continuously(self):
        """持续发送数据"""
        packet_interval = 0.1  # 每100ms发送一个数据包
        
        print(f"开始向 {self.target_host}:{self.target_port} 发送UDP数据...")
        print(f"基础频率: {self.base_frequency} Hz (对应 {self.base_frequency * 20} RPM)")
        print("按 Ctrl+C 停止发送")
        
        while self.is_sending:
            try:
                # 生成测试数据
                channels_data = self.generate_test_data()
                
                # 打包数据
                packet = self.pack_data(channels_data)
                
                # 发送数据包
                self.sock.sendto(packet, (self.target_host, self.target_port))
                
                # 等待下一个发送周期
                time.sleep(packet_interval)
                
                # 偶尔改变频率来模拟转速变化
                if np.random.random() < 0.1:  # 10%的概率改变频率
                    self.base_frequency += np.random.normal(0, 2)
                    self.base_frequency = max(30, min(100, self.base_frequency))  # 限制在30-100Hz范围
                
            except Exception as e:
                print(f"发送数据时出错: {e}")
                break
    
    def start_sending(self):
        """开始发送数据"""
        if not self.is_sending:
            self.is_sending = True
            self.send_thread = threading.Thread(target=self.send_data_continuously, daemon=True)
            self.send_thread.start()
    
    def stop_sending(self):
        """停止发送数据"""
        self.is_sending = False
        if self.send_thread:
            self.send_thread.join()
    
    def __del__(self):
        """析构函数"""
        self.stop_sending()
        self.sock.close()

def main():
    sender = UDPDataSender()
    
    try:
        sender.start_sending()
        
        # 保持程序运行
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n停止发送数据...")
        sender.stop_sending()
        print("已停止")

if __name__ == "__main__":
    main()

