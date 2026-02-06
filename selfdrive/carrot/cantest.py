#!/usr/bin/env python3
"""
mazda_turn_switch_test.py
在 comma3 上发送马自达 TURN_SWITCH 报文（左/右转向灯），支持日志显示、启动前读取 checksum、持续发送指定秒数。
依赖：openpilot 环境（panda、opendbc）
python3 mazda_turn_switch_test.py --left --seconds 4

用法：python3 mazda_turn_switch_test.py --left|--right [--seconds SECONDS]
"""

import argparse
import time
import sys
import os

# 确保 openpilot 路径
if '/data/openpilot' not in sys.path:
    sys.path.append('/data/openpilot')

from panda import Panda
from opendbc.can import CANPacker
from opendbc.car.mazda.values import DBC

def calculate_checksum_mazda(dat: list, addr: int) -> int:
    """
    马自达常用加法校验算法。
    对于 0x91 报文，校验位通常在 Byte 4。
    """
    # 算法示例：(常数 - 地址 - 其它字节之和) % 256
    # 注意：常数可能在 249-255 之间，建议根据实车日志调整
    s = sum(dat[i] for i in range(len(dat)) if i != 4)
    return (255 - addr - s) & 0xFF

def pack_turn_switch(packer, bus: int, hazard: bool, left: bool, right: bool, ctr: int):
    """
    打包 TURN_SWITCH (0x91) 报文
    :param packer: CANPacker 实例
    :param bus: 总线号
    :param hazard: 危险报警灯
    :param left: 左转向
    :param right: 右转向
    :param ctr: 计数器
    :return: (addr, data, bus)
    """
    values = {
        "HAZARD": int(hazard),
        "TURN_RIGHT_SWITCH": int(right),
        "TURN_LEFT_SWITCH": int(left),
        "CTR": ctr & 0xF,
        "CHKSUM": 0,
    }
    addr, dat, bus_ret = packer.make_can_msg("TURN_SWITCH", bus, values)

    # 将 bytes 转为 list 以便修改
    dat_list = list(dat)

    # 纠正：根据 DBC，CHKSUM (39|8@0+) 位于 Byte 4
    checksum = calculate_checksum_mazda(dat_list, addr)
    dat_list[4] = checksum & 0xFF

    return addr, bytes(dat_list), bus_ret

def main():
    parser = argparse.ArgumentParser(description="发送马自达 TURN_SWITCH 报文（左/右转向灯）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--left', action='store_true', help='左转向')
    group.add_argument('--right', action='store_true', help='右转向')
    parser.add_argument('--seconds', type=int, default=4, help='持续发送秒数（默认 4）')
    args = parser.parse_args()

    # 初始化 panda
    try:
        p = Panda()
    except Exception as e:
        print(f"无法连接 Panda: {e}")
        sys.exit(1)

    # 设置为 allOutput 以允许发送任意报文
    from opendbc.car.structs import CarParams
    p.set_safety_mode(CarParams.SafetyModel.allOutput)

    # 加载 DBC
    try:
        packer = CANPacker(DBC["mazda_2017"]["pt"])
    except Exception as e:
        print(f"加载 DBC 失败: {e}")
        sys.exit(1)

    # 读取当前 checksum（可选：读取一次并打印）
    # 这里仅作示例，实际可根据需要读取总线上的报文并解析 checksum
    print("准备发送 TURN_SWITCH 报文...")

    # 构造报文参数
    hazard = False
    left = args.left
    right = args.right
    seconds = args.seconds
    bus = 0  # 根据车辆调整总线号

    start_time = time.time()
    ctr = 0
    try:
        while time.time() - start_time < seconds:
            addr, dat, bus_ret = pack_turn_switch(packer, bus, hazard, left, right, ctr)
            p.can_send(addr, dat, bus_ret)
            print(f"[{time.strftime('%H:%M:%S')}] 发送: addr=0x{addr:03X} data={dat.hex()} bus={bus_ret} ctr={ctr}")
            ctr = (ctr + 1) & 0xF
            time.sleep(0.1)  # 10Hz 发送
    except KeyboardInterrupt:
        print("\n用户中断")
    finally:
        print("测试结束")

if __name__ == "__main__":
    main()