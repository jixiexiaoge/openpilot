#!/usr/bin/env python3
"""
现代汽车自动超车控制器 - 主程序入口
多源验证返回原车道与远超慢车距离超车优化版 v3.8
优化内容：
1：注释不重要调试打印信息
2:增加测车数据跳动滤波
"""

import sys
import os

# 添加到OpenPilot路径
sys.path.append('/data/openpilot')

# 导入自定义模块
try:
    from selfdrive.carrot.auto_overtake.config import Config
    from selfdrive.carrot.auto_overtake.vehicle_tracker import SideVehicleTracker
    from selfdrive.carrot.auto_overtake.lane_change_verification import LaneChangeVerificationSystem
    from selfdrive.carrot.auto_overtake.overtake_decision import OvertakeDecisionEngine
    from selfdrive.carrot.auto_overtake.return_strategy import ReturnStrategy
    from selfdrive.carrot.auto_overtake.status_management import StatusManager
    from selfdrive.carrot.auto_overtake.web_interface import WebInterface
    from selfdrive.carrot.auto_overtake.auto_overtake_controller import AutoOvertakeController
except ImportError:
    # 备用导入方式
    import sys
    import os
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, current_dir)
    
    from config import Config
    from vehicle_tracker import SideVehicleTracker
    from lane_change_verification import LaneChangeVerificationSystem
    from overtake_decision import OvertakeDecisionEngine
    from return_strategy import ReturnStrategy
    from status_management import StatusManager
    from web_interface import WebInterface
    from auto_overtake_controller import AutoOvertakeController

def main():
    """主函数"""
    print("="*50)
    print("现代汽车自动超车控制器 - v3.7 多源验证与远距离超车优化版")
    print("访问地址: http://<op_ip>:8088")
    print("="*50)

    controller = AutoOvertakeController()
    try:
        controller.start()
    except KeyboardInterrupt:
        print("\n收到停止信号...")
    except Exception as e:
        print(f"运行错误: {e}")
    finally:
        controller.stop()

if __name__ == "__main__":
    main()