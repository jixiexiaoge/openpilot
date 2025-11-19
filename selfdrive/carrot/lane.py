#!/usr/bin/env python3
import time
import numpy as np
from collections import deque

from msgq.visionipc.visionipc_pyx import VisionIpcClient, VisionStreamType
import cereal.messaging as messaging
from openpilot.common.transformations.camera import get_view_frame_from_calib_frame, DEVICE_CAMERAS
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog


# ==============================================================================
# 车道线类型检测器类
# ==============================================================================

class LaneLineDetector:
    """车道线实线/虚线检测器

    通过分析车道线像素值的方差来判断车道线类型:
    - 虚线: 相对标准差较低 (间断的线)
    - 实线: 相对标准差较高 (连续的线)
    """

    # 系统常量
    FULL_RES_WIDTH = 1928  # openpilot 标准相机全分辨率宽度

    def __init__(self):
        self.params = Params()

        # 初始化状态变量（在 update_params 之前）
        self.intrinsics = None
        self.w, self.h = None, None
        self.left_history = None
        self.right_history = None

        # 从 Params 读取可调参数（会创建历史队列）
        self.update_params()

        cloudlog.info("LaneLineDetector initialized")

    def update_params(self):
        """从 Params 系统更新可调参数，使用 try-except 处理未注册的键"""
        # 采样范围参数
        try:
            self.lookahead_start = float(self.params.get("LaneDetectLookaheadStart", encoding='utf8') or "6.0")
        except Exception:
            self.lookahead_start = 6.0
            cloudlog.warning("LaneDetectLookaheadStart not found, using default: 6.0")

        try:
            self.lookahead_end = float(self.params.get("LaneDetectLookaheadEnd", encoding='utf8') or "30.0")
        except Exception:
            self.lookahead_end = 30.0
            cloudlog.warning("LaneDetectLookaheadEnd not found, using default: 30.0")

        try:
            self.num_points = int(self.params.get("LaneDetectNumPoints", encoding='utf8') or "40")
        except Exception:
            self.num_points = 40
            cloudlog.warning("LaneDetectNumPoints not found, using default: 40")

        # 识别阈值参数
        try:
            self.relative_threshold_low = float(self.params.get("LaneDetectThresholdLow", encoding='utf8') or "0.095")
        except Exception:
            self.relative_threshold_low = 0.095
            cloudlog.warning("LaneDetectThresholdLow not found, using default: 0.095")

        try:
            self.relative_threshold_high = float(self.params.get("LaneDetectThresholdHigh", encoding='utf8') or "0.105")
        except Exception:
            self.relative_threshold_high = 0.105
            cloudlog.warning("LaneDetectThresholdHigh not found, using default: 0.105")

        try:
            self.prob_threshold = float(self.params.get("LaneDetectProbThreshold", encoding='utf8') or "0.3")
        except Exception:
            self.prob_threshold = 0.3
            cloudlog.warning("LaneDetectProbThreshold not found, using default: 0.3")

        # 时间平滑参数
        try:
            new_history_frames = int(self.params.get("LaneDetectHistoryFrames", encoding='utf8') or "5")
        except Exception:
            new_history_frames = 5
            cloudlog.warning("LaneDetectHistoryFrames not found, using default: 5")

        self.history_frames = new_history_frames

        # 重新创建历史队列（如果大小改变或首次初始化）
        if self.left_history is None or self.right_history is None:
            self.left_history = deque(maxlen=self.history_frames)
            self.right_history = deque(maxlen=self.history_frames)
        elif len(self.left_history) != 0 and self.left_history.maxlen != self.history_frames:
            # 保留现有数据，只改变最大长度
            self.left_history = deque(self.left_history, maxlen=self.history_frames)
            self.right_history = deque(self.right_history, maxlen=self.history_frames)

    def init_camera(self, sm, vipc_client):
        """初始化相机内参矩阵"""
        if self.intrinsics is not None:
            return True

        if not sm.updated['deviceState'] or not sm.updated['roadCameraState']:
            return False

        try:
            device_type = str(sm['deviceState'].deviceType)
            sensor = str(sm['roadCameraState'].sensor)
            camera = DEVICE_CAMERAS[(device_type, sensor)]

            # 获取实际分辨率
            self.w = vipc_client.width
            self.h = vipc_client.height

            # 根据实际分辨率缩放内参矩阵
            scale = self.w / self.FULL_RES_WIDTH
            self.intrinsics = camera.fcam.intrinsics * scale
            self.intrinsics[2, 2] = 1.0  # 保持齐次坐标

            cloudlog.info(f"Camera initialized: {self.w}x{self.h}, device={device_type}")
            return True
        except Exception as e:
            cloudlog.error(f"Camera initialization failed: {e}")
            return False

    def update(self, sm, yuv_buf):
        """主检测逻辑"""
        result = {
            'left': -1,  # -1: 丢失/视野外, 0: 虚线, 1: 实线
            'right': -1,
            'left_rel_std': 0.0,
            'right_rel_std': 0.0
        }

        if not sm.updated['modelV2'] or not sm.updated['liveCalibration']:
            return result

        model = sm['modelV2']
        calib = sm['liveCalibration']

        # 提取 YUV 数据的 Y 平面
        try:
            imgff = np.frombuffer(yuv_buf.data, dtype=np.uint8).reshape(
                (len(yuv_buf.data) // vipc_client.stride, vipc_client.stride))
            y_data = imgff[:self.h, :self.w]
        except Exception as e:
            cloudlog.error(f"YUV extraction failed: {e}")
            return result

        # 获取外参矩阵
        try:
            extrinsic_matrix_full = get_view_frame_from_calib_frame(
                calib.rpyCalib[0],  # roll
                0.0,                # pitch (已在 calibrated frame 中处理)
                0.0,                # yaw (已在 calibrated frame 中处理)
                0.0                 # height
            )
        except Exception as e:
            cloudlog.error(f"Calibration frame conversion failed: {e}")
            return result

        # 处理左右车道线 (索引 1 和 2)
        for i, line_idx in enumerate([1, 2]):
            try:
                line = model.laneLines[line_idx]
                line_prob = model.laneLineProbs[line_idx]
            except IndexError:
                continue

            side_key = 'left' if i == 0 else 'right'
            current_history = self.left_history if i == 0 else self.right_history

            # 检查车道线置信度
            if line_prob < self.prob_threshold:
                current_history.append(None)
                continue

            # 提取车道线坐标
            xs, ys, zs = np.array(line.x), np.array(line.y), np.array(line.z)
            if len(xs) < 10:
                current_history.append(None)
                continue

            # 沿车道线采样
            sample_xs = np.linspace(self.lookahead_start, self.lookahead_end, self.num_points)
            sample_ys = np.interp(sample_xs, xs, ys)
            sample_zs = np.interp(sample_xs, xs, zs)

            pixel_values = []
            for k in range(self.num_points):
                # 使用齐次坐标
                local_point_homo = np.array([sample_xs[k], sample_ys[k], sample_zs[k], 1.0])

                # 应用完整的 4x4 变换
                view_point_homo = extrinsic_matrix_full.dot(local_point_homo)

                # 检查深度
                if view_point_homo[2] <= 0:
                    continue

                # 投影到像素坐标
                u = int(view_point_homo[0] / view_point_homo[2] * self.intrinsics[0, 0] + self.intrinsics[0, 2])
                v = int(view_point_homo[1] / view_point_homo[2] * self.intrinsics[1, 1] + self.intrinsics[1, 2])

                if 0 <= u < self.w and 0 <= v < self.h:
                    pixel_values.append(int(y_data[v, u]))

            # 结果分析
            if len(pixel_values) < 10:
                current_history.append(None)
                continue

            pixel_std = np.std(pixel_values)
            pixel_mean = np.mean(pixel_values)
            relative_std_current = pixel_std / max(pixel_mean, 1.0)

            # 时间平滑
            current_history.append(relative_std_current)
            valid_history = [x for x in current_history if x is not None]

            if len(valid_history) < 2:
                avg_rel_std = relative_std_current
            else:
                avg_rel_std = np.mean(valid_history)

            # 三段式判断
            if avg_rel_std < self.relative_threshold_low:
                result[side_key] = 0  # 虚线
            elif avg_rel_std > self.relative_threshold_high:
                result[side_key] = 1  # 实线
            else:
                result[side_key] = -1  # 不确定

            result[f'{side_key}_rel_std'] = avg_rel_std

        return result

    def publish_result(self, pm, result):
        """发布检测结果到 Params 系统"""
        try:
            self.params.put("LaneLineTypeLeft", str(result['left']))
            self.params.put("LaneLineTypeRight", str(result['right']))
            self.params.put("LaneLineRelStdLeft", f"{result['left_rel_std']:.4f}")
            self.params.put("LaneLineRelStdRight", f"{result['right_rel_std']:.4f}")
        except Exception as e:
            cloudlog.warning(f"Failed to publish results to Params: {e}")

        # 如果需要通过消息系统发布（需要先在 log.capnp 中定义消息结构）
        # if pm is not None:
        #     msg = messaging.new_message('laneLineType')
        #     msg.laneLineType.left = result['left']
        #     msg.laneLineType.right = result['right']
        #     pm.send('laneLineType', msg)


# ==============================================================================
# 主程序 (用于独立测试)
# ==============================================================================

def main():
    """独立运行模式 - 用于测试和调试"""
    detector = LaneLineDetector()
    sm = messaging.SubMaster(['modelV2', 'liveCalibration', 'deviceState', 'roadCameraState'])
    vipc_client = VisionIpcClient("camerad", VisionStreamType.VISION_STREAM_ROAD, True)

    cloudlog.info("Waiting for stream... (请确保 ./replay 正在运行)")
    while not vipc_client.connect(False):
        time.sleep(0.2)
    cloudlog.info("Stream connected! Waiting for model and calibration data...")

    # 等待相机初始化
    while True:
        sm.update(0)
        if detector.init_camera(sm, vipc_client):
            break
        time.sleep(0.1)

    cloudlog.info("Camera initialized, starting detection...")

    while True:
        sm.update(0)
        yuv_buf = vipc_client.recv()

        result = detector.update(sm, yuv_buf)

        # 发布结果到 Params（供其他模块使用）
        detector.publish_result(None, result)

        # 格式化输出
        left_type = ['虚线', '实线', '不确定/丢失'][result['left'] if result['left'] >= 0 else 2]
        right_type = ['虚线', '实线', '不确定/丢失'][result['right'] if result['right'] >= 0 else 2]

        print(f"\033[2J\033[H", end="")
        print(f"=== 车道线识别 (Res: {detector.w}x{detector.h}) ===")
        print(f"左侧: {left_type}  (AvgRel: {result['left_rel_std']:.3f})")
        print(f"右侧: {right_type}  (AvgRel: {result['right_rel_std']:.3f})")
        print("----------------------------------")

if __name__ == "__main__":
    main()