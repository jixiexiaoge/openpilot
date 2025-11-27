#!/usr/bin/env python2
# -*- coding: utf-8 -*-

import random
import time

# ----------------------------
# RadarSpeedEstimator 类
# ----------------------------
class RadarSpeedEstimator:
    def __init__(self, max_points=10):
        self.max_points = max_points
        self.points = []  # (t_ms, dist_mm)
        self.last_output_speed = None

    def reset(self):
        self.points.clear()
        self.last_output_speed = None

    def update(self, t_ms, dist_mm, has_target):
        if not has_target:
            self.reset()
            return None

        self.points.append((t_ms, dist_mm))

        if len(self.points) > self.max_points:
            self.points.pop(0)

        if len(self.points) < 3:
            return None

        t0 = self.points[0][0]
        xs = [(t - t0) for (t, d) in self.points]
        ys = [d for (t, d) in self.points]

        n = len(xs)
        sum_x = sum(xs)
        sum_y = sum(ys)
        sum_xy = sum(x * y for x, y in zip(xs, ys))
        sum_x2 = sum(x * x for x in xs)

        denom = (n * sum_x2 - sum_x * sum_x)
        if denom == 0:
            return None

        slope = (n * sum_xy - sum_x * sum_y) / denom  # mm/ms = m/s
        self.last_output_speed = slope
        return slope

# ----------------------------
# 模拟数据生成函数
# ----------------------------
def simulate_linear_motion(start_dist_mm, velocity_mm_s, steps=50, noise=5):
    """
    生成模拟数据 (t_ms, dist_mm)
    velocity_mm_s: 正值=远离，负值=靠近
    """
    t = 0
    for i in range(steps):
        dist = start_dist_mm + velocity_mm_s * (t / 1000.0)
        dist += random.uniform(-noise, noise)
        yield (t, int(dist))
        t += 100  # 每100ms一帧

# ----------------------------
# 测试函数
# ----------------------------
def test_speed_estimator():
    est = RadarSpeedEstimator(max_points=10)
    true_speed = -1.5  # m/s (靠近)
    print("真实速度: {:.3f} m/s ({:.2f} km/h)".format(true_speed, true_speed * 3.6))

    stable_threshold = 3  # 至少3个点才能开始输出
    for t_ms, dist_mm in simulate_linear_motion(
            start_dist_mm=8000,
            velocity_mm_s=true_speed * 1000,  # 转成 mm/s
            steps=60,
            noise=5):

        # 模拟目标消失
        has_target = True
        if 2000 < t_ms < 3000:
            has_target = False

        slope = est.update(t_ms, dist_mm, has_target)

        if slope is None or len(est.points) < stable_threshold:
            print("t={:4d}ms  dist={:6d}mm  speed=None".format(t_ms, dist_mm))
        else:
            m_per_s = slope       # mm/ms = m/s
            km_per_h = m_per_s * 3.6
            print("t={:4d}ms  dist={:6d}mm  speed_m_per_s={:7.3f}  speed_km_h={:7.2f}".format(
                t_ms, dist_mm, m_per_s, km_per_h))

        time.sleep(0.01)

# ----------------------------
# 入口
# ----------------------------
if __name__ == "__main__":
    test_speed_estimator()
