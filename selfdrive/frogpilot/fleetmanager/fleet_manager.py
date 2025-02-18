#!/usr/bin/env python3
# otisserv - Copyright (c) 2019-, Rick Lan, dragonpilot community, and a number of other of contributors.
# Fleet Manager - [actuallylemoncurd](https://github.com/actuallylemoncurd), [AlexandreSato](https://github.com/alexandreSato),
# [ntegan1](https://github.com/ntegan1), [royjr](https://github.com/royjr), and [sunnyhaibin] (https://github.com/sunnypilot)
# Almost everything else - ChatGPT
# dirty PR pusher - mike8643
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
import os
import secrets

from flask import Flask, jsonify, render_template, Response, request, send_from_directory, redirect, url_for, abort, Blueprint
from openpilot.common.realtime import set_core_affinity
import openpilot.selfdrive.frogpilot.fleetmanager.helpers as fleet
from openpilot.system.hardware.hw import Paths
from openpilot.common.swaglog import cloudlog
import traceback
from ftplib import FTP
from selfdrive.frogpilot.fleetmanager.helpers import save_location, get_current_location

from openpilot.common.params import Params
from cereal import log, messaging
import time
from functools import wraps

# 修正导入路径
from openpilot.opendbc_repo.opendbc.car.interfaces import CarInterfaceBase
from openpilot.opendbc_repo.opendbc.car.values import PLATFORMS

# 在文件开头附近添加这个全局变量
sm = messaging.SubMaster(['carState'])

app = Flask(__name__)
bp = Blueprint("fleet_manager", __name__)

@bp.route("/amap_addr_input", methods=["GET", "POST"])
def amap_addr_input():
    try:
        if request.method == "POST":
            # 处理导航请求
            lat = request.form.get("lat")
            lon = request.form.get("lon")
            save_type = request.form.get("save_type", "recent")  # 默认为recent
            name = request.form.get("name", "")

            if lat is not None and lon is not None:
                try:
                    lat_float = float(lat)
                    lon_float = float(lon)
                    if save_location(lat_float, lon_float, save_type, name):
                        return redirect(url_for("fleet_manager.amap_addr_input"))
                    else:
                        return render_template("error.html", error="Failed to save location")
                except ValueError as e:
                    print(f"Error converting coordinates: {e}")
                    return render_template("error.html", error="Invalid coordinates format")
            else:
                return render_template("error.html", error="Missing coordinates")

        # GET 请求显示地图
        try:
            current_lat, current_lon = get_current_location()
            return render_template(
                "amap_addr_input.html",
                lat=current_lat,
                lon=current_lon
            )
        except Exception as e:
            print(f"Error getting current location: {e}")
            # 使用默认坐标
            return render_template(
                "amap_addr_input.html",
                lat=39.90923,
                lon=116.397428
            )

    except Exception as e:
        print(f"Error in amap_addr_input: {e}")
        traceback.print_exc()
        return render_template("error.html", error=str(e))

@bp.route("/")
def home_page():
  return render_template("index.html")

@bp.errorhandler(500)
def internal_error(exception):
  print('500 error caught')
  tberror = traceback.format_exc()
  return render_template("error.html", error=tberror)

@bp.route("/footage/full/<cameratype>/<route>")
def full(cameratype, route):
  chunk_size = 1024 * 512  # 5KiB
  file_name = cameratype + (".ts" if cameratype == "qcamera" else ".hevc")
  vidlist = "|".join(Paths.log_root() + "/" + segment + "/" + file_name for segment in fleet.segments_in_route(route))

  def generate_buffered_stream():
    with fleet.ffmpeg_mp4_concat_wrap_process_builder(vidlist, cameratype, chunk_size) as process:
      for chunk in iter(lambda: process.stdout.read(chunk_size), b""):
        yield bytes(chunk)
  return Response(generate_buffered_stream(), status=200, mimetype='video/mp4')

@bp.route("/footage/full/rlog/<route>/<segment>")
def download_rlog(route, segment):
  file_name = Paths.log_root() + route + "--" + segment + "/"
  print("download_route=", route, file_name, segment)
  return send_from_directory(file_name, "rlog", as_attachment=True)

@bp.route("/footage/full/qcamera/<route>/<segment>")
def download_qcamera(route, segment):
  file_name = Paths.log_root() + route + "--" + segment + "/"
  print("download_route=", route, file_name, segment)
  return send_from_directory(file_name, "qcamera.ts", as_attachment=True)

@bp.route("/footage/full/fcamera/<route>/<segment>")
def download_fcamera(route, segment):
  file_name = Paths.log_root() + route + "--" + segment + "/"
  print("download_route=", route, file_name, segment)
  return send_from_directory(file_name, "fcamera.hevc", as_attachment=True)

@bp.route("/footage/full/dcamera/<route>/<segment>")
def download_dcamera(route, segment):
  file_name = Paths.log_root() + route + "--" + segment + "/"
  print("download_route=", route, file_name, segment)
  return send_from_directory(file_name, "dcamera.hevc", as_attachment=True)


def upload_folder_to_ftp(local_folder, directory, remote_path):
    from tqdm import tqdm  # tqdm���� ���� �� ǥ��
    ftp_server = "shind0.synology.me"
    ftp_port = 8021
    ftp_username = "carrotpilot"
    ftp_password = "Ekdrmsvkdlffjt7710"
    ftp = FTP()
    ftp.connect(ftp_server, ftp_port)
    ftp.login(ftp_username, ftp_password)

    try:
        print(f"Create remote path = {directory}")
        try:
          ftp.mkd(directory)
        except Exception as e:
          print(f"Directory creation failed: {e}")
        ftp.cwd(directory)
        try:
          ftp.mkd(remote_path)
        except Exception as e:
          print(f"Directory creation failed: {e}")
        ftp.cwd(remote_path)

        # ���� ������ ��� ���� ��������
        files = [
            os.path.join(root, filename)
            for root, _, filenames in os.walk(local_folder)
            for filename in filenames
        ]

        # tqdm�� ����� ���� �� ǥ��
        with tqdm(total=len(files), desc="Uploading Files", unit="file") as pbar:
            for local_file in files:
                filename = os.path.basename(local_file)
                if filename in ['rlog', 'qcamera.ts']:
                  try:
                      with open(local_file, 'rb') as file:
                          ftp.storbinary(f'STOR {filename}', file)
                          print(f"Uploaded: {local_file} -> {filename}")
                  except Exception as e:
                      print(f"Failed to upload {local_file}: {e}")

                  pbar.update(1)  # ���� �� ������Ʈ

        ftp.quit()
        return True
    except Exception as e:
        print(f"FTP Upload Error: {e}")
        return False

@bp.route("/footage/full/upload_carrot/<route>/<segment>")
def upload_carrot(route, segment):
    from openpilot.common.params import Params

    local_folder = Paths.log_root() + f"{route}--{segment}"

    # ������ �����ϴ��� Ȯ��
    if not os.path.isdir(local_folder):
        print(f"Folder not found: {local_folder}")
        return abort(404, "Folder not found")

    car_selected = Params().get("CarName")
    if car_selected is None:
      car_selected = "none"
    else:
      car_selected = car_selected.decode('utf-8')

    directory = "routes " + car_selected + " " + Params().get("DongleId").decode('utf-8')

    # FTP�� ������ ���� ���ε� ����
    #remote_path = f"{directory}/{route}--{segment}"
    success = upload_folder_to_ftp(local_folder, directory, f"{route}--{segment}")

    if success:
        return "All files uploaded successfully", 200
    else:
        return "Failed to upload files", 500

@bp.route("/footage/<cameratype>/<segment>")
def fcamera(cameratype, segment):
  if not fleet.is_valid_segment(segment):
    return render_template("error.html", error="invalid segment")
  file_name = Paths.log_root() + "/" + segment + "/" + cameratype + (".ts" if cameratype == "qcamera" else ".hevc")
  return Response(fleet.ffmpeg_mp4_wrap_process_builder(file_name).stdout.read(), status=200, mimetype='video/mp4')


@bp.route("/footage/<route>")
def route(route):
  if len(route) != 20:
    return render_template("error.html", error="route not found")

  if str(request.query_string) == "b''":
    query_segment = "0"
    query_type = "qcamera"
  else:
    query_segment = (str(request.query_string).split(","))[0][2:]
    query_type = (str(request.query_string).split(","))[1][:-1]

  links = ""
  segments = ""
  for segment in fleet.segments_in_route(route):
    links += "<a href='"+route+"?"+segment.split("--")[2]+","+query_type+"'>"+segment+"</a><br>"
    segments += "'"+segment+"',"
  return render_template("route.html", route=route, query_type=query_type, links=links, segments=segments, query_segment=query_segment)


@bp.route("/footage/")
@bp.route("/footage")
def footage():
  route_paths = fleet.all_routes()
  gifs = []
  for route_path in route_paths:
    input_path = Paths.log_root() + route_path + "--0/qcamera.ts"
    output_path = Paths.log_root() + route_path + "--0/preview.gif"
    fleet.video_to_img(input_path, output_path)
    gif_path = route_path + "--0/preview.gif"
    gifs.append(gif_path)
  zipped = zip(route_paths, gifs, strict=False)
  return render_template("footage.html", zipped=zipped)

@bp.route("/preserved/")
@bp.route("/preserved")
def preserved():
  query_type = "qcamera"
  route_paths = []
  gifs = []
  segments = fleet.preserved_routes()
  for segment in segments:
    input_path = Paths.log_root() + segment + "/qcamera.ts"
    output_path = Paths.log_root() + segment + "/preview.gif"
    fleet.video_to_img(input_path, output_path)
    split_segment = segment.split("--")
    route_paths.append(f"{split_segment[0]}--{split_segment[1]}?{split_segment[2]},{query_type}")
    gif_path = segment + "/preview.gif"
    gifs.append(gif_path)

  zipped = zip(route_paths, gifs, segments, strict=False)
  return render_template("preserved.html", zipped=zipped)

@bp.route("/screenrecords/")
@bp.route("/screenrecords")
def screenrecords():
  rows = fleet.list_file(fleet.SCREENRECORD_PATH)
  if not rows:
    return render_template("error.html", error="no screenrecords found at:<br><br>" + fleet.SCREENRECORD_PATH)
  return render_template("screenrecords.html", rows=rows, clip=rows[0])


@bp.route("/screenrecords/<clip>")
def screenrecord(clip):
  return render_template("screenrecords.html", rows=fleet.list_files(fleet.SCREENRECORD_PATH), clip=clip)


@bp.route("/screenrecords/play/pipe/<file>")
def videoscreenrecord(file):
  file_name = fleet.SCREENRECORD_PATH + file
  return Response(fleet.ffplay_mp4_wrap_process_builder(file_name).stdout.read(), status=200, mimetype='video/mp4')


@bp.route("/screenrecords/download/<clip>")
def download_file(clip):
  return send_from_directory(fleet.SCREENRECORD_PATH, clip, as_attachment=True)


@bp.route("/about")
def about():
  return render_template("about.html")


@bp.route("/error_logs")
def error_logs():
  rows = fleet.list_file(fleet.ERROR_LOGS_PATH)
  if not rows:
    return render_template("error.html", error="no error logs found at:<br><br>" + fleet.ERROR_LOGS_PATH)
  return render_template("error_logs.html", rows=rows)


@bp.route("/error_logs/<file_name>")
def open_error_log(file_name):
  f = open(fleet.ERROR_LOGS_PATH + file_name)
  error = f.read()
  return render_template("error_log.html", file_name=file_name, file_content=error)

@bp.route("/addr_input", methods=['GET', 'POST'])
def addr_input():
  preload = fleet.preload_favs()
  SearchInput = fleet.get_SearchInput()
  token = fleet.get_public_token()
  s_token = fleet.get_app_token()
  gmap_key = fleet.get_gmap_key()
  PrimeType = fleet.get_PrimeType()
  lon = 0.0
  lat = 0.0
  print(f"Request method: {request.method}, SearchInput: {SearchInput}, token: {token}, s_token: {s_token}, gmap_key: {gmap_key}, PrimeType: {PrimeType}")
  if request.method == 'POST':
    valid_addr = False
    postvars = request.form.to_dict()
    addr, lon, lat, valid_addr, token = fleet.parse_addr(postvars, lon, lat, valid_addr, token)
    if not valid_addr:
      # If address is not found, try searching
      postvars = request.form.to_dict()
      addr = request.form.get('addr_val')
      addr, lon, lat, valid_addr, token = fleet.search_addr(postvars, lon, lat, valid_addr, token)
    if valid_addr:
      # If a valid address is found, redirect to nav_confirmation
      return redirect(url_for('nav_confirmation', addr=addr, lon=lon, lat=lat))
    else:
      return render_template("error.html")
  #elif PrimeType != 0:
  #  return render_template("prime.html")
  # amap stuff
  elif SearchInput == 1:
    amap_key, amap_key_2 = fleet.get_amap_key()
    if amap_key == "" or amap_key is None or amap_key_2 == "" or amap_key_2 is None:
      return redirect(url_for('amap_key_input'))
    elif token == "" or token is None:
      return redirect(url_for('public_token_input'))
    elif s_token == "" or s_token is None:
      return redirect(url_for('app_token_input'))
    else:
      return redirect(url_for('amap_addr_input'))
  elif False: #fleet.get_nav_active(): # carrot: 그냥지움... 이것때문에 토큰을 안물어보는듯...
    if SearchInput == 2:
      return render_template("nonprime.html",
                             gmap_key=gmap_key, lon=lon, lat=lat,
                             home=preload[0],work=preload[1], fav1=preload[2], fav2=preload[3], fav3=preload[4])
    else:
      return render_template("nonprime.html",
                             gmap_key=None, lon=None, lat=None,
                             home=preload[0], work=preload[1], fav1=preload[2], fav2=preload[3], fav3=preload[4])
  elif token == "" or token is None:
    return redirect(url_for('public_token_input'))
  elif s_token == "" or s_token is None:
    return redirect(url_for('app_token_input'))
  elif SearchInput == 2:
    lon, lat = fleet.get_last_lon_lat()
    if gmap_key == "" or gmap_key is None:
      return redirect(url_for('gmap_key_input'))
    else:
      return render_template("addr.html",
                             gmap_key=gmap_key, lon=lon, lat=lat,
                             home=preload[0], work=preload[1], fav1=preload[2], fav2=preload[3], fav3=preload[4])
  else:
      return render_template("addr.html",
                             gmap_key=None, lon=None, lat=None,
                             home=preload[0], work=preload[1], fav1=preload[2], fav2=preload[3], fav3=preload[4])

@bp.route("/nav_confirmation", methods=['GET', 'POST'])
def nav_confirmation():
  token = fleet.get_public_token()
  lon = request.args.get('lon')
  lat = request.args.get('lat')
  addr = request.args.get('addr')
  if request.method == 'POST':
    postvars = request.form.to_dict()
    fleet.nav_confirmed(postvars)
    return redirect(url_for('addr_input'))
  else:
    return render_template("nav_confirmation.html", addr=addr, lon=lon, lat=lat, token=token)

@bp.route("/public_token_input", methods=['GET', 'POST'])
def public_token_input():
  if request.method == 'POST':
    postvars = request.form.to_dict()
    fleet.public_token_input(postvars)
    return redirect(url_for('addr_input'))
  else:
    return render_template("public_token_input.html")

@bp.route("/app_token_input", methods=['GET', 'POST'])
def app_token_input():
  if request.method == 'POST':
    postvars = request.form.to_dict()
    fleet.app_token_input(postvars)
    return redirect(url_for('addr_input'))
  else:
    return render_template("app_token_input.html")

@bp.route("/gmap_key_input", methods=['GET', 'POST'])
def gmap_key_input():
  if request.method == 'POST':
    postvars = request.form.to_dict()
    fleet.gmap_key_input(postvars)
    return redirect(url_for('addr_input'))
  else:
    return render_template("gmap_key_input.html")

@bp.route("/amap_key_input", methods=['GET', 'POST'])
def amap_key_input():
  if request.method == 'POST':
    postvars = request.form.to_dict()
    fleet.amap_key_input(postvars)
    return redirect(url_for('amap_addr_input'))
  else:
    return render_template("amap_key_input.html")

@bp.route("/CurrentStep.json", methods=['GET'])
def find_CurrentStep():
  directory = "/data/openpilot/selfdrive/manager/"
  filename = "CurrentStep.json"
  return send_from_directory(directory, filename, as_attachment=True)

@bp.route("/navdirections.json", methods=['GET'])
def find_nav_directions():
  directory = "/data/openpilot/selfdrive/manager/"
  filename = "navdirections.json"
  return send_from_directory(directory, filename, as_attachment=True)

@bp.route("/locations", methods=['GET'])
def get_locations():
  data = fleet.get_locations()
  return Response(data, content_type="application/json")

@bp.route("/set_destination", methods=['POST'])
def set_destination():
  valid_addr = False
  postvars = request.get_json()
  data, valid_addr = fleet.set_destination(postvars, valid_addr)
  if valid_addr:
    return Response('{"success": true}', content_type='application/json')
  else:
    return Response('{"success": false}', content_type='application/json')

@bp.route("/navigation/<file_name>", methods=['GET'])
def find_navicon(file_name):
  directory = "/data/openpilot/selfdrive/assets/navigation/"
  return send_from_directory(directory, file_name, as_attachment=True)

@bp.route("/previewgif/<path:file_path>", methods=['GET'])
def find_previewgif(file_path):
  directory = "/data/media/0/realdata/"
  return send_from_directory(directory, file_path, as_attachment=True)

@bp.route("/tools", methods=['GET'])
def tools_route():
  return render_template("tools.html")

@bp.route("/get_toggle_values", methods=['GET'])
def get_toggle_values_route():
  toggle_values = fleet.get_all_toggle_values()
  return jsonify(toggle_values)

@bp.route("/store_toggle_values", methods=['POST'])
def store_toggle_values_route():
  try:
    updated_values = request.get_json()
    fleet.store_toggle_values(updated_values)
    return jsonify({"message": "Values updated successfully"}), 200
  except Exception as e:
    return jsonify({"error": "Failed to update values", "details": str(e)}), 400

def handle_errors(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            print(f"Error in {f.__name__}: {str(e)}")
            traceback.print_exc()
            return render_template("error.html", error=str(e))
    return decorated_function

@bp.route("/carinfo")
@handle_errors
def carinfo():
    try:
        params = Params()

        # 更新消息
        sm.update()

        # 获取车辆基本信息
        try:
            car_name = params.get("CarName", encoding='utf8')
            if car_name in PLATFORMS:
                platform = PLATFORMS[car_name]
                car_fingerprint = platform.config.platform_str
                car_specs = platform.config.specs
            else:
                car_fingerprint = "未知指纹"
                car_specs = None
        except Exception as e:
            print(f"获取车辆基本信息失败: {e}")
            car_name = "未知车型"
            car_fingerprint = "未知指纹"
            car_specs = None

        # 获取车辆状态信息
        try:
            CS = sm['carState']

            # 基本状态判断
            is_car_started = CS.vEgo > 0.1
            is_car_engaged = CS.cruiseState.enabled

            # 构建基础信息
            car_info = {
                "车辆状态": {
                    "运行状态": "行驶中" if is_car_started else "停车中",
                    "巡航系统": "已启用" if is_car_engaged else "未启用",
                    "当前速度": f"{CS.vEgo * 3.6:.1f} km/h",
                    "发动机转速": f"{CS.engineRPM:.0f} RPM" if hasattr(CS, 'engineRPM') and CS.engineRPM > 0 else "未知",
                    "档位信息": str(CS.gearShifter) if hasattr(CS, 'gearShifter') else "未知"
                },
                "基本信息": {
                    "车型": car_name,
                    "指纹": str(car_fingerprint),
                    "车重": f"{car_specs.mass:.0f} kg" if car_specs and hasattr(car_specs, 'mass') else "未知",
                    "轴距": f"{car_specs.wheelbase:.3f} m" if car_specs and hasattr(car_specs, 'wheelbase') else "未知",
                    "转向比": f"{car_specs.steerRatio:.1f}" if car_specs and hasattr(car_specs, 'steerRatio') else "未知"
                }
            }

            # 详细信息
            if is_car_started or is_car_engaged:
                car_info.update({
                    "巡航信息": {
                        "巡航状态": "开启" if CS.cruiseState.enabled else "关闭",
                        "自适应巡航": "开启" if CS.cruiseState.available else "关闭",
                        "设定速度": f"{CS.cruiseState.speed * 3.6:.1f} km/h" if CS.cruiseState.speed > 0 else "未设置",
                        "跟车距离": str(CS.cruiseState.followDistance) if hasattr(CS.cruiseState, 'followDistance') else "未知"
                    },
                    "车轮速度": {
                        "左前轮": f"{CS.wheelSpeeds.fl * 3.6:.1f} km/h",
                        "右前轮": f"{CS.wheelSpeeds.fr * 3.6:.1f} km/h",
                        "左后轮": f"{CS.wheelSpeeds.rl * 3.6:.1f} km/h",
                        "右后轮": f"{CS.wheelSpeeds.rr * 3.6:.1f} km/h"
                    },
                    "转向系统": {
                        "转向角度": f"{CS.steeringAngleDeg:.1f}°",
                        "转向扭矩": f"{CS.steeringTorque:.1f} Nm",
                        "转向角速度": f"{CS.steeringRateDeg:.1f}°/s",
                        "车道偏离": "是" if CS.leftBlinker or CS.rightBlinker else "否"
                    },
                    "踏板状态": {
                        "油门位置": f"{CS.gas * 100:.1f}%",
                        "刹车压力": f"{CS.brake * 100:.1f}%",
                        "油门踏板": "踩下" if CS.gasPressed else "松开",
                        "刹车踏板": "踩下" if CS.brakePressed else "松开"
                    },
                    "安全系统": {
                        "ESP状态": "介入" if CS.espDisabled else "正常",
                        "ABS状态": "介入" if hasattr(CS, 'absActive') and CS.absActive else "正常",
                        "牵引力控制": "介入" if hasattr(CS, 'tcsActive') and CS.tcsActive else "正常",
                        "碰撞预警": "警告" if hasattr(CS, 'collisionWarning') and CS.collisionWarning else "正常"
                    },
                    "车门状态": {
                        "左前门": "开启" if CS.doorOpen else "关闭",
                        "右前门": "开启" if hasattr(CS, 'passengerDoorOpen') and CS.passengerDoorOpen else "关闭",
                        "后备箱": "开启" if hasattr(CS, 'trunkOpen') and CS.trunkOpen else "关闭",
                        "引擎盖": "开启" if hasattr(CS, 'hoodOpen') and CS.hoodOpen else "关闭",
                        "安全带": "未系" if CS.seatbeltUnlatched else "已系"
                    },
                    "灯光状态": {
                        "左转向灯": "开启" if CS.leftBlinker else "关闭",
                        "右转向灯": "开启" if CS.rightBlinker else "关闭",
                        "远光灯": "开启" if CS.genericToggle else "关闭",
                        "近光灯": "开启" if hasattr(CS, 'lowBeamOn') and CS.lowBeamOn else "关闭"
                    },
                    "盲点监测": {
                        "左侧": "有车" if CS.leftBlindspot else "无车",
                        "右侧": "有车" if CS.rightBlindspot else "无车"
                    }
                })

                # 添加可选的其他信息
                other_info = {}
                if hasattr(CS, 'outsideTemp'):
                    other_info["车外温度"] = f"{CS.outsideTemp:.1f}°C"
                if hasattr(CS, 'fuelGauge'):
                    other_info["续航里程"] = f"{CS.fuelGauge:.1f}km"
                if hasattr(CS, 'odometer'):
                    other_info["总里程"] = f"{CS.odometer:.1f}km"
                if hasattr(CS, 'instantFuelConsumption'):
                    other_info["瞬时油耗"] = f"{CS.instantFuelConsumption:.1f}L/100km"

                if other_info:
                    car_info["其他信息"] = other_info

        except Exception as e:
            print(f"获取车辆状态信息时出错: {str(e)}")
            traceback.print_exc()
            car_info = {
                "基本信息": {
                    "车型": car_name,
                    "指纹": str(car_fingerprint)
                },
                "状态": "无法获取车辆状态信息，请检查车辆是否启动"
            }

        return render_template("carinfo.html", car_info=car_info)

    except Exception as e:
        print(f"carinfo 页面渲染出错: {str(e)}")
        traceback.print_exc()
        return render_template("carinfo.html", car_info={"错误": f"获取车辆信息时出错: {str(e)}"})

def main():
  try:
    set_core_affinity([0, 1, 2, 3])
  except Exception:
    cloudlog.exception("fleet_manager: failed to set core affinity")

  # 注册 Blueprint
  app.register_blueprint(bp)

  app.secret_key = secrets.token_hex(32)
  app.run(host="0.0.0.0", port=8082)


if __name__ == '__main__':
  main()
