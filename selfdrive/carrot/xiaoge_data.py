#!/usr/bin/env python3
"""
灏忛附鏁版嵁骞挎挱妯″潡
浠庣郴缁熻幏鍙栧疄鏃舵暟鎹紝閫氳繃TCP杩炴帴浼犺緭鍒?711绔彛
"""

import json
import socket
import struct
import threading
import time
import traceback
from typing import Dict, Any, List, Tuple

import numpy as np
import cereal.messaging as messaging
from openpilot.common.realtime import Ratekeeper
from openpilot.system.hardware import PC


class XiaogeDataBroadcaster:
    # 甯搁噺瀹氫箟锛堝弬鑰?radard.py:28锛?
    RADAR_TO_CAMERA = 1.52  # 闆疯揪鐩稿浜庣浉鏈哄腑蹇冪殑鍋忕Щ锛堢背锛?
    RADAR_LAT_FACTOR = 0.5  # 鏈潵浣嶇疆棰勬祴鏃堕棿鍥犲瓙锛堢锛夛紝鍙傝€?radard.py 鐨?radar_lat_factor
    FILTER_INIT_FRAMES = 3  # 婊ゆ尝鍣ㄥ垵濮嬪寲鎵€闇€鐨勬渶灏忓抚鏁帮紙鍙傝€?radard.py:520-546 鐨?cnt > 3锛?

    # 浼樺寲锛氳溅閬撳垎绫诲拰妫€娴嬮槇鍊硷紙鍙傝€?radard.py:520-546锛?
    LANE_PROB_THRESHOLD = 0.1  # 杞﹂亾鍐呮鐜囬槇鍊硷紝鐢ㄤ簬鍖哄垎褰撳墠杞﹂亾鍜屼晶鏂硅溅閬擄紙鍙傝€?radard.py:520锛?
    CUTIN_PROB_THRESHOLD = 0.1  # Cut-in 妫€娴嬬殑杞﹂亾鍐呮鐜囬槇鍊硷紙鍙傝€?radard.py:520锛?

    # 浼樺寲锛氬巻鍙叉暟鎹厤缃�
    HISTORY_SIZE = 10  # 鍘嗗彶鏁版嵁淇濈暀甯ф暟锛岀敤浜庤绠楁í鍚戦€熷害

    # 浼樺寲锛氬姩鎬佺疆淇″害闃堝€煎弬鏁帮紙鍙傝€?radard.py:126-157 鐨勫尮閰嶉€昏緫锛?
    CONFIDENCE_BASE_THRESHOLD = 0.5  # 鍩虹缃俊搴﹂槇鍊�
    CONFIDENCE_DISTANCE_THRESHOLD = 50.0  # 璺濈闃堝€硷紙绫筹級锛岃秴杩囨璺濈瑕佹眰鏇撮珮缃俊搴�
    CONFIDENCE_DISTANCE_BOOST = 0.7  # 璺濈瓒呰繃闃堝€兼椂鐨勭疆淇″害鎻愬崌
    CONFIDENCE_VELOCITY_DIFF_THRESHOLD = 10.0  # 閫熷害宸紓闃堝€硷紙m/s锛�
    CONFIDENCE_VELOCITY_BOOST = 0.6  # 閫熷害宸紓瓒呰繃闃堝€兼椂鐨勭疆淇″害鎻愬崌

    # 浼樺寲锛氫晶鏂硅溅杈嗙瓫閫夊弬鏁帮紙鍙傝€?radard.py:560-569锛?
    SIDE_VEHICLE_MIN_DISTANCE = 5.0  # 渚ф柟杞﹁締鏈€灏忚窛绂伙紙绫筹級
    SIDE_VEHICLE_MAX_DPATH = 3.5  # 渚ф柟杞﹁締鏈€澶ц矾寰勫亸绉伙紙绫筹級

    # 浼樺寲锛氳溅閬撳搴﹁绠楀弬鏁�
    DEFAULT_LANE_HALF_WIDTH = 1.75  # 榛樿杞﹂亾鍗婂 3.5m / 2
    MIN_LANE_HALF_WIDTH = 0.1  # 鏈€灏忚溅閬撳崐瀹介槇鍊硷紙閬垮厤闄ら浂锛�
    TARGET_LANE_WIDTH_DISTANCE = 20.0  # 杞﹂亾瀹藉害璁＄畻鐨勭洰鏍囪窛绂伙紙绫筹級

    def get_ip_address(self):
        """鑾峰彇鏈満灞€鍩熺綉IP鍦板潃"""
        try:
            # 鍒涘缓涓€涓猆DP socket杩炴帴鍒板閮ㄥ湴鍧€锛堜笉闇€瑕佸疄闄呰繛鎺ユ垚鍔燂級
            # 杩欐牱鍙互鑷姩閫夋嫨姝ｇ‘鐨勭綉缁滄帴鍙P
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    def __init__(self):
        self.tcp_port = 7711  # TCP 绔彛鍙�
        self.sequence = 0
        self.device_ip = self.get_ip_address()  # 鑾峰彇鏈満IP

        # TCP 瀹㈡埛绔繛鎺ョ鐞嗭紙绾跨▼瀹夊叏锛�
        self.clients = {}  # {addr: conn}  瀛樺偍娲昏穬鐨勫鎴风杩炴帴
        self.clients_lock = threading.Lock()  # 淇濇姢瀹㈡埛绔垪琛ㄧ殑閿�
        self.server_socket = None  # TCP 鏈嶅姟鍣� socket
        self.server_running = False  # 鏈嶅姟鍣ㄨ繍琛岀姸鎬佹爣蹇�

        # 璁㈤槄娑堟伅锛堢函瑙嗚鏁版嵁锛屼笉浣跨敤闆疯揪锛�
        self.sm = messaging.SubMaster([
            'carState',
            'modelV2',
            'selfdriveState',
            # 绉婚櫎 'controlsState' - 涓嶅啀闇€瑕� longControlState
            # 绉婚櫎 'can' - 鐩插尯鏁版嵁鐩存帴浠巆arState鑾峰彇
            # 绉婚櫎 'radarState' - 绾瑙夋柟妗堬紝涓嶄娇鐢ㄩ浄杈捐瀺鍚堟暟鎹�
        ])

        # 鏃堕棿婊ゆ尝锛氱敤浜庡钩婊戜晶鏂硅溅杈嗘暟鎹紙鎸囨暟绉诲姩骞冲潎锛�
        # alpha 鍊硷細0.3 琛ㄧず鏂版暟鎹潈閲�30%锛屽巻鍙叉暟鎹潈閲�70%
        self.filter_alpha = 0.3
        self.lead_left_filtered = {'x': 0.0, 'v': 0.0, 'y': 0.0, 'vRel': 0.0, 'dPath': 0.0, 'yRel': 0.0}
        self.lead_right_filtered = {'x': 0.0, 'v': 0.0, 'y': 0.0, 'vRel': 0.0, 'dPath': 0.0, 'yRel': 0.0}
        self.lead_left_count = 0  # 杩炵画妫€娴嬭鏁帮紙鐢ㄤ簬婊ゆ尝鍒濆鍖栵級
        self.lead_right_count = 0

        # 鍘嗗彶鏁版嵁缂撳瓨锛氱敤浜庤绠楁í鍚戦€熷害锛坹vRel锛夊拰婊ゆ尝鍣ㄥ垵濮嬪寲
        # 瀛樺偍鏈€杩戝嚑甯х殑 yRel 鍜� dRel锛岀敤浜庤绠楁í鍚戦€熷害
        self.lead_left_history: List[Dict[str, float]] = []  # 瀛樺偍 {'yRel': float, 'dRel': float, 'timestamp': float}
        self.lead_right_history: List[Dict[str, float]] = []

        # 杞﹂亾绾挎暟鎹紦瀛橈細閬垮厤閲嶅璁＄畻
        # 淇锛氭坊鍔� position_valid 瀛楁锛岀紦瀛樿鍒掕矾寰勫崟璋冩€ч獙璇佺粨鏋�
        self._lane_cache = {
            'lane_xs': None,
            'left_ys': None,
            'right_ys': None,
            'position_x': None,
            'position_y': None,
            'position_valid': False,  # 鏂板锛氱紦瀛樿鍒掕矾寰勫崟璋冩€ч獙璇佺粨鏋�
            'cache_valid': False
        }

    def recvall(self, sock, n):
        """
        鎺ユ敹鎸囧畾瀛楄妭鏁扮殑鏁版嵁锛圱CP 闇€瑕佺‘淇濇帴鏀跺畬鏁存暟鎹級
        鍙傝€?carrot_man.py:765-773 鐨勫疄鐜�
        鍙傛暟:
        - sock: socket 瀵硅薄
        - n: 闇€瑕佹帴鏀剁殑瀛楄妭鏁�
        杩斿洖: 鎺ユ敹鍒扮殑鏁版嵁锛坆ytearray锛夛紝濡傛灉杩炴帴鍏抽棴鍒欒繑鍥� None
        """
        data = bytearray()
        while len(data) < n:
            packet = sock.recv(n - len(data))
            if not packet:  # 杩炴帴宸插叧闂�
                return None
            data.extend(packet)
        return data

    def send_packet_to_client(self, conn, packet):
        """
        鍚戝崟涓鎴风鍙戦€佹暟鎹寘锛圱CP 闇€瑕佺‘淇濇暟鎹畬鏁村彂閫侊級
        鍙傛暟:
        - conn: 瀹㈡埛绔繛鎺ュ璞�
        - packet: 瑕佸彂閫佺殑鏁版嵁鍖咃紙bytes锛�
        杩斿洖: 鏄惁鍙戦€佹垚鍔燂紙bool锛�
        """
        try:
            # TCP 鍙戰€佹暟鎹寘鏍煎紡: [鏁版嵁闀垮害(4瀛楄妭)][鏁版嵁]
            # 鍏堝彂閫佹暟鎹暱搴︼紙缃戠粶瀛楄妭搴忥紝big-endian锛�
            size = len(packet)
            conn.sendall(struct.pack('!I', size))
            # 鍐嶅彂閫佸疄闄呮暟鎹�
            conn.sendall(packet)
            return True
        except (socket.error, OSError):
            # 杩炴帴宸叉柇寮€鎴栧彂閫佸け璐�
            return False

    def handle_client(self, conn, addr):
        """
        澶勭悊鍗曚釜瀹㈡埛绔繛鎺�
        鏀寔瀹㈡埛绔彂閫佸懡浠わ細
        - CMD 2: 蹇冭烦鍖咃紝鍥炲 0 琛ㄧず瀛樻椿
        """
        print(f"Client connected from {addr}")

        # 灏嗗鎴风娣诲姞鍒拌繛鎺ュ垪琛紙绾跨▼瀹夊叏锛�
        with self.clients_lock:
            self.clients[addr] = conn

        try:
            while self.server_running:
                # 鎺ユ敹瀹㈡埛绔姹�(4瀛楄妭鍛戒护)
                # 濡傛灉瀹㈡埛绔彧鏄帴鏀舵暟鎹笉鍙戦€佸懡浠わ紝杩欓噷浼氶樆濉烇紝杩欐槸姝ｅ父鐨�
                # 鍙涓嶆姏鍑哄紓甯革紝杩炴帴灏变繚鎸佺潃锛屼富绾跨▼鍙互缁х画閫氳繃 broadcast_to_clients 鍙戦€佹暟鎹�
                cmd_data = self.recvall(conn, 4)

                if not cmd_data:
                    break

                cmd = struct.unpack('!I', cmd_data)[0]

                if cmd == 2:  # 蹇冭烦璇锋眰
                    # 鍝嶅簲蹇冭烦锛氬彂閫佸ぇ灏忎负0鐨勬暟鎹寘
                    try:
                        conn.sendall(struct.pack('!I', 0))
                    except (socket.error, OSError):
                        break
                # 鍙互鎵╁睍鍏朵粬鍛戒护锛屼緥濡傝姹傜壒瀹氭暟鎹�
        except Exception as e:
            print(f"Error handling client {addr}: {e}")
        finally:
            # 娓呯悊瀹㈡埛绔繛鎺�
            with self.clients_lock:
                self.clients.pop(addr, None)
            try:
                conn.close()
            except:
                pass
            print(f"Client {addr} disconnected")

    def start_tcp_server(self):
        """
        鍚姩 TCP 鏈嶅姟鍣紙鍦ㄧ嫭绔嬬嚎绋嬩腑杩愯锛�
        鍙傝€?carrot_man.py:809-878 鐨� carrot_route() 瀹炵幇
        """
        try:
            # 鍒涘缓 TCP socket
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # 璁剧疆 SO_REUSEADDR 閫夐」锛屽厑璁哥鍙ｉ噸鐢�
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # 缁戝畾鍒版墍鏈夌綉缁滄帴鍙ｇ殑鎸囧畾绔彛
            self.server_socket.bind(('0.0.0.0', self.tcp_port))
            # 寮€濮嬬洃鍚繛鎺ワ紙鏈€澶� 5 涓緟澶勭悊杩炴帴锛�
            self.server_socket.listen(5)

            self.server_running = True
            print(f"TCP server started, listening on port {self.tcp_port}")

            while self.server_running:
                try:
                    # 绛夊緟瀹㈡埛绔繛鎺ワ紙闃诲璋冪敤锛�
                    conn, addr = self.server_socket.accept()
                    # 涓烘瘡涓鎴风鍒涘缓鐙珛绾跨▼澶勭悊杩炴帴
                    client_thread = threading.Thread(
                        target=self.handle_client,
                        args=(conn, addr),
                        daemon=True  # 璁剧疆涓哄畧鎶ょ嚎绋嬶紝涓荤▼搴忛€€鍑烘椂鑷姩缁撴潫
                    )
                    client_thread.start()
                except socket.error as e:
                    if self.server_running:
                        print(f"Error accepting connection: {e}")
                    break
        except Exception as e:
            print(f"TCP server error: {e}")
            traceback.print_exc()
        finally:
            self.server_running = False
            if self.server_socket:
                try:
                    self.server_socket.close()
                except:
                    pass
            print("TCP server stopped")

    def broadcast_to_clients(self, packet):
        """
        鍚戞墍鏈夎繛鎺ョ殑瀹㈡埛绔箍鎾暟鎹寘
        鍙傛暟:
        - packet: 瑕佸彂閫佺殑鏁版嵁鍖咃紙bytes锛�
        """
        if not packet:
            return

        # 绾跨▼瀹夊叏鍦拌幏鍙栧鎴风鍒楄〃鍓湰
        with self.clients_lock:
            clients_copy = dict(self.clients)  # 鍒涘缓鍓湰锛岄伩鍏嶅湪杩唬鏃朵慨鏀瑰師瀛楀吀

        # 璁板綍闇€瑕佹竻鐞嗙殑鏂紑杩炴帴
        dead_clients = []

        # 鍚戞墍鏈夊鎴风鍙戦€佹暟鎹�
        for addr, conn in clients_copy.items():
            if not self.send_packet_to_client(conn, packet):
                # 鍙戰€佸け璐ワ紝鏍囪涓烘柇寮€杩炴帴
                dead_clients.append(addr)

        # 娓呯悊鏂紑鐨勮繛鎺�
        if dead_clients:
            with self.clients_lock:
                for addr in dead_clients:
                    self.clients.pop(addr, None)
                    try:
                        # 灏濊瘯鍏抽棴杩炴帴锛堝鏋滆繕鏈叧闂級
                        if addr in clients_copy:
                            clients_copy[addr].close()
                    except:
                        pass

    def shutdown(self):
        """
        浼橀泤鍏抽棴鏈嶅姟鍣�
        鍏抽棴鎵€鏈夊鎴风杩炴帴骞跺仠姝㈡湇鍔″櫒
        """
        print("Shutting down TCP server...")

        # 鍋滄鏈嶅姟鍣ㄨ繍琛屾爣蹇�
        self.server_running = False

        # 鍏抽棴鎵€鏈夊鎴风杩炴帴锛堢嚎绋嬪畨鍏級
        with self.clients_lock:
            for addr, conn in self.clients.items():
                try:
                    conn.close()
                    print(f"Closed connection to {addr}")
                except:
                    pass
            self.clients.clear()

        # 鍏抽棴鏈嶅姟鍣� socket
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass

        print("TCP server shutdown complete")

    def collect_car_state(self, carState) -> Dict[str, Any]:
        """鏀堕泦鏈溅鐘舵€佹暟鎹� - 绠€鍖栫増锛堝彧淇濈暀瓒呰溅鍐崇瓥蹇呴渶瀛楁锛�
        """
        # 鏁版嵁楠岃瘉锛氱‘淇� vEgo 涓烘湁鏁堝€�
        vEgo = float(carState.vEgo)
        if vEgo < 0:
            print(f"Warning: Invalid vEgo value: {vEgo}, using 0.0")
            vEgo = 0.0

        return {
            'vEgo': vEgo,  # 瀹為檯閫熷害
            'steeringAngleDeg': float(carState.steeringAngleDeg),  # 鏂瑰悜鐩樿搴�
            'leftLatDist': float(carState.leftLatDist),  # 杞﹂亾璺濈锛堣繑鍥炲師杞﹂亾锛�
            'leftBlindspot': bool(carState.leftBlindspot) if hasattr(carState, 'leftBlindspot') else False,  # 宸︾洸鍖�
            'rightBlindspot': bool(carState.rightBlindspot) if hasattr(carState, 'rightBlindspot') else False,  # 鍙崇洸鍖�
        }

    def _update_lane_cache(self, modelV2):
        """鏇存柊杞﹂亾绾挎暟鎹紦瀛橈紝閬垮厤閲嶅璁＄畻"""
        try:
            # 淇锛氶渶瑕佽嚦灏� 3 鏉＄嚎鎵嶈兘璁块棶绱㈠紩 1 鍜� 2
            if not hasattr(modelV2, 'laneLines') or len(modelV2.laneLines) < 3:
                self._lane_cache['cache_valid'] = False
                return

            # 淇锛氶獙璇佺储寮� 1 鍜� 2 鏄惁瀛樺湪锛堥渶瑕佽嚦灏� 3 涓厓绱犳墠鑳借闂储寮� 2锛�
            if len(modelV2.laneLines) <= 2:
                self._lane_cache['cache_valid'] = False
                return

            # 鎻愬彇杞﹂亾绾挎暟鎹�
            lane_xs = [float(x) for x in modelV2.laneLines[1].x]
            left_ys = [float(y) for y in modelV2.laneLines[1].y]
            right_ys = [float(y) for y in modelV2.laneLines[2].y]

            # 淇锛氶獙璇佀 x 鍧愭爣鏄惁鍗曡皟閫掑锛坣p.interp() 瑕佹眰锛�
            if not (len(lane_xs) == len(left_ys) == len(right_ys)):
                self._lane_cache['cache_valid'] = False
                return

            # 淇锛氶獙璇� x 鍧愭爣鏄惁鍗曡皟閫掑锛坣p.interp() 瑕佹眰锛�
            if len(lane_xs) < 2 or not all(lane_xs[i] < lane_xs[i + 1] for i in range(len(lane_xs) - 1)):
                self._lane_cache['cache_valid'] = False
                return

            self._lane_cache['lane_xs'] = lane_xs
            self._lane_cache['left_ys'] = left_ys
            self._lane_cache['right_ys'] = right_ys

            # 鏇存柊瑙勫垝璺緞鏁版嵁
            # 淇锛氬湪缂撳瓨鏇存柊鏃堕獙璇佸崟璋冩€э紝骞剁紦瀛橀獙璇佺粨鏋滐紝閬垮厤鍦� d_path_interp() 涓噸澶嶆鏌�
            if hasattr(modelV2, 'position') and len(modelV2.position.x) > 0:
                position_x = [float(x) for x in modelV2.position.x]
                position_y = [float(y) for y in modelV2.position.y]

                # 楠岃瘉瑙勫垝璺緞鏁版嵁闀垮害涓€鑷存€у拰鍗曡皟鎬э紝骞剁紦瀛橀獙璇佺粨鏋�
                if len(position_x) == len(position_y) and len(position_x) >= 2:
                    # 楠岃瘉 x 鍧愭爣鍗曡皟閫掑锛堝彧楠岃瘉涓€娆★紝缁撴灉缂撳瓨鍒� position_valid锛�
                    if all(position_x[i] < position_x[i + 1] for i in range(len(position_x) - 1)):
                        self._lane_cache['position_x'] = position_x
                        self._lane_cache['position_y'] = position_y
                        self._lane_cache['position_valid'] = True  # 缂撳瓨楠岃瘉缁撴灉
                    else:
                        self._lane_cache['position_x'] = None
                        self._lane_cache['position_y'] = None
                        self._lane_cache['position_valid'] = False
                else:
                    self._lane_cache['position_x'] = None
                    self._lane_cache['position_y'] = None
                    self._lane_cache['position_valid'] = False
            else:
                self._lane_cache['position_x'] = None
                self._lane_cache['position_y'] = None
                self._lane_cache['position_valid'] = None

            self._lane_cache['cache_valid'] = (
                len(self._lane_cache['lane_xs']) > 0 and
                len(self._lane_cache['left_ys']) > 0 and
                len(self._lane_cache['right_ys']) > 0
            )
        except (IndexError, AttributeError, ValueError):
            # 淇锛氫娇鐢ㄥ叿浣撶殑寮傚父绫诲瀷
            self._lane_cache['cache_valid'] = False

    def _calculate_dpath(self, dRel: float, yRel: float, yvRel: float = 0.0, vLead: float = 0.0) -> Tuple[float, float, float]:
        """
        璁＄畻杞﹁締鐩稿浜庤鍒掕矾寰勭殑妯悜鍋忕Щ (dPath) 鍜岃溅閬撳唴姒傜巼 (in_lane_prob)
        鍙傝€?radard.py:74-87 鐨� d_path() 鏂规硶

        鍙傛暟:
        - dRel: 鐩稿浜庨浄杈剧殑璺濈锛堝凡鑰冭檻 RADAR_TO_CAMERA 鍋忕Щ锛�
        - yRel: 鐩稿浜庣浉鏈虹殑妯悜浣嶇疆
        - yvRel: 妯悜閫熷害锛堢敤浜庢湭鏉ヤ綅缃娴嬶紝鍙€夛級
        - vLead: 鍓嶈溅閫熷害锛堢敤浜庢湭鏉ヤ綅缃娴嬶紝鍙€夛級

        杩斿洖: (dPath, in_lane_prob, in_lane_prob_future)
        - dPath: 鐩稿浜庤鍒掕矾寰勭殑妯悜鍋忕Щ
        - in_lane_prob: 褰撳墠鏃跺埢鍦ㄨ溅閬撳唴鐨勬鐜�
        - in_lane_prob_future: 鏈潵鏃跺埢鍦ㄨ溅閬撳唴鐨勬鐜囷紙鐢ㄤ簬 Cut-in 妫€娴嬶級
        """
        if not self._lane_cache['cache_valid']:
            return 0.0, 0.0, 0.0

        try:
            # 浼樺寲锛氱Щ闄ら噸澶嶇殑鍗曡皟鎬ф鏌ワ紝鍥犱负 cache_valid 宸茬粡淇濊瘉浜嗘暟鎹殑鏈夋晥鎬�
            # 鍗曡皟鎬ч獙璇佸凡鍦� _update_lane_cache() 涓畬鎴�
            lane_xs = self._lane_cache['lane_xs']
            left_ys = self._lane_cache['left_ys']
            right_ys = self._lane_cache['right_ys']

            def d_path_interp(dRel_val: float, yRel_val: float) -> Tuple[float, float]:
                """鍐呴儴鍑芥暟锛氳绠楁寚瀹氳窛绂诲鐨� dPath 鍜� in_lane_prob"""
                # 鍦ㄨ窛绂� dRel_val 澶勬彃鍊艰绠楀乏鍙宠溅閬撶嚎鐨勬í鍚戜綅缃�
                left_lane_y = np.interp(dRel_val, lane_xs, left_ys)
                right_lane_y = np.interp(dRel_val, lane_xs, right_ys)

                # 璁＄畻杞﹂亾涓績浣嶇疆
                center_y = (left_lane_y + right_lane_y) / 2.0

                # 璁＄畻杞﹂亾鍗婂
                # 浼樺寲锛氫娇鐢ㄧ被甯搁噺鏇夸唬榄旀硶鏁板瓧
                lane_half_width = abs(right_lane_y - left_lane_y) / 2.0
                if lane_half_width < self.MIN_LANE_HALF_WIDTH:
                    lane_half_width = self.DEFAULT_LANE_HALF_WIDTH

                # 淇锛氫娇鐢ㄦ纭殑绗﹀彿璁＄畻鐩稿浜庤溅閬撲腑蹇冪殑鍋忕Щ
                # yRel_val 鍜� center_y 閮芥槸鐩稿浜庣浉鏈虹殑锛屾墍浠ョ浉鍑忓緱鍒扮浉瀵逛簬杞﹂亾涓績鐨勫亸绉�
                dist_from_center = yRel_val - center_y

                # 璁＄畻鍦ㄨ溅閬撳唴鐨勬鐜囷紙璺濈涓績瓒婅繎锛屾鐜囪秺楂橈級
                # 鍙傝€?radard.py:82 鐨勮绠楁柟娉�
                in_lane_prob = max(0.0, 1.0 - (abs(dist_from_center) / lane_half_width))

                # 璁＄畻 dPath锛堢浉瀵逛簬瑙勫垝璺緞鐨勬í鍚戝亸绉伙級
                # 淇锛氫娇鐢ㄧ紦瀛樼殑楠岃瘉缁撴灉锛岄伩鍏嶉噸澶嶇殑鍗曡皟鎬ф鏌ワ紙鎬ц兘浼樺寲锛�
                # 鍗曡皟鎬ч獙璇佸凡鍦� _update_lane_cache() 涓畬鎴愬苟缂撳瓨鍒� position_valid
                if self._lane_cache.get('position_valid', False):
                    path_y = np.interp(dRel_val, self._lane_cache['position_x'], self._lane_cache['position_y'])
                    # 淇锛氬悓鏍蜂慨澶嶇鍙凤紝 dPath = yRel - path_y
                    dPath = yRel_val - path_y
                else:
                    dPath = dist_from_center

                return dPath, in_lane_prob

            # 璁＄畻褰撳墠鏃跺埢鐨勫€�
            dPath, in_lane_prob = d_path_interp(dRel, yRel)

            # 璁＄畻鏈潵鏃跺埢鐨勫€�(鐢ㄤ簬 Cut-in 妫€娴嬶級
            # 鍙傝€?radard.py:30-72 鐨� Track.update() 鏂规硶
            # yRel_future = yRel + yvLead * radar_lat_factor
            # dRel_future = dRel + vLead * radar_lat_factor
            future_dRel = dRel + vLead * self.RADAR_LAT_FACTOR
            future_yRel = yRel + yvRel * self.RADAR_LAT_FACTOR
            _, in_lane_prob_future = d_path_interp(future_dRel, future_yRel)

            return float(dPath), float(in_lane_prob), float(in_lane_prob_future)

        except (IndexError, ValueError, TypeError):
            # 淇锛氫娇鐢ㄥ叿浣撶殑寮傚父绫诲瀷
            # 璋冭瘯淇℃伅锛堝彲閫夛級
            # print(f"Error in _calculate_dpath: {e}")
            return 0.0, 0.0, 0.0

    def _estimate_lateral_velocity(self, current_yRel: float, current_dRel: float, history: List[Dict[str, float]]) -> float:
        """
        浼拌妯悜閫熷害锛坹vRel锛�
        閫氳繃鍘嗗彶鏁版嵁璁＄畻 yRel 鐨勫彉鍖栫巼

        鍙傛暟:
        - current_yRel: 褰撳墠妯悜浣嶇疆锛堟湭浣跨敤锛屼繚鐣欑敤浜庢帴鍙ｅ吋瀹规€э級
        - current_dRel: 褰撳墠璺濈锛堟湭浣跨敤锛屼繚鐣欑敤浜庢帴鍙ｅ吋瀹规€э級
        - history: 鍘嗗彶鏁版嵁鍒楄〃锛屽寘鍚�{'yRel': float, 'dRel': float, 'timestamp': float}

        杩斿洖: 妯悜閫熷害锛坢/s锛�
        """
        if len(history) < 2:
            return 0.0

        try:
            # 淇锛氫娇鐢ㄥ巻鍙叉暟鎹腑鏈€杩戜袱甯х殑宸€艰绠楅€熷害
            # 鍙栨渶杩戠殑涓ゅ抚
            recent = history[-2:]
            if len(recent) < 2:
                return 0.0

            dt = recent[1]['timestamp'] - recent[0]['timestamp']
            if dt <= 0:
                return 0.0

            # 淇锛氫娇鐢ㄥ巻鍙叉暟鎹腑鏈€杩戜袱甯х殑宸€硷紝鑰屼笉鏄綋鍓嶅€间笌鍘嗗彶鍊肩殑宸€�
            dyRel = recent[1]['yRel'] - recent[0]['yRel']
            yvRel = dyRel / dt

            return float(yvRel)
        except (KeyError, IndexError, ZeroDivisionError):
            # 淇锛氫娇鐢ㄥ叿浣撶殑寮傚父绫诲瀷
            return 0.0

    def _calculate_lane_width(self, modelV2) -> float:
        """
        浣跨敤杞﹂亾绾垮潗鏍囨暟鎹�璁＄畻鍦ㄧ害 20 绫冲璁＄畻杞﹂亾瀹藉害锛堜娇鐢ㄦ彃鍊兼柟娉曪級
        鍙傝€?carrot.cc:2119-2130

        浼樺寲锛氫紭鍏堜娇鐢ㄧ紦瀛樼殑鏁版嵁锛堝凡楠岃瘉鍗曡皟鎬э級锛岄伩鍏嶉噸澶嶉獙璇佸拰閲嶅鏁版嵁杞崲
        """
        try:
            # 浼樺寲锛氫紭鍏堜娇鐢ㄧ紦瀛樼殑鏁版嵁锛屽洜涓� _update_lane_cache() 宸茬粡楠岃瘉杩囧崟璋冩€э�
            # 杩欐牱鍙互閬垮厤閲嶅楠岃瘉鍜岄噸澶嶇殑鏁版嵁杞崲锛屾彁鍗囨€ц兘
            if self._lane_cache.get('cache_valid', False):
                lane_xs = self._lane_cache['lane_xs']
                left_ys = self._lane_cache['left_ys']
                right_ys = self._lane_cache['right_ys']

                # 浣跨敤绫诲父閲忔浛浠ｉ瓟娉曟暟瀛�
                target_distance = self.TARGET_LANE_WIDTH_DISTANCE

                # 妫€鏌ョ洰鏍囪窛绂绘槸鍚﹀湪鑼冨洿鍐咃紙缂撳瓨鏁版嵁宸蹭繚璇佸崟璋冩€э級
                if (
                    len(lane_xs) > 0 and
                    target_distance <= max(lane_xs) and target_distance >= min(lane_xs)
                ):

                    # 浣跨敤缂撳瓨鐨勬暟鎹繘琛屾彃鍊艰绠�
                    left_y_at_dist = np.interp(target_distance, lane_xs, left_ys)
                    right_y_at_dist = np.interp(target_distance, lane_xs, right_ys)
                    lane_width = abs(right_y_at_dist - left_y_at_dist)
                    return lane_width

            # 濡傛灉缂撳瓨鏃犳晥锛屽洖閫€鍒扮洿鎺ヤ粠 modelV2 璇诲彇锛堥渶瑕侀獙璇佸崟璋冩€э級
            # 闇€瑕佽嚦灏� 3 鏉¤溅閬撶嚎锛� 0=宸﹁矾杈圭嚎, 1=宸﹁溅閬撶嚎, 2=鍙宠溅閬撶嚎, 3=鍙宠矾杈圭嚎锛�
            if not hasattr(modelV2, 'laneLines') or len(modelV2.laneLines) < 3:
                return 0.0

            left_lane = modelV2.laneLines[1]  # 宸﹁溅閬撶嚎
            right_lane = modelV2.laneLines[2]  # 鍙宠溅閬撶嚎

            target_distance = self.TARGET_LANE_WIDTH_DISTANCE

            if (
                len(left_lane.x) > 0 and len(left_lane.y) > 0 and
                len(right_lane.x) > 0 and len(right_lane.y) > 0
            ):

                left_x = [float(x) for x in left_lane.x]
                left_y = [float(y) for y in left_lane.y]
                right_x = [float(x) for x in right_lane.x]
                right_y = [float(y) for y in right_lane.y]

                # 楠岃瘉鍒楄〃闈炵┖鍚庡啀璋冪敤 max/min锛屽苟楠岃瘉 x 鍧愭爣鍗曡皟鎬�
                # 娉ㄦ剰锛氬彧鏈夊湪缂撳瓨鏃犳晥鏃舵墠闇€瑕侀獙璇侊紝鍥犱负缂撳瓨宸茬粡楠岃瘉杩囦簡
                if (
                    len(left_x) > 0 and len(right_x) > 0 and
                    # 楠岃瘉 x 鍧愭爣鍗曡皟閫掑锛堢紦瀛樻棤鏁堟椂鎵嶉渶瑕侊級
                    len(left_x) >= 2 and all(left_x[i] < left_x[i + 1] for i in range(len(left_x) - 1)) and
                    len(right_x) >= 2 and all(right_x[i] < right_x[i + 1] for i in range(len(right_x) - 1)) and
                    # 妫€鏌ョ洰鏍囪窛绂绘槸鍚﹀湪鑼冨洿鍐�
                    target_distance <= max(left_x) and target_distance <= max(right_x) and
                    target_distance >= min(left_x) and target_distance >= min(right_x)
                ):

                    left_y_at_dist = np.interp(target_distance, left_x, left_y)
                    right_y_at_dist = np.interp(target_distance, right_x, right_y)
                    lane_width = abs(right_y_at_dist - left_y_at_dist)
                    return lane_width
        except (IndexError, ValueError, TypeError):
            # 淇锛氫娇鐢ㄥ叿浣撶殑寮傚父绫诲瀷
            pass

        return 0.0

    def collect_model_data(self, modelV2, carState=None) -> Dict[str, Any]:
        """
        鏀堕泦妯″瀷鏁版嵁 - 浼樺寲鐗堟湰
        閫氳繃 modelV2 鏁版嵁闂存帴鎺ㄦ柇渚ф柟杞﹁締鎯呭喌锛屾浛浠� radarState

        鍙傛暟:
        - modelV2: 妯″瀷鏁版嵁
        - carState: 杞﹁締鐘舵€佹暟鎹紙鍙€夛紝鐢ㄤ簬鑾峰彇鏇村噯纭殑鑷溅閫熷害锛�
        """
        data = {}

        # 淇锛氫紭鍏堜娇鐢� carState.vEgo锛堟潵鑷� CAN鎬荤嚎锛屾洿鍑嗙‘锛夛紝濡傛灉涓嶅彲鐢ㄥ垯浣跨敤妯″瀷浼拌
        v_ego = 0.0
        if carState is not None and hasattr(carState, 'vEgo'):
            v_ego = float(carState.vEgo)
        elif hasattr(modelV2, 'velocity') and len(modelV2.velocity.x) > 0:
            v_ego = float(modelV2.velocity.x[0])

        # modelVEgo 鍜� laneWidth 宸插垹闄�
        # 鏇存柊杞﹂亾绾挎暟鎹紦瀛橈紙姣忓抚鏇存柊涓€娆★紝閬垮厤閲嶅璁＄畻锛�
        self._update_lane_cache(modelV2)

        # 鑾峰彇褰撳墠鏃堕棿鎴筹紙鐢ㄤ簬璁＄畻妯悜閫熷害锛�
        current_time = time.time()

        # 鍒嗙被鎵€鏈夋娴嬪埌鐨勮溅杈嗭紙宸�/鍙�/涓溅閬擄級
        left_vehicles: List[Dict[str, Any]] = []
        right_vehicles: List[Dict[str, Any]] = []
        center_vehicles: List[Dict[str, Any]] = []

        # 閬嶅巻鎵€鏈夋娴嬭溅杈�
        for i, lead in enumerate(modelV2.leadsV3):
            lead_prob = float(lead.prob)

            # 鍔ㄦ€佺疆淇″害闃堝€硷細鏍规嵁璺濈鍜岄€熷害璋冩暣
            # 鍙傝€?radard.py:126-157 鐨勫尮閰嶉€昏緫
            x = float(lead.x[0]) if len(lead.x) > 0 else 0.0  # 绾靛悜璺濈
            v = float(lead.v[0]) if len(lead.v) > 0 else 0.0  # 閫熷害

            # 浼樺寲锛氫娇鐢ㄧ被甯搁噺閰嶇疆鍔ㄦ€佺疆淇″害闃堝€�
            # 鍔ㄦ€佽皟鏁寸疆淇″害闃堝€硷細璺濈瓒婅繙鎴栭€熷害宸紓瓒婂ぇ锛岃姹傜疆淇″害瓒婇珮
            min_prob = self.CONFIDENCE_BASE_THRESHOLD
            if x > self.CONFIDENCE_DISTANCE_THRESHOLD:
                min_prob = max(min_prob, self.CONFIDENCE_DISTANCE_BOOST)
            if abs(v - v_ego) > self.CONFIDENCE_VELOCITY_DIFF_THRESHOLD:
                min_prob = max(min_prob, self.CONFIDENCE_VELOCITY_BOOST)

            # 杩囨护浣庣疆淇″害鐩爣
            if lead_prob < min_prob:
                continue

            # 鎻愬彇杞﹁締鏁版嵁
            y = float(lead.y[0]) if len(lead.y) > 0 else 0.0  # 妯悜浣嶇疆
            a = float(lead.a[0]) if len(lead.a) > 0 else 0.0  # 鍔犻€熷害

            # 璁＄畻鐩稿閫熷害锛堜娇鐢ㄦ洿鍑嗙‘鐨勮嚜杞﹂€熷害锛�
            v_rel = v - v_ego  # 淇锛氫娇鐢� v_ego

            # 璁＄畻 dRel锛堣€冭檻闆疯揪鍒扮浉鏈虹殑鍋忕Щ锛屽弬鑰� radard.py:220-243锛�
            # 娉ㄦ剰锛氳櫧鐒朵笉浣跨敤闆疯揪锛屼絾 RADAR_TO_CAMERA 鏄浉鏈哄埌杞﹁締涓績鐨勫亸绉�
            dRel = x - self.RADAR_TO_CAMERA
            yRel = -y  # 娉ㄦ剰绗﹀彿锛歮odelV2.leadsV3[i].y 涓� yRel 绗﹀彿鐩稿弽

            # 浼拌妯悜閫熷害锛坹vRel锛� 鐢ㄤ簬鏈潵浣嶇疆棰勬祴
            # 瀵逛簬褰撳墠妫€娴嬭溅杈嗭紝浣跨敤绠€鍖栫殑鏂规硶锛氬亣璁炬í鍚戦€熷害涓庣浉瀵归€熷害鐩稿叧
            # 鍦ㄥ疄闄呭簲鐢ㄤ腑锛屽彲浠ラ€氳繃鍘嗗彶鏁版嵁璁＄畻锛岃繖閲屼娇鐢ㄧ畝鍖栦及璁�
            yvRel = 0.0  # 榛樿鍊硷紝灏嗗湪鍚庣画閫氳繃鍘嗗彶鏁版嵁鏀硅繘

            # 璁＄畻鍓嶈溅閫熷害锛坴Lead = vEgo + vRel锛�
            vLead = v_ego + v_rel  # 淇锛氫娇鐢� v_ego

            # 璁＄畻璺緞鍋忕Щ鍜岃溅閬撳唴姒傜巼锛堜娇鐢ㄧ紦瀛樺拰鏈潵浣嶇疆棰勬祴锛�
            dPath, in_lane_prob, in_lane_prob_future = self._calculate_dpath(dRel, yRel, yvRel, vLead)

            vehicle_data = {
                'x': x,
                'dRel': dRel,  # 鐩稿浜庨浄杈剧殑璺濈锛堝凡鑰冭檻 RADAR_TO_CAMERA 鍋忕Щ锛�
                'y': y,
                'yRel': yRel,  # 鐩稿浜庣浉鏈虹殑妯悜浣嶇疆
                'v': v,
                'vLead': vLead,  # 鍓嶈溅缁濆閫熷害
                'a': a,
                'vRel': v_rel  # 鐩稿閫熷害
            }

            # 涓�闆舵彁渚涘叿澶勬暟鎹�
            vehicle_data.update({
                'yvRel': yvRel,  # 妯悜閫熷害锛堢敤浜庢湭鏉ヤ綅缃娴嬶級
                'dPath': dPath,  # 璺緞鍋忕Щ
                'inLaneProb': in_lane_prob,  # 杞﹂亾鍐呮鐜�
                'inLaneProbFuture': in_lane_prob_future,  # 鏈潵杞﹂亾鍐呮鐜囷紙鐢ㄤ簬 Cut-in 妫€娴嬶級
                'prob': lead_prob,
                'timestamp': current_time  # 鏃堕棿鎴筹紝鐢ㄤ簬璁＄畻妯悜閫熷害
            })

            # 浼樺寲锛氫娇鐢ㄧ被甯搁噺閰嶇疆杞﹂亾鍒嗙被闃堝€�
            # 鏍规嵁杞﹂亾鍐呮鐜囧拰妯悜浣嶇疆鍒嗙被杞﹁締
            # 鍙傝€?radard.py:520-546 鐨勫垎绫婚€昏緫
            if in_lane_prob > self.LANE_PROB_THRESHOLD:
                # 褰撳墠杞﹂亾杞﹁締
                center_vehicles.append(vehicle_data)
            elif yRel < 0:  # 宸︿晶杞﹂亾
                left_vehicles.append(vehicle_data)
            else:  # 鍙充晶杞﹂亾
                right_vehicles.append(vehicle_data)

        # 鍓嶈溅妫€娴� - 閫夋嫨褰撳墠杞﹂亾鏈€杩戠殑鍓嶈溅锛坙ead0锛�
        # 绠€鍖栫増锛氬彧淇濈暀瓒呰溅鍐崇瓥蹇呴渶鐨勫瓧娈�
        if center_vehicles:
            # 閫夋嫨璺濈鏈€杩戠殑鍓嶈溅
            lead0 = min(center_vehicles, key=lambda v: v['x'])
            data['lead0'] = {
                'x': lead0['x'],
                'y': lead0['y'],  # 妯悜浣嶇疆锛堢敤浜庤繑鍥炲師杞﹂亾鍒ゆ柇锛�
                'v': lead0['v'],
                'prob': lead0['prob'],
            }
        elif len(modelV2.leadsV3) > 0:
            # 濡傛灉娌℃湁鏄庣‘鐨勪腑蹇冭溅閬撹溅杈嗭紝浣跨敤绗竴涓娴嬭溅杈�
            lead0 = modelV2.leadsV3[0]
            x = float(lead0.x[0]) if len(lead0.x) > 0 else 0.0
            y = float(lead0.y[0]) if len(lead0.y) > 0 else 0.0
            v = float(lead0.v[0]) if len(lead0.v) > 0 else 0.0
            data['lead0'] = {
                'x': x,
                'y': y,  # 妯悜浣嶇疆
                'v': v,
                'prob': float(lead0.prob),
            }
        else:
            data['lead0'] = {
                'x': 0.0, 'y': 0.0, 'v': 0.0, 'prob': 0.0
            }

        # 绗簩鍓嶈溅锛坙ead1锛夊凡鍒犻櫎 - 绠€鍖栫増涓嶅啀闇€瑕�
        # 浼樺寲锛氫娇鐢ㄧ被甯搁噺閰嶇疆渚ф柟杞﹁締绛涢€夊弬鏁�
        # 渚ф柟杞﹁締妫€娴� - 閫夋嫨鏈€杩戠殑宸︿晶鍜屽彸渚ц溅杈�
        # 鍙傝€?radard.py:560-569 鐨勭瓫閫夐€昏緫
        left_filtered = [
            v for v in left_vehicles
            if v['dRel'] > self.SIDE_VEHICLE_MIN_DISTANCE and abs(v['dPath']) < self.SIDE_VEHICLE_MAX_DPATH
        ]
        right_filtered = [
            v for v in right_vehicles
            if v['dRel'] > self.SIDE_VEHICLE_MIN_DISTANCE and abs(v['dPath']) < self.SIDE_VEHICLE_MAX_DPATH
        ]

        # Cut-in 妫€娴嬪凡鍒犻櫎 - 绠€鍖栫増涓嶅啀闇€瑕�
        # 閫夋嫨宸︿晶鏈€杩戠殑杞﹁締 - 绠€鍖栫増锛氬彧淇濈暀瓒呰溅鍐崇瓥蹇呴渶鐨勫瓧娈�
        if left_filtered:
            lead_left = min(left_filtered, key=lambda vehicle: vehicle['dRel'])
            data['leadLeft'] = {
                'dRel': lead_left['dRel'],  # 鐩稿浜庨浄杈剧殑璺濈
                'vRel': lead_left['vRel'],  # 鐩稿閫熷害
                'status': True,
            }
        else:
            data['leadLeft'] = {
                'dRel': 0.0,
                'vRel': 0.0,
                'status': False
            }

        # 閫夋嫨鍙充晶鏈€杩戠殑杞﹁締 - 绠€鍖栫増锛氬彧淇濈暀瓒呰溅鍐崇瓥蹇呴渶鐨勫瓧娈�
        if right_filtered:
            lead_right = min(right_filtered, key=lambda vehicle: vehicle['dRel'])
            data['leadRight'] = {
                'dRel': lead_right['dRel'],  # 鐩稿浜庨浄杈剧殑璺濈
                'vRel': lead_right['vRel'],  # 鐩稿閫熷害
                'status': True,
            }
        else:
            data['leadRight'] = {
                'dRel': 0.0,
                'vRel': 0.0,
                'status': False
            }

        # Cut-in 妫€娴嬪凡鍒犻櫎 - 绠€鍖栫増涓嶅啀闇€瑕�
        # 杞﹂亾绾跨疆淇″害 - 瓒呰溅鍐崇瓥闇€瑕�
        data['laneLineProbs'] = [
            float(modelV2.laneLineProbs[1]) if len(modelV2.laneLineProbs) >= 3 else 0.0,  # 宸﹁溅閬撶嚎缃俊搴�
            float(modelV2.laneLineProbs[2]) if len(modelV2.laneLineProbs) >= 3 else 0.0,  # 鍙宠溅閬撶嚎缃俊搴�
        ]

        # 杞﹂亾瀹藉害鍜屽彉閬撶姸鎬� - 淇濈暀锛堣秴杞﹀喅绛栭渶瑕侊級
        meta = modelV2.meta

        # Cap'n Proto 鏋氫妇绫诲瀷杞崲锛歘DynamicEnum 绫诲瀷闇€瑕佺壒娈婂鐞�
        def enum_to_int(enum_value, default=0):
            """灏� Cap'n Proto 鏋氫妇杞崲涓烘暣鏁�"""
            if enum_value is None:
                return default
            try:
                return int(enum_value)
            except (TypeError, ValueError):
                try:
                    return enum_value.raw
                except AttributeError:
                    try:
                        return enum_value.value
                    except AttributeError:
                        try:
                            return int(str(enum_value).split('.')[-1])
                        except (ValueError, AttributeError):
                            return default

        data['meta'] = {
            'laneWidthLeft': float(meta.laneWidthLeft),  # 宸﹁溅閬撳搴�
            'laneWidthRight': float(meta.laneWidthRight),  # 鍙宠溅閬撳搴�
            'laneChangeState': enum_to_int(meta.laneChangeState, 0),  # 鍙橀亾鐘舵€�
            'laneChangeDirection': enum_to_int(meta.laneChangeDirection, 0),  # 鍙橀亾鏂瑰悜
        }

        # 鏇茬巼淇℃伅 - 鐢ㄤ簬鍒ゆ柇寮亾锛堣秴杞﹀喅绛栧叧閿暟鎹級
        # 淇锛氭敼杩涚┖鍒楄〃妫€鏌ラ€昏緫锛屼娇浠ｇ爜鏇存竻鏅�
        if hasattr(modelV2, 'orientationRate') and len(modelV2.orientationRate.z) > 0:
            orientation_rate_z = [float(x) for x in modelV2.orientationRate.z]
            data['curvature'] = {
                'maxOrientationRate': max(orientation_rate_z, key=abs),  # 鏈€澶ф柟鍚戝彉鍖栫巼 (rad/s)
            }
        else:
            data['curvature'] = {'maxOrientationRate': 0.0}

        return data

    def collect_system_state(self, selfdriveState) -> Dict[str, Any]:
        """鏀堕泦绯荤粺鐘舵€�"""
        return {
            'enabled': bool(selfdriveState.enabled) if selfdriveState else False,
            'active': bool(selfdriveState.active) if selfdriveState else False,
        }

    # 绉婚櫎 collect_carrot_data() - CarrotMan 鏁版嵁宸蹭笉鍐嶉渶瑕�
    # 绉婚櫎 collect_blindspot_data() - 鐩插尯鏁版嵁宸茬洿鎺ヤ粠 carState 鑾峰彇

    def create_packet(self, data: Dict[str, Any]) -> bytes:
        """
        鍒涘缓鏁版嵁鍖�
        杩斿洖: UTF-8 缂栫爜鐨� JSON 瀛楄妭涓�
        """
        packet_data = {
            'version': 1,
            'sequence': self.sequence,
            'timestamp': time.time(),
            'ip': self.device_ip,
            'data': data
        }

        # 杞崲涓篔SON
        json_str = json.dumps(packet_data)
        packet_bytes = json_str.encode('utf-8')

        # 鐩存帴杩斿洖 JSON 瀛楄妭鏁版嵁锛岀敱鍙戦€佸嚱鏁拌礋璐ｆ坊鍔犻暱搴﹀ご
        # TCP 鍗忚鏈韩淇濊瘉鏁版嵁瀹屾暣鎬э紝鏃犻渶搴旂敤灞� CRC32 鏍￠獙

        # 妫€鏌ユ暟鎹寘澶у皬
        if len(packet_bytes) > 1024 * 1024:  # 1MB 璀﹀憡
            print(f"Warning: Large packet size {len(packet_bytes)} bytes")

        return packet_bytes

    def broadcast_data(self):
        """涓诲惊鐜細鏀堕泦鏁版嵁骞堕€氳繃 TCP 鎺ㄩ€佺粰鎵€鏈夎繛鎺ョ殑瀹㈡埛绔�"""
        rk = Ratekeeper(20, print_delay_threshold=None)  # 20Hz

        # 鍚姩 TCP 鏈嶅姟鍣紙鍦ㄧ嫭绔嬬嚎绋嬩腑杩愯锛�
        server_thread = threading.Thread(
            target=self.start_tcp_server,
            daemon=True  # 璁剧疆涓哄畧鎶ょ嚎绋�
        )
        server_thread.start()

        # 绛夊緟鏈嶅姟鍣ㄥ惎鍔�
        time.sleep(0.5)

        print(f"XiaogeDataBroadcaster started, TCP server listening on port {self.tcp_port}")

        try:
            while True:
                try:
                    # 鎬ц兘鐩戞帶
                    start_time = time.perf_counter()

                    # 鏇存柊鎵€鏈夋秷鎭�
                    self.sm.update(0)

                    # 鏀堕泦鏁版嵁
                    data = {}

                    # 鏈溅鐘舵€� - 濮嬬粓鏀堕泦锛堟暟鎹獙璇佸凡鍦� collect_car_state() 鍐呴儴瀹屾垚锛�
                    if self.sm.alive['carState']:
                        data['carState'] = self.collect_car_state(self.sm['carState'])

                    # 妯″瀷鏁版嵁
                    if self.sm.alive['modelV2']:
                        # 淇锛氫紶閫� carState 浠ヨ幏鍙栨洿鍑嗙‘鐨勮嚜杞﹂€熷害
                        carState = self.sm['carState'] if self.sm.alive['carState'] else None
                        data['modelV2'] = self.collect_model_data(self.sm['modelV2'], carState)

                    # 绯荤粺鐘舵€�
                    if self.sm.alive['selfdriveState']:
                        data['systemState'] = self.collect_system_state(
                            self.sm['selfdriveState']
                        )

                    # 鐩插尯鏁版嵁宸插寘鍚湪 carState 涓�

                    # 鎬ц兘鐩戞帶
                    processing_time = time.perf_counter() - start_time
                    if processing_time > 0.05:  # 瓒呰繃50ms
                        print(f"Warning: Slow processing detected: {processing_time * 1000:.1f}ms")

                    # 濡傛灉鏈夋暟鎹垯鎺ㄩ€佺粰鎵€鏈夎繛鎺ョ殑瀹㈡埛绔�
                    # 娉ㄦ剰锛氬鏋� openpilot 绯荤粺姝ｅ父杩愯锛岃嚦灏戜細鏈� carState 鏁版嵁
                    # 蹇冭烦鏈哄埗宸插湪 handle_client() 涓疄鐜帮紙30绉掗棿闅旓級
                    if data:
                        packet = self.create_packet(data)

                        try:
                            # 鍚戞墍鏈夎繛鎺ョ殑瀹㈡埛绔箍鎾暟鎹寘
                            self.broadcast_to_clients(packet)
                            self.sequence += 1

                            # 姣� 100 甯ф墦鍗颁竴娆℃棩蹇�
                            if self.sequence % 100 == 0:
                                with self.clients_lock:
                                    client_count = len(self.clients)
                                print(f"Sent {self.sequence} packets to {client_count} clients), last size: {len(packet)} bytes")
                        except Exception as e:
                            print(f"Failed to send packet to clients: {e}")
                    else:
                        # 濡傛灉娌℃湁鏁版嵁锛屽彂閫佷竴涓渶灏忕殑蹇冭烦鏁版嵁鍖咃紝淇濇寔杩炴帴娲昏穬
                        # 杩欐牱瀹㈡埛绔氨涓嶄細鍥犱负瓒呮椂鑰屾柇寮€杩炴帴
                        try:
                            # 鍒涘缓涓€涓渶灏忕殑蹇冭烦鏁版嵁鍖咃紙鍙寘鍚熀鏈粨鏋勶紝 data 瀛楁涓虹┖瀵硅薄锛�
                            # 娉ㄦ剰锛歞ata 瀛楁蹇呴』鏄湁鏁堢殑 JSON 瀵硅薄锛屼笉鑳戒负 null锛屽惁鍒橝ndroid 绔В鏋愪細澶辫触
                            heartbeat_packet = {
                                'version': 1,
                                'sequence': self.sequence,
                                'timestamp': time.time(),
                                'ip': self.device_ip,
                                'data': {}  # 绌哄璞★紝鑰屼笉鏄痭ull锛岀‘淇滱ndroid 绔兘姝ｇ‘瑙ｆ瀽
                            }
                            json_str = json.dumps(heartbeat_packet)
                            packet_bytes = json_str.encode('utf-8')
                            self.broadcast_to_clients(packet_bytes)
                            self.sequence += 1
                        except Exception:
                            # 蹇冭烦鍖呭彂閫佸け璐ヤ笉褰卞搷涓绘祦绋�
                            pass

                    rk.keep_time()

                except KeyboardInterrupt:
                    # 鎹曡幏 Ctrl+C锛屼紭闆呭叧闂�
                    print("\nReceived shutdown signal, closing gracefully...")
                    break
                except Exception as e:
                    print(f"XiaogeDataBroadcaster error: {e}")
                    traceback.print_exc()
                    time.sleep(1)
        finally:
            # 纭繚浼橀泤鍏抽棴
            self.shutdown()


def main():
    broadcaster = XiaogeDataBroadcaster()
    broadcaster.broadcast_data()


if __name__ == "__main__":
    main()