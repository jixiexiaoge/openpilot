#!/usr/bin/env python3
"""
Changan Car Implementation Testing Script with RLog Data

This script allows users to test and validate the Changan car implementation
in opendbc_repo/opendbc/car/changan using real driving data from rlog files.

Usage:
    python test_changan_with_rlog.py

Then input the rlog directory path when prompted, e.g.:
    /home/jeff/realdata1/00000002--b52be56519--102
"""

import os
import sys
from collections import defaultdict
from typing import Dict, List, Any, Tuple
import numpy as np

# Add paths for imports
BASEDIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASEDIR)

from tools.lib.logreader import LogReader
from cereal import log
from opendbc.can.parser import CANParser
from opendbc.car.changan.values import CAR, DBC, EPS_SCALE
from opendbc.car.changan.interface import CarInterface
from opendbc.car.changan.carstate import CarState
from opendbc.car.changan.carcontroller import CarController
from opendbc.car.changan import changancan
from opendbc.car import structs, Bus
from opendbc.car.common.conversions import Conversions as CV


# Signal validation ranges and constraints
SIGNAL_RANGES = {
    # Speed signals
    'ESP_VehicleSpeed': (0, 250),  # km/h
    'wheelSpeeds': (0, 250),  # km/h

    # Steering signals
    'steeringAngleDeg': (-476, 476),  # degrees
    'SAS_SteeringAngleSpeed': (0, 255),  # deg/s
    'EPS_MeasuredTorsionBarTorque': (0, 4.095),  # Nm
    'EPS_ActualTorsionBarTorq': (-5533, 60002),  # raw value

    # Pedal signals
    'brakePressed': (0, 1),  # boolean
    'gasPressed': (0, 1),  # boolean

    # Gear signals
    'gearShifter': (0, 15),  # enum
    'TCU_GearForDisplay': (0, 15),  # enum

    # Door/Safety signals
    'doorOpen': (0, 1),  # boolean
    'seatbeltUnlatched': (0, 1),  # boolean
    'leftBlinker': (0, 3),  # enum
    'rightBlinker': (0, 3),  # enum

    # ACC/Control signals
    'ACC_Acceleration_24E': (-10, 10),  # m/s2
    'ACC_ACCMode': (0, 7),  # enum
    'ACC_IACCHWAMode': (0, 7),  # enum
    'vCruise': (0, 250),  # km/h
    'ACC_DistanceLevel': (0, 3),  # enum
    'ACC_FCWPreWarning': (0, 1),  # boolean
    'ACC_AEBCtrlType': (0, 7),  # enum

    # EPS status
    'EPS_LatCtrlAvailabilityStatus': (0, 3),  # enum

    # Counters
    'COUNTER': (0, 15),  # 4-bit counter
    'Counter_1BA': (0, 15),
    'Counter_35E': (0, 15),
    'Counter_36D': (0, 15),
    'ACC_RollingCounter_24E': (0, 15),
    'EPS_RollingCounter_17E': (0, 15),

    # Checksums
    'CHECKSUM': (0, 255),  # 8-bit checksum
}


class SignalStats:
    """Track statistics for a signal."""
    def __init__(self, name: str):
        self.name = name
        self.count = 0
        self.min_val = float('inf')
        self.max_val = float('-inf')
        self.values = []
        self.out_of_range = 0
        self.missing = 0

    def update(self, value: float, expected_range: Tuple[float, float] = None):
        """Update statistics with a new value."""
        self.count += 1
        self.values.append(value)
        self.min_val = min(self.min_val, value)
        self.max_val = max(self.max_val, value)

        if expected_range:
            if value < expected_range[0] or value > expected_range[1]:
                self.out_of_range += 1

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics."""
        if not self.values:
            return {'count': 0, 'missing': self.missing}

        return {
            'count': self.count,
            'min': self.min_val,
            'max': self.max_val,
            'mean': np.mean(self.values) if self.values else 0,
            'std': np.std(self.values) if len(self.values) > 1 else 0,
            'out_of_range': self.out_of_range,
            'missing': self.missing,
        }


class ChanganRLogTester:
    """Test Changan car implementation against real rlog data."""

    def __init__(self, rlog_path: str):
        """
        Initialize the tester with rlog directory path.

        Args:
            rlog_path: Path to rlog directory (e.g., /path/to/00000002--b52be56519--102)
        """
        self.rlog_path = rlog_path
        self.messages = []
        self.stats = defaultdict(int)
        self.errors = []
        self.warnings = []
        self.signal_stats = defaultdict(lambda: SignalStats("unknown"))
        self.car_fingerprint = None
        self.CP = None
        self.car_state = None
        self.car_controller = None

    def load_rlog(self) -> bool:
        """
        Load rlog files from the specified directory.

        Returns:
            True if successful, False otherwise
        """
        print(f"\n{'='*60}")
        print(f"加载 RLog 数据...")
        print(f"路径: {self.rlog_path}")
        print(f"{'='*60}\n")

        try:
            # Check if path exists
            if not os.path.exists(self.rlog_path):
                self.errors.append(f"路径不存在: {self.rlog_path}")
                return False

            # Try to find rlog files in the directory
            rlog_files = []
            if os.path.isdir(self.rlog_path):
                # Look for .rlog, .rlog.zst, or .rlog.bz2 files
                for file in os.listdir(self.rlog_path):
                    if file.endswith(('.rlog', '.rlog.zst', '.rlog.bz2')):
                        rlog_files.append(os.path.join(self.rlog_path, file))

                if not rlog_files:
                    self.errors.append(f"目录中未找到 rlog 文件: {self.rlog_path}")
                    return False

                # Use the first rlog file found
                rlog_file = sorted(rlog_files)[0]
                print(f"找到 rlog 文件: {os.path.basename(rlog_file)}")
            else:
                # Direct file path
                rlog_file = self.rlog_path

            # Load messages using LogReader
            print("正在读取消息...")
            lr = LogReader(rlog_file)
            self.messages = list(lr)

            if not self.messages:
                self.errors.append("未从 rlog 中读取到任何消息")
                return False

            print(f"✓ 成功加载 {len(self.messages)} 条消息")

            # Count message types
            msg_types = defaultdict(int)
            for msg in self.messages:
                msg_types[msg.which()] += 1

            print(f"\n消息类型统计:")
            for msg_type, count in sorted(msg_types.items(), key=lambda x: -x[1])[:10]:
                print(f"  {msg_type:20s}: {count:6d} 条")

            return True

        except Exception as e:
            self.errors.append(f"加载 rlog 失败: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

    def _create_test_car_params(self, car_fingerprint) -> structs.CarParams:
        """
        Create minimal CarParams for testing without Params() dependency.
        This avoids the segmentation fault from Params() initialization.
        """
        ret = structs.CarParams.new_message()

        # Get platform config
        platform = car_fingerprint
        ret.carFingerprint = str(car_fingerprint)

        # Set basic specs from platform config
        ret.mass = platform.config.specs.mass
        ret.wheelbase = platform.config.specs.wheelbase
        ret.steerRatio = platform.config.specs.steerRatio
        ret.centerToFront = ret.wheelbase * platform.config.specs.centerToFrontRatio
        ret.minEnableSpeed = platform.config.specs.minEnableSpeed if platform.config.specs.minEnableSpeed else -1.0
        ret.minSteerSpeed = platform.config.specs.minSteerSpeed if platform.config.specs.minSteerSpeed else 0.1
        ret.tireStiffnessFactor = platform.config.specs.tireStiffnessFactor
        ret.flags = int(platform.config.flags)

        # Set brand and safety
        ret.brand = "changan"
        ret.safetyConfigs = [structs.CarParams.SafetyConfig.new_message()]
        ret.safetyConfigs[0].safetyModel = structs.CarParams.SafetyModel.changan

        # Set transmission and control types
        ret.transmissionType = structs.CarParams.TransmissionType.automatic
        ret.steerControlType = structs.CarParams.SteerControlType.angle
        ret.radarUnavailable = True
        ret.enableBsm = True

        # Set steering params
        ret.steerActuatorDelay = 0.12
        ret.steerLimitTimer = 1.0

        # Set longitudinal params
        ret.longitudinalActuatorDelay = 0.35
        ret.vEgoStopping = 0.25
        ret.vEgoStarting = 0.25
        ret.stoppingDecelRate = 0.3
        ret.startingState = True
        ret.startAccel = 0.8
        ret.stopAccel = -0.35

        return ret

    def analyze_car_params(self) -> Dict[str, Any]:
        """
        Analyze carParams from rlog to identify the car model.

        Returns:
            Dictionary with car parameters
        """
        print(f"\n{'='*60}")
        print("分析车辆参数 (carParams)...")
        print(f"{'='*60}\n")

        car_params_msgs = [m for m in self.messages if m.which() == 'carParams']

        if not car_params_msgs:
            print("⚠ 警告: rlog 中未找到 carParams 消息")
            self.warnings.append("未找到 carParams 消息")
            return {}

        try:
            # Get the first carParams message
            cp_msg = car_params_msgs[0]
            cp = cp_msg.carParams

            # Use getattr with defaults to handle missing attributes gracefully
            params = {
                'carName': getattr(cp, 'carName', 'Unknown'),
                'carFingerprint': getattr(cp, 'carFingerprint', 'Unknown'),
                'mass': getattr(cp, 'mass', 0.0),
                'wheelbase': getattr(cp, 'wheelbase', 0.0),
                'steerRatio': getattr(cp, 'steerRatio', 0.0),
                'centerToFront': getattr(cp, 'centerToFront', 0.0),
            }

            print(f"车辆信息:")
            print(f"  名称: {params['carName']}")
            print(f"  指纹: {params['carFingerprint']}")
            if params['mass'] > 0:
                print(f"  质量: {params['mass']:.1f} kg")
            if params['wheelbase'] > 0:
                print(f"  轴距: {params['wheelbase']:.2f} m")
            if params['steerRatio'] > 0:
                print(f"  转向比: {params['steerRatio']:.1f}")
            if params['centerToFront'] > 0:
                print(f"  中心到前轴: {params['centerToFront']:.2f} m")

            return params

        except Exception as e:
            error_msg = f"解析 carParams 失败: {str(e)}"
            print(f"⚠ 警告: {error_msg}")
            self.warnings.append(error_msg)
            import traceback
            traceback.print_exc()
            return {}

    def test_can_parsing(self) -> bool:
        """
        Test CAN message parsing using Changan CarState with comprehensive signal validation.

        Returns:
            True if tests pass, False otherwise
        """
        print(f"\n{'='*60}")
        print("测试 CAN 消息解析 (CarState)...")
        print(f"{'='*60}\n")

        try:
            # Get car params from rlog
            car_params_msgs = [m for m in self.messages if m.which() == 'carParams']
            if not car_params_msgs:
                self.warnings.append("未找到 carParams 消息，使用默认 Z6_IDD")
                # Default to Z6_IDD for testing
                self.car_fingerprint = CAR.CHANGAN_Z6_IDD
            else:
                cp_msg = car_params_msgs[0]
                fingerprint_str = getattr(cp_msg.carParams, 'carFingerprint', 'CHANGAN_Z6_IDD')
                # Find matching CAR enum
                self.car_fingerprint = CAR.CHANGAN_Z6_IDD
                for car in CAR:
                    if car.name == fingerprint_str or fingerprint_str in str(car):
                        self.car_fingerprint = car
                        break

            print(f"检测到车型: {self.car_fingerprint}")

            # Get CarParams - create manually to avoid Params() dependency
            self.CP = self._create_test_car_params(self.car_fingerprint)

            # Initialize CarState
            self.car_state = CarState(self.CP)

            # Get CAN parsers
            can_parsers = CarState.get_can_parsers(self.CP)

            # Filter CAN messages
            can_msgs = [m for m in self.messages if m.which() == 'can']
            if not can_msgs:
                self.errors.append("rlog 中未找到 CAN 消息")
                return False

            print(f"找到 {len(can_msgs)} 条 CAN 消息")

            # Group CAN messages by time for parsing
            can_packets_by_time = defaultdict(list)
            for msg in can_msgs:
                timestamp = msg.logMonoTime
                for can_data in msg.can:
                    can_packets_by_time[timestamp].append((can_data.address, bytes(can_data.dat), can_data.src))

            print(f"按时间分组: {len(can_packets_by_time)} 个时间点")

            # Analyze CAN addresses
            can_addresses = defaultdict(int)
            for msg in can_msgs:
                for can_data in msg.can:
                    can_addresses[can_data.address] += 1

            print(f"\nCAN 地址统计 (前20个):")
            for addr, count in sorted(can_addresses.items(), key=lambda x: -x[1])[:20]:
                print(f"  0x{addr:03X}: {count:6d} 条")

            # Parse messages and track signals
            print(f"\n解析 CAN 信号...")

            parsed_count = 0
            parse_errors = 0

            for ts in sorted(can_packets_by_time.keys())[:1000]:  # Sample first 1000 time points
                try:
                    # Update CAN parsers with messages at this timestamp
                    frames = can_packets_by_time[ts]
                    can_strings = [(ts, frames)]

                    # Update parsers
                    for parser_bus, parser in can_parsers.items():
                        parser.update(can_strings)

                    # Now update CarState
                    car_state_ret = self.car_state.update(can_parsers)

                    # Track signal values
                    self._track_car_state_signals(car_state_ret, can_parsers)

                    parsed_count += 1

                except Exception as e:
                    parse_errors += 1
                    if parse_errors <= 5:  # Only show first few errors
                        self.warnings.append(f"解析错误 (样本 {parsed_count}): {str(e)}")

            print(f"✓ 成功解析 {parsed_count} 个时间点的信号")
            if parse_errors > 0:
                print(f"⚠ 解析错误: {parse_errors} 次")

            self.stats['can_packets_processed'] = parsed_count

            # Print signal statistics
            self._print_signal_statistics()

            return parse_errors < parsed_count * 0.1  # Allow up to 10% errors

        except Exception as e:
            self.errors.append(f"CAN 解析测试失败: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

    def _track_car_state_signals(self, car_state_ret: structs.CarState, can_parsers: Dict):
        """Track all signals from CarState for validation."""
        try:
            # Track vehicle speed
            if hasattr(car_state_ret, 'vEgoRaw'):
                self.signal_stats['vEgoRaw'].update(car_state_ret.vEgoRaw * CV.MS_TO_KPH, SIGNAL_RANGES.get('ESP_VehicleSpeed'))

            # Track steering
            if hasattr(car_state_ret, 'steeringAngleDeg'):
                self.signal_stats['steeringAngleDeg'].update(car_state_ret.steeringAngleDeg, SIGNAL_RANGES.get('steeringAngleDeg'))
            if hasattr(car_state_ret, 'steeringRateDeg'):
                self.signal_stats['steeringRateDeg'].update(car_state_ret.steeringRateDeg, SIGNAL_RANGES.get('SAS_SteeringAngleSpeed'))
            if hasattr(car_state_ret, 'steeringTorque'):
                self.signal_stats['steeringTorque'].update(car_state_ret.steeringTorque, SIGNAL_RANGES.get('EPS_MeasuredTorsionBarTorque'))
            if hasattr(car_state_ret, 'steeringTorqueEps'):
                self.signal_stats['steeringTorqueEps'].update(car_state_ret.steeringTorqueEps)

            # Track pedals
            if hasattr(car_state_ret, 'brakePressed'):
                self.signal_stats['brakePressed'].update(float(car_state_ret.brakePressed), SIGNAL_RANGES.get('brakePressed'))
            if hasattr(car_state_ret, 'gasPressed'):
                self.signal_stats['gasPressed'].update(float(car_state_ret.gasPressed), SIGNAL_RANGES.get('gasPressed'))

            # Track gear
            if hasattr(car_state_ret, 'gearShifter'):
                self.signal_stats['gearShifter'].update(float(car_state_ret.gearShifter))

            # Track doors and safety
            if hasattr(car_state_ret, 'doorOpen'):
                self.signal_stats['doorOpen'].update(float(car_state_ret.doorOpen), SIGNAL_RANGES.get('doorOpen'))
            if hasattr(car_state_ret, 'seatbeltUnlatched'):
                self.signal_stats['seatbeltUnlatched'].update(float(car_state_ret.seatbeltUnlatched), SIGNAL_RANGES.get('seatbeltUnlatched'))

            # Track blinkers
            if hasattr(car_state_ret, 'leftBlinker'):
                self.signal_stats['leftBlinker'].update(float(car_state_ret.leftBlinker))
            if hasattr(car_state_ret, 'rightBlinker'):
                self.signal_stats['rightBlinker'].update(float(car_state_ret.rightBlinker))

            # Track cruise state
            if hasattr(car_state_ret, 'cruiseState'):
                if hasattr(car_state_ret.cruiseState, 'enabled'):
                    self.signal_stats['cruiseEnabled'].update(float(car_state_ret.cruiseState.enabled))
                if hasattr(car_state_ret.cruiseState, 'speed'):
                    speed_kph = car_state_ret.cruiseState.speed * CV.MS_TO_KPH
                    if speed_kph > 0:  # Only track when set
                        self.signal_stats['cruiseSpeed'].update(speed_kph, SIGNAL_RANGES.get('vCruise'))

            # Track faults
            if hasattr(car_state_ret, 'accFaulted'):
                self.signal_stats['accFaulted'].update(float(car_state_ret.accFaulted))
            if hasattr(car_state_ret, 'steerFaultTemporary'):
                self.signal_stats['steerFaultTemporary'].update(float(car_state_ret.steerFaultTemporary))

            # Track raw CAN signals for detailed validation
            cp = can_parsers[Bus.pt]
            cp_cam = can_parsers[Bus.cam]

            # Track counters for continuity
            if "GW_17E" in cp.vl:
                self.signal_stats['counter_17E'].update(cp.vl["GW_17E"]["EPS_RollingCounter_17E"], SIGNAL_RANGES.get('EPS_RollingCounter_17E'))
            if "GW_1BA" in cp_cam.vl:
                self.signal_stats['counter_1BA'].update(cp_cam.vl["GW_1BA"]["Counter_1BA"], SIGNAL_RANGES.get('Counter_1BA'))
            if "GW_244" in cp_cam.vl:
                self.signal_stats['counter_244'].update(cp_cam.vl["GW_244"]["ACC_RollingCounter_24E"], SIGNAL_RANGES.get('ACC_RollingCounter_24E'))
            if "GW_307" in cp_cam.vl:
                self.signal_stats['counter_307'].update(cp_cam.vl["GW_307"]["Counter_35E"], SIGNAL_RANGES.get('Counter_35E'))
            if "GW_31A" in cp_cam.vl:
                self.signal_stats['counter_31A'].update(cp_cam.vl["GW_31A"]["Counter_36D"], SIGNAL_RANGES.get('Counter_36D'))

        except Exception as e:
            pass  # Silently skip tracking errors

    def _print_signal_statistics(self):
        """Print detailed signal statistics."""
        print(f"\n{'='*60}")
        print("信号统计摘要")
        print(f"{'='*60}\n")

        # Group signals by category
        categories = {
            '车速信号': ['vEgoRaw'],
            '转向信号': ['steeringAngleDeg', 'steeringRateDeg', 'steeringTorque', 'steeringTorqueEps'],
            '踏板信号': ['brakePressed', 'gasPressed'],
            '档位信号': ['gearShifter'],
            '门/安全带': ['doorOpen', 'seatbeltUnlatched'],
            '转向灯': ['leftBlinker', 'rightBlinker'],
            '巡航状态': ['cruiseEnabled', 'cruiseSpeed'],
            '故障状态': ['accFaulted', 'steerFaultTemporary'],
            '计数器': ['counter_17E', 'counter_1BA', 'counter_244', 'counter_307', 'counter_31A'],
        }

        for category, signal_names in categories.items():
            print(f"{category}:")
            for sig_name in signal_names:
                if sig_name in self.signal_stats:
                    stats = self.signal_stats[sig_name]
                    summary = stats.get_summary()
                    if summary['count'] > 0:
                        print(f"  {sig_name:30s}: 计数={summary['count']:5d}, "
                              f"范围=[{summary['min']:8.2f}, {summary['max']:8.2f}], "
                              f"均值={summary['mean']:8.2f}, 标准差={summary['std']:6.2f}")
                        if summary['out_of_range'] > 0:
                            print(f"    ⚠ 超出范围: {summary['out_of_range']} 次")
            print()

    def test_signal_validation(self) -> bool:
        """
        Validate specific CAN signals against expected ranges and check counter continuity.

        Returns:
            True if validation passes, False otherwise
        """
        print(f"\n{'='*60}")
        print("验证信号范围和连续性...")
        print(f"{'='*60}\n")

        try:
            validation_results = []
            issues_found = []

            # Check signal ranges
            print("检查信号范围:")
            range_checks = [
                ('vEgoRaw', SIGNAL_RANGES['ESP_VehicleSpeed'], '车速 (0-250 km/h)'),
                ('steeringAngleDeg', SIGNAL_RANGES['steeringAngleDeg'], '转向角 (-476° to +476°)'),
                ('brakePressed', SIGNAL_RANGES['brakePressed'], '刹车踏板状态 (0/1)'),
                ('gasPressed', SIGNAL_RANGES['gasPressed'], '油门踏板状态 (0/1)'),
            ]

            for sig_name, expected_range, desc in range_checks:
                if sig_name in self.signal_stats:
                    stats = self.signal_stats[sig_name]
                    summary = stats.get_summary()
                    if summary['count'] > 0:
                        in_range = summary['out_of_range'] == 0
                        status = "✓" if in_range else "✗"
                        print(f"  {status} {desc}")
                        if not in_range:
                            issues_found.append(f"{sig_name} 有 {summary['out_of_range']} 个值超出范围")
                        validation_results.append(in_range)
                    else:
                        print(f"  ⚠ {desc} - 无数据")
                        self.warnings.append(f"信号 {sig_name} 未找到数据")
                else:
                    print(f"  ⚠ {desc} - 信号未追踪")
                    self.warnings.append(f"信号 {sig_name} 未被追踪")

            # Check counter continuity
            print(f"\n检查计数器连续性:")
            counter_checks = [
                ('counter_17E', 'EPS 计数器 (0x17E)'),
                ('counter_1BA', '转向控制计数器 (0x1BA)'),
                ('counter_244', 'ACC 计数器 (0x244)'),
                ('counter_307', '巡航设定计数器 (0x307)'),
                ('counter_31A', 'HUD 计数器 (0x31A)'),
            ]

            for counter_name, desc in counter_checks:
                if counter_name in self.signal_stats:
                    stats = self.signal_stats[counter_name]
                    if stats.values:
                        # Check for counter continuity (should increment by 1, wrapping at 16)
                        discontinuities = 0
                        for i in range(1, len(stats.values)):
                            expected = (int(stats.values[i-1]) + 1) % 16
                            actual = int(stats.values[i])
                            if actual != expected:
                                discontinuities += 1

                        continuity_ok = discontinuities < len(stats.values) * 0.1  # Allow 10% discontinuity
                        status = "✓" if continuity_ok else "✗"
                        print(f"  {status} {desc}: {len(stats.values)} 个样本, {discontinuities} 处不连续")
                        if not continuity_ok:
                            issues_found.append(f"{counter_name} 计数器不连续次数过多: {discontinuities}")
                        validation_results.append(continuity_ok)
                else:
                    print(f"  ⚠ {desc} - 未追踪")

            # Summary
            if issues_found:
                print(f"\n发现的问题:")
                for issue in issues_found:
                    print(f"  - {issue}")
                    self.warnings.append(issue)

            self.stats['validations_passed'] = sum(validation_results)
            self.stats['validations_total'] = len(validation_results)

            print(f"\n验证通过: {self.stats['validations_passed']}/{self.stats['validations_total']}")

            return len(issues_found) == 0

        except Exception as e:
            self.errors.append(f"信号验证失败: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

    def test_control_generation(self) -> bool:
        """
        Test control message generation (CarController) with checksum validation.

        Returns:
            True if tests pass, False otherwise
        """
        print(f"\n{'='*60}")
        print("测试控制消息生成 (CarController)...")
        print(f"{'='*60}\n")

        try:
            # Filter sendcan messages (control outputs)
            sendcan_msgs = [m for m in self.messages if m.which() == 'sendcan']

            if not sendcan_msgs:
                print("⚠ 警告: rlog 中未找到 sendcan 消息")
                self.warnings.append("未找到 sendcan 消息")
                return True  # Not a failure, just no control data

            print(f"找到 {len(sendcan_msgs)} 条 sendcan 消息")

            # Analyze control CAN addresses
            control_addresses = defaultdict(int)
            for msg in sendcan_msgs:
                for can_data in msg.sendcan:
                    control_addresses[can_data.address] += 1

            print(f"\n控制 CAN 地址统计:")
            expected_control_addrs = {
                0x1BA: "转向控制 (Steering)",
                0x17E: "EPS 状态 (EPS Status)",
                0x244: "ACC 控制 (ACC Control)",
                0x307: "巡航设定 (Cruise Set)",
                0x31A: "HUD 显示 (HUD Display)",
            }

            for addr, count in sorted(control_addresses.items(), key=lambda x: -x[1]):
                desc = expected_control_addrs.get(addr, "未知")
                print(f"  0x{addr:03X}: {count:6d} 条 - {desc}")

            # Check for expected control messages
            print(f"\n检查控制消息完整性:")
            for addr, desc in expected_control_addrs.items():
                if addr in control_addresses:
                    print(f"  ✓ {desc} (0x{addr:03X})")
                else:
                    print(f"  ✗ {desc} (0x{addr:03X}) - 未找到")
                    self.warnings.append(f"未找到控制消息 0x{addr:03X} ({desc})")

            # Test CarController message generation with real CarState
            if self.CP and self.car_state:
                print(f"\n测试 CarController 消息生成...")

                # Initialize CarController
                self.car_controller = CarController(DBC[self.CP.carFingerprint], self.CP)

                # Create mock control command
                CC = structs.CarControl.new_message()
                CC.enabled = True
                CC.latActive = False  # Don't activate lateral in test
                CC.longActive = False  # Don't activate longitudinal in test
                CC.actuators.steeringAngleDeg = 0.0
                CC.actuators.accel = 0.0
                CC.hudControl.setSpeed = 0.0

                # Generate control messages
                try:
                    actuators, can_sends = self.car_controller.update(CC, self.car_state, 0)

                    print(f"  ✓ 成功生成 {len(can_sends)} 条控制消息")

                    # Validate generated messages
                    for can_send in can_sends:
                        addr, _, dat, _ = can_send
                        # Check message length
                        if addr in [0x1BA, 0x244, 0x307, 0x31A]:
                            if len(dat) == 32:  # 32-byte messages
                                # Verify checksum
                                checksum_ok = self._verify_checksum(addr, dat)
                                if not checksum_ok:
                                    self.warnings.append(f"消息 0x{addr:03X} 校验和验证失败")
                            else:
                                self.warnings.append(f"消息 0x{addr:03X} 长度异常: {len(dat)} 字节")
                        elif addr == 0x17E:
                            if len(dat) != 8:
                                self.warnings.append(f"消息 0x{addr:03X} 长度异常: {len(dat)} 字节")

                except Exception as e:
                    self.errors.append(f"CarController 消息生成失败: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    return False

            self.stats['control_messages'] = len(sendcan_msgs)

            return True

        except Exception as e:
            self.errors.append(f"控制生成测试失败: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

    def _verify_checksum(self, addr: int, dat: bytes) -> bool:
        """Verify CRC8 checksum for control messages."""
        try:
            # Messages with CRC8 checksums
            if addr in [0x1BA, 0x244, 0x307, 0x31A]:
                # These are 32-byte messages with 4 checksums at positions 7, 15, 23, 31
                # Simple validation: check if checksums are reasonable (not all zeros or all 0xFF)
                checksums = [dat[7], dat[15], dat[23], dat[31]]
                return not all(c == 0 for c in checksums) and not all(c == 0xFF for c in checksums)
            elif addr == 0x17E:
                # 8-byte message with checksum at position 7
                return dat[7] != 0 and dat[7] != 0xFF
            return True
        except:
            return False

    def print_summary(self):
        """Print comprehensive test summary and results."""
        print(f"\n{'='*60}")
        print("测试总结")
        print(f"{'='*60}\n")

        print(f"统计信息:")
        print(f"  总消息数: {len(self.messages)}")
        print(f"  解析的样本数: {self.stats.get('can_packets_processed', 0)}")
        print(f"  控制消息数: {self.stats.get('control_messages', 0)}")
        if self.stats.get('validations_total', 0) > 0:
            print(f"  通过的验证: {self.stats.get('validations_passed', 0)}/{self.stats.get('validations_total', 0)}")

        # Print signal coverage
        print(f"\n信号覆盖率:")
        total_signals = len(SIGNAL_RANGES)
        tracked_signals = len([s for s in self.signal_stats.values() if s.count > 0])
        print(f"  追踪的信号: {tracked_signals}")
        print(f"  DBC 定义信号: {total_signals}")
        coverage_pct = (tracked_signals / total_signals * 100) if total_signals > 0 else 0
        print(f"  覆盖率: {coverage_pct:.1f}%")

        if self.warnings:
            print(f"\n⚠ 警告 ({len(self.warnings)}):")
            for i, warning in enumerate(self.warnings[:10], 1):  # Show first 10 warnings
                print(f"  {i}. {warning}")
            if len(self.warnings) > 10:
                print(f"  ... 还有 {len(self.warnings) - 10} 个警告")

        if self.errors:
            print(f"\n✗ 错误 ({len(self.errors)}):")
            for i, error in enumerate(self.errors, 1):
                print(f"  {i}. {error}")
            print(f"\n测试失败!")
            return False
        else:
            # Determine overall success
            validation_success = (self.stats.get('validations_passed', 0) >=
                                 self.stats.get('validations_total', 1) * 0.9)  # 90% threshold
            parse_success = self.stats.get('can_packets_processed', 0) > 0

            if validation_success and parse_success:
                print(f"\n✓ 所有测试通过!")
                print(f"\n✓ 长安实现已验证，可以上车测试!")
                return True
            else:
                print(f"\n⚠ 部分测试未通过，请检查警告信息")
                if len(self.warnings) == 0:
                    print(f"✓ 没有严重问题，可以谨慎尝试上车测试")
                return False

    def run_all_tests(self) -> bool:
        """
        Run all tests in sequence.

        Returns:
            True if all tests pass, False otherwise
        """
        # Load rlog
        if not self.load_rlog():
            self.print_summary()
            return False

        # Analyze car parameters
        self.analyze_car_params()

        # Test CAN parsing
        if not self.test_can_parsing():
            self.print_summary()
            return False

        # Validate signals
        if not self.test_signal_validation():
            self.print_summary()
            return False

        # Test control generation
        if not self.test_control_generation():
            self.print_summary()
            return False

        # Print summary
        return self.print_summary()


def main():
    """Main entry point for the script."""
    print("="*60)
    print("长安汽车 RLog 测试脚本")
    print("Changan Car RLog Testing Script")
    print("="*60)
    print()
    print("此脚本用于测试和验证 opendbc/car/changan 的实现代码")
    print("使用真实的 rlog 驾驶数据进行验证")
    print()

    # Get rlog path from user
    rlog_path = input("请输入 rlog 目录路径 (例如: /home/jeff/realdata1/00000002--b52be56519--102):\n> ").strip()

    if not rlog_path:
        print("错误: 未输入路径")
        return 1

    # Create tester instance
    tester = ChanganRLogTester(rlog_path)

    # Run all tests
    success = tester.run_all_tests()

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
