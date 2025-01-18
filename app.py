from flask import Flask, render_template, jsonify
import cantools
import can
import json

app = Flask(__name__)

# 加载DBC文件
db = cantools.database.load_file('mazda_2017.dbc')

# 初始化存储车辆数据的字典
vehicle_data = {
    'engine_rpm': 0,        # 发动机转速
    'vehicle_speed': 0,     # 车速
    'gear': 'P',           # 档位
    'brake_pressure': 0,    # 刹车压力
    'throttle': 0,         # 油门开度
    'acc_status': False,    # ACC状态
    'blind_spot': {        # 盲区监测
        'left': False,
        'right': False
    },
    'following': {         # 跟车信息
        'distance': 0,     # 车距
        'relative_speed': 0 # 相对速度
    },
    'temp': {             # 温度
        'outdoor': 0,      # 车外温度
        'coolant': 0       # 冷却液温度
    },
    'doors': {            # 车门状态
        'fl': False,       # 前左
        'fr': False,       # 前右
        'bl': False,       # 后左
        'br': False        # 后右
    },
    'seatbelts': {        # 安全带状态
        'driver': False,    # 驾驶员
        'passenger': False  # 乘客
    },
    'lights': {           # 车灯状态
        'left_blink': False,   # 左转向灯
        'right_blink': False,  # 右转向灯
        'hazard': False,       # 危险警告灯
        'high_beam': False,    # 远光灯
        'low_beam': False,     # 近光灯
        'rear_wiper': False,   # 后雨刷
        'front_wiper': {       # 前雨刷
            'low': False,      # 低速
            'high': False      # 高速
        }
    }
}

# CAN总线数据处理函数
def process_can_message(msg):
    try:
        # 解码CAN消息
        decoded = db.decode_message(msg.arbitration_id, msg.data)

        # 根据不同的消息ID更新vehicle_data
        if msg.arbitration_id == 514:  # ENGINE_DATA
            vehicle_data['engine_rpm'] = decoded.get('RPM', 0)
            vehicle_data['vehicle_speed'] = decoded.get('SPEED', 0)
            vehicle_data['throttle'] = decoded.get('PEDAL_GAS', 0)

        elif msg.arbitration_id == 552:  # GEAR
            gear_map = {1: 'P', 2: 'R', 3: 'N', 4: 'D'}
            vehicle_data['gear'] = gear_map.get(decoded.get('GEAR', 1), 'P')

        elif msg.arbitration_id == 120:  # BRAKE
            vehicle_data['brake_pressure'] = decoded.get('BRAKE_PRESSURE', 0)

        elif msg.arbitration_id == 357:  # PEDALS
            vehicle_data['acc_status'] = decoded.get('ACC_ACTIVE', False)

        elif msg.arbitration_id == 1143:  # BSM
            vehicle_data['blind_spot']['left'] = decoded.get('LEFT_BS_STATUS', 0) > 0
            vehicle_data['blind_spot']['right'] = decoded.get('RIGHT_BS_STATUS', 0) > 0

        elif msg.arbitration_id == 1056:  # CHECK_AND_TEMP
            vehicle_data['temp']['outdoor'] = decoded.get('OUTDOOR_TEMP', 0)
            vehicle_data['temp']['coolant'] = decoded.get('COOLANT_TEMP', 0)

        elif msg.arbitration_id == 1086:  # DOORS
            vehicle_data['doors']['fl'] = decoded.get('FL', False)
            vehicle_data['doors']['fr'] = decoded.get('FR', False)
            vehicle_data['doors']['bl'] = decoded.get('BL', False)
            vehicle_data['doors']['br'] = decoded.get('BR', False)

        elif msg.arbitration_id == 832:  # SEATBELT
            vehicle_data['seatbelts']['driver'] = decoded.get('DRIVER_SEATBELT', False)
            vehicle_data['seatbelts']['passenger'] = decoded.get('PASSENGER_SEATBELT', False)

        elif msg.arbitration_id == 154:  # BLINK_INFO
            vehicle_data['lights']['left_blink'] = decoded.get('LEFT_BLINK', False)
            vehicle_data['lights']['right_blink'] = decoded.get('RIGHT_BLINK', False)
            vehicle_data['lights']['rear_wiper'] = decoded.get('REAR_WIPER_ON', False)
            vehicle_data['lights']['front_wiper']['low'] = decoded.get('WIPER_LO', False)
            vehicle_data['lights']['front_wiper']['high'] = decoded.get('WIPER_HI', False)
            vehicle_data['lights']['low_beam'] = decoded.get('LOW_BEAMS', 0) > 0
            vehicle_data['lights']['high_beam'] = decoded.get('HIGH_BEAMS', 0) > 0

        elif msg.arbitration_id == 145:  # TURN_SWITCH
            vehicle_data['lights']['hazard'] = decoded.get('HAZARD', False)

    except Exception as e:
        print(f"Error processing CAN message: {e}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/data')
def get_data():
    return jsonify(vehicle_data)

if __name__ == '__main__':
    # 初始化CAN接口
    bus = can.interface.Bus(channel='can0', bustype='socketcan')

    # 启动CAN数据接收线程
    import threading
    def can_receive():
        while True:
            msg = bus.recv()
            if msg:
                process_can_message(msg)

    threading.Thread(target=can_receive, daemon=True).start()

    # 启动Flask应用
    app.run(host='0.0.0.0', port=5000)