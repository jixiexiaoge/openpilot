#!/usr/bin/env python3
import os
import sys
import time
import numpy as np
import cv2  # 虽然代码中未使用 cv2 库，但保留您的原导入
from collections import deque

# ==========================================
# 1. 路径配置与库导入
# ==========================================
BASE_PATH = os.path.dirname(os.path.abspath(__file__))
if BASE_PATH not in sys.path:
    sys.path.append(BASE_PATH)

MSGQ_PATH = os.path.join(BASE_PATH, "msgq_repo")
if MSGQ_PATH not in sys.path:
    sys.path.append(MSGQ_PATH)

try:
    from msgq.visionipc.visionipc_pyx import VisionIpcClient, VisionStreamType
    import cereal.messaging as messaging
    from common.transformations.camera import get_view_frame_from_calib_frame, DEVICE_CAMERAS
    print("✅ 成功加载所有依赖库")
except ImportError as e:
    print(f"❌ 库加载失败: {e}")
    sys.exit(1)

# ==========================================
# 2. 核心参数设置
# ==========================================
# 采样范围参数
LOOKAHEAD_START = 6.0
LOOKAHEAD_END = 30.0
NUM_POINTS = 40

# 置信度阈值
PROB_THRESHOLD = 0.3

# 系统常量
FULL_RES_WIDTH = 1928

# 最终阈值修正：根据实际数据调整，缩小不确定缓冲区
RELATIVE_THRESHOLD_LOW = 0.095
RELATIVE_THRESHOLD_HIGH = 0.105

# 时间平滑设置
HISTORY_FRAMES = 5
LEFT_HISTORY = deque(maxlen=HISTORY_FRAMES)
RIGHT_HISTORY = deque(maxlen=HISTORY_FRAMES)

# 全局变量
INTRINSICS = None
W, H = None, None

def main():
    global INTRINSICS, W, H

    # 初始化 SubMaster 和 VisionIpcClient
    sm = messaging.SubMaster(['modelV2', 'liveCalibration', 'deviceState', 'roadCameraState'])
    vipc_client = VisionIpcClient("camerad", VisionStreamType.VISION_STREAM_ROAD, True)

    print("\n等待 openpilot 服务启动...")
    print("(请确保 openpilot 正在运行)")
    connection_timeout = 30  # 连接超时时间（秒）
    start_time = time.time()
    while not vipc_client.connect(False):
        if time.time() - start_time > connection_timeout:
            print("❌ 连接超时：无法连接到 camerad 服务")
            print("   请检查 openpilot 是否正在运行")
            sys.exit(1)
        time.sleep(0.2)
    print("✅ 视频流已连接！等待模型和配置数据...")

    # ==========================================
    # 3. 动态获取内参并缩放
    # ==========================================
    print("⏳ 正在获取相机配置...")
    config_timeout = 10  # 配置获取超时时间（秒）
    config_start_time = time.time()
    while sm.recv_frame['roadCameraState'] <= 0 or sm.recv_frame['deviceState'] <= 0:
        if time.time() - config_start_time > config_timeout:
            print("❌ 配置获取超时：无法获取相机配置信息")
            print("   请检查 openpilot 服务是否正常运行")
            sys.exit(1)
        sm.update(0)
        time.sleep(0.1)

    W = vipc_client.width
    H = vipc_client.height

    try:
        camera = DEVICE_CAMERAS[(str(sm['deviceState'].deviceType), str(sm['roadCameraState'].sensor))]
        INTRINSICS = camera.fcam.intrinsics

        # 根据实际分辨率缩放内参
        scale = W / FULL_RES_WIDTH
        INTRINSICS = INTRINSICS * scale
        INTRINSICS[2, 2] = 1.0  # 确保最后一项保持 1.0

        print(f"✅ 内参矩阵获取成功 (Res: {W}x{H}, Scale: {scale:.2f})")
    except KeyError:
        print("❌ 无法识别设备类型，使用默认内参。")
        INTRINSICS = np.array([[2648.0, 0.0, 964.0], [0.0, 2648.0, 604.0], [0.0, 0.0, 1.0]])
        INTRINSICS = INTRINSICS * (W / 1928.0)
        INTRINSICS[2, 2] = 1.0


    # 连接状态跟踪
    consecutive_errors = 0
    MAX_CONSECUTIVE_ERRORS = 10  # 最大连续错误次数

    while True:
        try:
            # 更新消息订阅，使用超时确保实时性
            sm.update(100)  # 100ms 超时，避免阻塞太久

            # 接收视频帧（非阻塞）
            yuv_buf = vipc_client.recv()

            if yuv_buf is None:
                consecutive_errors += 1
                if consecutive_errors > MAX_CONSECUTIVE_ERRORS:
                    print("❌ 连续接收失败，尝试重新连接...", file=sys.stderr)
                    if not vipc_client.connect(False):
                        print("❌ 重连失败，等待后重试...", file=sys.stderr)
                        time.sleep(1.0)
                    else:
                        consecutive_errors = 0
                        print("✅ 重连成功", file=sys.stderr)
                continue

            # ==========================================
            # 4. YUV 数据提取 (考虑 Stride)
            # ==========================================
            try:
                imgff = np.frombuffer(yuv_buf.data, dtype=np.uint8).reshape(
                    (len(yuv_buf.data) // vipc_client.stride, vipc_client.stride))
                y_data = imgff[:H, :W] # 提取 Y 分量
            except (ValueError, AttributeError) as e:
                consecutive_errors += 1
                if consecutive_errors <= 3:  # 只打印前几次错误
                    print(f"⚠️  数据提取错误: {e}", file=sys.stderr)
                continue

            # 检查必要的数据是否已更新
            if not sm.updated['modelV2'] or sm.recv_frame['liveCalibration'] <= 0:
                continue

            # 重置错误计数
            consecutive_errors = 0

            model = sm['modelV2']
            calib = sm['liveCalibration']

            # ==========================================
            # 5. 坐标系转换 (使用完整的 4x4 矩阵)
            # ==========================================
            try:
                extrinsic_matrix_full = get_view_frame_from_calib_frame(
                    calib.rpyCalib[0],  # roll
                    0.0,                # pitch (使用 0.0)
                    0.0,                # yaw (使用 0.0)
                    0.0                 # height (使用 0.0)
                )
            except Exception as e:
                print(f"⚠️  坐标系转换错误: {e}", file=sys.stderr)
                continue

            output_lines = []
            is_debug_printed = False

            # 遍历当前车道的左右边界 (索引 1 和 2)
            for i, line_idx in enumerate([1, 2]):

                # --- 数据获取与采样 ---
                try:
                    line = model.laneLines[line_idx]
                    line_prob = model.laneLineProbs[line_idx]
                except IndexError:
                    output_lines.append("数据越界")
                    continue

                side_name = "左侧" if i == 0 else "右侧"

                if line_prob < PROB_THRESHOLD:
                    # \033[90m 是灰色
                    output_lines.append(f"{side_name}: \033[90m丢失 (Prob low)\033[0m")
                    (LEFT_HISTORY if i == 0 else RIGHT_HISTORY).append(None)
                    continue

                xs, ys, zs = np.array(line.x), np.array(line.y), np.array(line.z)

                if len(xs) == 0:
                    output_lines.append(f"{side_name}: 数据空")
                    (LEFT_HISTORY if i == 0 else RIGHT_HISTORY).append(None)
                    continue

                # 插值采样
                sample_xs = np.linspace(LOOKAHEAD_START, LOOKAHEAD_END, NUM_POINTS)
                sample_ys = np.interp(sample_xs, xs, ys)
                sample_zs = np.interp(sample_xs, xs, zs)

                pixel_values = []

                # 投影到像素坐标并采样亮度
                for k in range(NUM_POINTS):
                    local_point = np.array([sample_xs[k], sample_ys[k], sample_zs[k]])
                    local_point_homo = np.append(local_point, 1.0)

                    # 世界坐标 -> 视图坐标
                    view_point_homo = extrinsic_matrix_full.dot(local_point_homo)
                    view_point = view_point_homo[:3]

                    if view_point[2] <= 0: continue # 过滤掉在相机后面的点

                    # 视图坐标 -> 像素坐标
                    u = int(view_point[0] / view_point[2] * INTRINSICS[0, 0] + INTRINSICS[0, 2])
                    v = int(view_point[1] / view_point[2] * INTRINSICS[1, 1] + INTRINSICS[1, 2])

                    # 调试信息 (只打印第一个点)
                    if not is_debug_printed and k == 0 and 0 <= u < W and 0 <= v < H:
                        print(f"Debug: RPY={calib.rpyCalib[0]:.2f}, Local={local_point}, Pixels=(u={u}, v={v})", file=sys.stderr)
                        is_debug_printed = True

                    if 0 <= u < W and 0 <= v < H:
                        pixel_values.append(int(y_data[v, u])) # 采样 Y 分量亮度值

                # --- 结果分析与平滑 ---
                if len(pixel_values) < 10:
                    # \033[93m 是黄色
                    output_lines.append(f"{side_name}: \033[93m视野外\033[0m")
                    (LEFT_HISTORY if i == 0 else RIGHT_HISTORY).append(None)
                    continue

                pixel_std = np.std(pixel_values)
                pixel_mean = np.mean(pixel_values)
                relative_std_current = pixel_std / max(pixel_mean, 1.0)

                # 时间平滑：将当前相对标准差加入历史记录
                current_history = (LEFT_HISTORY if i == 0 else RIGHT_HISTORY)
                current_history.append(relative_std_current)
                valid_history = [x for x in current_history if x is not None]

                if len(valid_history) < 2:
                    avg_rel_std = relative_std_current
                else:
                    avg_rel_std = np.mean(valid_history)

                # 使用平均相对方差和新阈值进行三段式判断
                if avg_rel_std < RELATIVE_THRESHOLD_LOW:
                    status = "\033[91m【虚线】\033[0m" # 红色
                elif avg_rel_std > RELATIVE_THRESHOLD_HIGH:
                    status = "\033[92m【实线】\033[0m" # 绿色
                else:
                    status = "\033[93m【不确定】\033[0m" # 黄色

                # 改进：输出均值、标准差和平均相对标准差
                output_lines.append(f"{side_name}: {status} (Std:{pixel_std:.1f}, Mean:{pixel_mean:.1f}, AvgRel:{avg_rel_std:.3f})")

            # 刷新显示
            # \033[2J 清空屏幕, \033[H 移动光标到左上角
            print(f"\033[2J\033[H", end="")
            print(f"=== 车道线识别 (实时模式 - Res: {W}x{H}) ===")

            print(output_lines[0] if len(output_lines) > 0 else "---")
            print(output_lines[1] if len(output_lines) > 1 else "---")
            print("----------------------------------")

        except KeyboardInterrupt:
            print("\n\n程序被用户中断")
            break
        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors <= 5:  # 只打印前几次严重错误
                print(f"❌ 处理错误: {e}", file=sys.stderr)
                import traceback
                traceback.print_exc()
            if consecutive_errors > MAX_CONSECUTIVE_ERRORS:
                print("❌ 错误过多，程序退出", file=sys.stderr)
                break
            time.sleep(0.1)  # 错误后短暂等待
            continue

if __name__ == "__main__":
    main()