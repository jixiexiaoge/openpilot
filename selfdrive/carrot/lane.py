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
        """从 Params 系统更新可调参数"""
        # 采样范围参数 (影响采集数据的远近和数量)
        self.lookahead_start = float(self.params.get("LaneDetectLookaheadStart", encoding='utf8') or "6.0")  # 建议: 3.0-10.0
        self.lookahead_end = float(self.params.get("LaneDetectLookaheadEnd", encoding='utf8') or "30.0")    # 建议: 20.0-50.0
        self.num_points = int(self.params.get("LaneDetectNumPoints", encoding='utf8') or "40")              # 建议: 20-60

        # 识别阈值参数 (影响实线/虚线判定)
        self.relative_threshold_low = float(self.params.get("LaneDetectThresholdLow", encoding='utf8') or "0.095")   # 虚线上限
        self.relative_threshold_high = float(self.params.get("LaneDetectThresholdHigh", encoding='utf8') or "0.105") # 实线下限
        self.prob_threshold = float(self.params.get("LaneDetectProbThreshold", encoding='utf8') or "0.3")           # 置信度阈值

        # 时间平滑参数
        new_history_frames = int(self.params.get("LaneDetectHistoryFrames", encoding='utf8') or "5")  # 建议: 3-10

        # 更新历史队列大小（保留现有数据）
        if not hasattr(self, 'history_frames') or self.history_frames != new_history_frames:
            self.history_frames = new_history_frames
            # 保留现有数据，只改变 maxlen
            if hasattr(self, 'left_history'):
                self.left_history = deque(self.left_history, maxlen=self.history_frames)
                self.right_history = deque(self.right_history, maxlen=self.history_frames)
            else:
                self.left_history = deque(maxlen=self.history_frames)
                self.right_history = deque(maxlen=self.history_frames)


    def init_camera(self, sm, vipc_client):
        """初始化相机内参"""
        if self.intrinsics is not None:
            return True

        if sm.recv_frame['roadCameraState'] <= 0 or sm.recv_frame['deviceState'] <= 0:
            return False

        self.w = vipc_client.width
        self.h = vipc_client.height

        try:
            camera = DEVICE_CAMERAS[(str(sm['deviceState'].deviceType), str(sm['roadCameraState'].sensor))]
            self.intrinsics = camera.fcam.intrinsics

            # 根据实际分辨率缩放内参
            scale = self.w / self.FULL_RES_WIDTH
            self.intrinsics = self.intrinsics * scale
            self.intrinsics[2, 2] = 1.0

            cloudlog.info(f"Camera intrinsics initialized (Res: {self.w}x{self.h}, Scale: {scale:.2f})")
        except KeyError:
            cloudlog.warning("Unknown device type, using default intrinsics")
            self.intrinsics = np.array([[2648.0, 0.0, 964.0], [0.0, 2648.0, 604.0], [0.0, 0.0, 1.0]])
            self.intrinsics = self.intrinsics * (self.w / 1928.0)
            self.intrinsics[2, 2] = 1.0

        return True

    def publish_result(self, pm, result):
        """发布检测结果到消息系统

        Args:
            pm: PubMaster 对象
            result: update() 方法返回的结果字典
        """
        # 将检测结果存储到 Params，供 UI 或其他模块使用
        self.params.put("LaneLineTypeLeft", str(result['left']))
        self.params.put("LaneLineTypeRight", str(result['right']))
        self.params.put("LaneLineRelStdLeft", f"{result['left_rel_std']:.4f}")
        self.params.put("LaneLineRelStdRight", f"{result['right_rel_std']:.4f}")

        # 注意: 如果需要通过 cereal 消息发布，需要先在 log.capnp 中定义消息结构
        # 当前使用 Params 存储，因为不需要高频实时传输

    def update(self, sm, yuv_buf):
        """更新车道线检测

        Args:
            sm: SubMaster 对象
            yuv_buf: VisionIPC buffer

        Returns:
            dict: {'left': type, 'right': type, 'left_rel_std': float, 'right_rel_std': float}
                  type: 0=虚线, 1=实线, -1=不确定/丢失
        """
        if yuv_buf is None:
            return {'left': -1, 'right': -1, 'left_rel_std': 0.0, 'right_rel_std': 0.0}

        # YUV 数据提取
        try:
            imgff = np.frombuffer(yuv_buf.data, dtype=np.uint8).reshape(
                (len(yuv_buf.data) // yuv_buf.stride, yuv_buf.stride))
            y_data = imgff[:self.h, :self.w]
        except ValueError:
            return {'left': -1, 'right': -1, 'left_rel_std': 0.0, 'right_rel_std': 0.0}

        if not sm.updated['modelV2'] or sm.recv_frame['liveCalibration'] <= 0:
            return {'left': -1, 'right': -1, 'left_rel_std': 0.0, 'right_rel_std': 0.0}

        model = sm['modelV2']
        calib = sm['liveCalibration']

        # 坐标系转换 (4x4 矩阵)
        try:
            extrinsic_matrix_full = get_view_frame_from_calib_frame(
                calib.rpyCalib[0],  # roll
                0.0, 0.0, 0.0
            )
        except Exception as e:
            cloudlog.error(f"Calibration frame conversion failed: {e}")
            return {'left': -1, 'right': -1, 'left_rel_std': 0.0, 'right_rel_std': 0.0}

        if len(model.laneLines) < 3:
            return {'left': -1, 'right': -1, 'left_rel_std': 0.0, 'right_rel_std': 0.0}

        result = {'left': -1, 'right': -1, 'left_rel_std': 0.0, 'right_rel_std': 0.0}

        # 遍历当前车道的左右边界 (索引 1 和 2)
        for i, line_idx in enumerate([1, 2]):
            side_key = 'left' if i == 0 else 'right'
            side_key_std = 'left_rel_std' if i == 0 else 'right_rel_std'

            try:
                line = model.laneLines[line_idx]
                line_prob = model.laneLineProbs[line_idx]
            except IndexError:
                continue

            current_history = self.left_history if i == 0 else self.right_history

            if line_prob < self.prob_threshold:
                current_history.append(None)
                result[side_key] = -1
                continue

            xs, ys, zs = np.array(line.x), np.array(line.y), np.array(line.z)

            if len(xs) == 0:
                current_history.append(None)
                result[side_key] = -1
                continue

            # 采样与投影
            sample_xs = np.linspace(self.lookahead_start, self.lookahead_end, self.num_points)
            sample_ys = np.interp(sample_xs, xs, ys)
            sample_zs = np.interp(sample_xs, xs, zs)

            pixel_values = []
            for k in range(self.num_points):
                local_point = np.array([sample_xs[k], sample_ys[k], sample_zs[k]])
                local_point_homo = np.append(local_point, 1.0)
                view_point_homo = extrinsic_matrix_full.dot(local_point_homo)
                view_point = view_point_homo[:3]

                if view_point[2] <= 0:
                    continue

                u = int(view_point[0] / view_point[2] * self.intrinsics[0, 0] + self.intrinsics[0, 2])
                v = int(view_point[1] / view_point[2] * self.intrinsics[1, 1] + self.intrinsics[1, 2])

                if 0 <= u < self.w and 0 <= v < self.h:
                    pixel_values.append(int(y_data[v, u]))

            # 结果分析与平滑
            if len(pixel_values) < 10:
                current_history.append(None)
                result[side_key] = -1
                continue

            pixel_std = np.std(pixel_values)
            pixel_mean = np.mean(pixel_values)
            relative_std_current = pixel_std / max(pixel_mean, 1.0)

            # 时间平滑计算
            current_history.append(relative_std_current)
            valid_history = [x for x in current_history if x is not None]

            if len(valid_history) < 2:
                avg_rel_std = relative_std_current
            else:
                avg_rel_std = np.mean(valid_history)

            result[side_key_std] = avg_rel_std

            # 三段式判断 (基于平均相对方差)
            if avg_rel_std < self.relative_threshold_low:
                result[side_key] = 0  # 虚线
            elif avg_rel_std > self.relative_threshold_high:
                result[side_key] = 1  # 实线
            else:
                result[side_key] = -1  # 不确定

        return result


# ==============================================================================
# 主程序 (用于独立测试)
# ==============================================================================

def main():
    """独立运行模式 - 用于测试和调试"""
    detector = LaneLineDetector()
    sm = messaging.SubMaster(['modelV2', 'liveCalibration', 'deviceState', 'roadCameraState'])
    vipc_client = VisionIpcClient("camerad", VisionStreamType.VISION_STREAM_ROAD, True)

    # 可选: 如果需要发布结果到消息系统
    # pm = messaging.PubMaster(['laneLineType'])

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

        # 可选: 发布到消息系统
        # detector.publish_result(pm, result)

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