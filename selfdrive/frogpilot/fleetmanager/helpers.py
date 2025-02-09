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
import json
import math
import os
import requests
import subprocess
# otisserv conversion
from pathlib import Path

from openpilot.common.params import Params
from openpilot.system.hardware import PC
from openpilot.system.hardware.hw import Paths
from openpilot.system.loggerd.uploader import listdir_by_creation
from openpilot.tools.lib.route import SegmentName
from openpilot.system.loggerd.xattr_cache import getxattr

# otisserv conversion
from urllib.parse import quote

pi = 3.1415926535897932384626
x_pi = 3.14159265358979324 * 3000.0 / 180.0
a = 6378245.0
ee = 0.00669342162296594323

params = Params()
params_memory = Params("/dev/shm/params")
#params_storage = Params("/persist/comma/params")

PRESERVE_ATTR_NAME = 'user.preserve'
PRESERVE_ATTR_VALUE = b'1'
PRESERVE_COUNT = 5


# path to openpilot screen recordings and error logs
if PC:
  SCREENRECORD_PATH = os.path.join(str(Path.home()), ".comma", "media", "0", "videos", "")
  ERROR_LOGS_PATH = os.path.join(str(Path.home()), ".comma", "community", "crashes", "")
else:
  SCREENRECORD_PATH = "/data/media/0/videos/"
  ERROR_LOGS_PATH = "/data/community/crashes/"


def list_files(path): # still used for footage
  return sorted(listdir_by_creation(path), reverse=True)


def list_file(path): # new function for screenrecords/error-logs
  if os.path.exists(path):
    files = os.listdir(path)
    sorted_files = sorted(files, reverse=True)
  else:
    return []  # Return an empty list if there are no files or directory
  return sorted_files


def is_valid_segment(segment):
  try:
    segment_to_segment_name(Paths.log_root(), segment)
    return True
  except AssertionError:
    return False


def segment_to_segment_name(data_dir, segment):
  fake_dongle = "ffffffffffffffff"
  return SegmentName(str(os.path.join(data_dir, fake_dongle + "|" + segment)))


def all_segment_names():
  segments = []
  for segment in listdir_by_creation(Paths.log_root()):
    try:
      segments.append(segment_to_segment_name(Paths.log_root(), segment))
    except AssertionError:
      pass
  return segments


def all_routes():
  segment_names = all_segment_names()
  route_names = [segment_name.route_name for segment_name in segment_names]
  route_times = [route_name.time_str for route_name in route_names]
  unique_routes = list(dict.fromkeys(route_times))
  return sorted(unique_routes, reverse=True)

def preserved_routes():
  dirs = listdir_by_creation(Paths.log_root())
  preserved_segments = get_preserved_segments(dirs)
  return sorted(preserved_segments, reverse=True)

def has_preserve_xattr(d: str) -> bool:
  return getxattr(os.path.join(Paths.log_root(), d), PRESERVE_ATTR_NAME) == PRESERVE_ATTR_VALUE

def get_preserved_segments(dirs_by_creation: list[str]) -> list[str]:
  preserved = []
  for n, d in enumerate(filter(has_preserve_xattr, reversed(dirs_by_creation))):
    if n == PRESERVE_COUNT:
      break
    date_str, _, seg_str = d.rpartition("--")

    # ignore non-segment directories
    if not date_str:
      continue
    try:
      seg_num = int(seg_str)
    except ValueError:
      continue
    # preserve segment and its prior
    preserved.append(d)

  return preserved

def video_to_gif(input_path, output_path, fps=1, duration=6): # not used right now but can if want longer animated gif
  if os.path.exists(output_path):
    return
  command = [
    'ffmpeg', '-y', '-i', input_path,
    '-filter_complex',
    f'fps={fps},scale=240:-1:flags=lanczos,setpts=0.1*PTS,split[s0][s1];[s0]palettegen=max_colors=32[p];[s1][p]paletteuse=dither=bayer',
    '-t', str(duration), output_path
  ]
  subprocess.run(command)
  print(f"GIF file created: {output_path}")

def video_to_img(input_path, output_path, fps=1, duration=6):
  if os.path.exists(output_path):
    print("video_to_img path exist=", output_path)
    return
  subprocess.run(['ffmpeg', '-y', '-i', input_path, '-ss', '5', '-vframes', '1', output_path])
  print(f"GIF file created: {output_path}")

def segments_in_route(route):
  segment_names = [segment_name for segment_name in all_segment_names() if segment_name.time_str == route]
  segments = [segment_name.time_str + "--" + str(segment_name.segment_num) for segment_name in segment_names]
  return segments


def ffmpeg_mp4_concat_wrap_process_builder(file_list, cameratype, chunk_size=1024*512):
  command_line = ["ffmpeg"]
  if not cameratype == "qcamera":
    command_line += ["-f", "hevc"]
  command_line += ["-r", "20"]
  command_line += ["-i", "concat:" + file_list]
  command_line += ["-c", "copy"]
  command_line += ["-map", "0"]
  if not cameratype == "qcamera":
    command_line += ["-vtag", "hvc1"]
  command_line += ["-f", "mp4"]
  command_line += ["-movflags", "empty_moov"]
  command_line += ["-"]
  return subprocess.Popen(
    command_line, stdout=subprocess.PIPE,
    bufsize=chunk_size
  )


def ffmpeg_mp4_wrap_process_builder(filename):
  """Returns a process that will wrap the given filename
     inside a mp4 container, for easier playback by browsers
     and other devices. Primary use case is streaming segment videos
     to the vidserver tool.
     filename is expected to be a pathname to one of the following
       /path/to/a/qcamera.ts
       /path/to/a/dcamera.hevc
       /path/to/a/ecamera.hevc
       /path/to/a/fcamera.hevc
  """
  basename = filename.rsplit("/")[-1]
  extension = basename.rsplit(".")[-1]
  command_line = ["ffmpeg"]
  if extension == "hevc":
    command_line += ["-f", "hevc"]
  command_line += ["-r", "20"]
  command_line += ["-i", filename]
  command_line += ["-c", "copy"]
  command_line += ["-map", "0"]
  if extension == "hevc":
    command_line += ["-vtag", "hvc1"]
  command_line += ["-f", "mp4"]
  command_line += ["-movflags", "empty_moov"]
  command_line += ["-"]
  return subprocess.Popen(
    command_line, stdout=subprocess.PIPE
  )


def ffplay_mp4_wrap_process_builder(file_name):
  command_line = ["ffmpeg"]
  command_line += ["-i", file_name]
  command_line += ["-c", "copy"]
  command_line += ["-map", "0"]
  command_line += ["-f", "mp4"]
  command_line += ["-movflags", "empty_moov"]
  command_line += ["-"]
  return subprocess.Popen(
    command_line, stdout=subprocess.PIPE
  )

def get_nav_active():
  try:
    return params.get("NavDestination", encoding='utf8') is not None
  except:
    return False

def get_public_token():
  try:
    token = params.get("MapboxPublicKey", encoding='utf8')
    return token.strip() if token is not None else ""
  except:
    return ""

def get_app_token():
  try:
    token = params.get("MapboxSecretKey", encoding='utf8')
    return token.strip() if token is not None else ""
  except:
    return ""

def get_gmap_key():
  try:
    # 直接获取参数值，不指定编码
    token = params.get("AMapKey1")
    token2 = params.get("AMapKey2")

    print(f"获取到的原始参数 - AMapKey1: {token}, AMapKey2: {token2}")

    # 处理字节串转换
    if isinstance(token, bytes):
      try:
        token = token.decode('utf-8')
      except UnicodeDecodeError:
        print("AMapKey1 解码失败")
        token = "faf2f8ab406a8da1231ef7e10d501b65"  # 使用默认值

    if isinstance(token2, bytes):
      try:
        token2 = token2.decode('utf-8')
      except UnicodeDecodeError:
        print("AMapKey2 解码失败")
        token2 = "fc2724b3c96a7f244b2211f05c5264be"  # 使用默认值

    # 如果值为空，使用默认值
    if not token:
      token = "faf2f8ab406a8da1231ef7e10d501b65"
    if not token2:
      token2 = "fc2724b3c96a7f244b2211f05c5264be"

    # 去除空白并返回
    token = token.strip()
    token2 = token2.strip()

    print(f"处理后的参数 - AMapKey1: {token}, AMapKey2: {token2}")
    return (token, token2)

  except Exception as e:
    print(f"获取高德地图 API Keys 时发生错误: {str(e)}")
    # 发生错误时返回默认值
    return ("faf2f8ab406a8da1231ef7e10d501b65", "fc2724b3c96a7f244b2211f05c5264be")

def get_amap_key():
  """获取高德地图 API Keys"""
  try:
    # 默认的 API Keys
    default_web_key = "faf2f8ab406a8da1231ef7e10d501b65"
    default_js_key = "fc2724b3c96a7f244b2211f05c5264be"

    # 获取参数值
    try:
      # 直接获取字节串形式的参数
      web_key = params.get("AMapKey1")
      js_key = params.get("AMapKey2")

      print(f"原始参数值 - AMapKey1: {web_key}, AMapKey2: {js_key}")

      # 处理 web_key
      if web_key is None or web_key == b"":
        web_key = default_web_key.encode()
      elif isinstance(web_key, bytes):
        try:
          web_key = web_key.decode('utf-8').strip()
        except UnicodeDecodeError:
          print("AMapKey1 解码失败，使用默认值")
          web_key = default_web_key
      else:
        web_key = str(web_key).strip()

      # 处理 js_key
      if js_key is None or js_key == b"":
        js_key = default_js_key.encode()
      elif isinstance(js_key, bytes):
        try:
          js_key = js_key.decode('utf-8').strip()
        except UnicodeDecodeError:
          print("AMapKey2 解码失败，使用默认值")
          js_key = default_js_key
      else:
        js_key = str(js_key).strip()

      # 确保键值非空
      web_key = web_key if web_key else default_web_key
      js_key = js_key if js_key else default_js_key

      print(f"处理后的参数 - AMapKey1: {web_key}, AMapKey2: {js_key}")
      return (web_key, js_key)

    except Exception as e:
      print(f"参数处理失败: {str(e)}")
      return (default_web_key, default_js_key)

  except Exception as e:
    print(f"获取高德地图 API Keys 时发生错误: {str(e)}")
    return (default_web_key, default_js_key)

def get_SearchInput():
  try:
    params.put("SearchInput", "1")  # 确保设置默认值
    return 1  # 默认使用高德地图
  except:
    return 1

def get_PrimeType():
  try:
    return params.get_int("PrimeType") or 0
  except:
    return 0

def get_last_lon_lat():
  try:
    last_pos = params.get("LastGPSPosition")
    if last_pos:
      try:
        l = json.loads(last_pos)
        return float(l.get("longitude", 0.0)), float(l.get("latitude", 0.0))
      except:
        pass
    return 0.0, 0.0
  except:
    return 0.0, 0.0

def get_locations():
  try:
    data = params.get("ApiCache_NavDestinations", encoding='utf-8')
    if data is None:
      return "[]"
    return data.rstrip('\x00')
  except:
    return "[]"

def preload_favs():
  try:
    # 获取导航目的地数据
    data = get_locations()
    if data == "[]":
      return (None, None, None, None, None)

    # 尝试解析 JSON
    try:
      nav_destinations = json.loads(data)
    except:
      return (None, None, None, None, None)

    # 初始化位置字典
    locations = {"home": None, "work": None, "fav1": None, "fav2": None, "fav3": None}

    # 遍历并填充位置信息
    if isinstance(nav_destinations, list):
      for item in nav_destinations:
        if isinstance(item, dict) and "save_type" in item:
          if item["save_type"] == "favorite" and "label" in item:
            label = item["label"]
            if label in locations:
              locations[label] = item.get("place_name", "未命名位置")

    return tuple(locations.values())

  except Exception as e:
    print(f"Error in preload_favs: {str(e)}")
    return (None, None, None, None, None)

def parse_addr(postvars, lon, lat, valid_addr, token):
  try:
    addr = postvars.get("fav_val")
    if not addr or addr == "favorites":
      return (None, lon, lat, False, token)

    data = get_locations()
    if data == "[]":
      return (None, lon, lat, False, token)

    dests = json.loads(data)
    for item in dests:
      if isinstance(item, dict) and "label" in item and item["label"] == addr:
        try:
          lat = float(item["latitude"])
          lon = float(item["longitude"])
          real_addr = item.get("place_name", "未命名位置")
          return (real_addr, lon, lat, True, token)
        except:
          continue

    return (None, lon, lat, False, token)
  except Exception as e:
    print(f"Error in parse_addr: {str(e)}")
    return (None, lon, lat, False, token)

def search_addr(postvars, lon, lat, valid_addr, token):
  """搜索地址并返回坐标"""
  try:
    addr = ""
    if "addr_val" in postvars:
      addr = postvars.get("addr_val", "")
      if addr:
        # 编码地址以处理空格
        addr_encoded = quote(addr)
        query = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{addr_encoded}.json?access_token={token}&limit=1"

        # 使用最后的GPS位置作为搜索中心
        lngi, lati = get_last_lon_lat()
        query += f"&proximity={lngi},{lati}"

        try:
          r = requests.get(query)
          if r.status_code == 200:
            j = json.loads(r.text)
            if j["features"]:
              lon, lat = j["features"][0]["geometry"]["coordinates"]
              valid_addr = True
              print(f"地址搜索成功 - 地址: {addr}, 坐标: ({lon}, {lat})")
            else:
              print(f"未找到地址: {addr}")
        except Exception as e:
          print(f"地址搜索请求失败: {str(e)}")
      else:
        print("地址为空")
    else:
      print("未提供地址参数")

    return (addr, lon, lat, valid_addr, token)

  except Exception as e:
    print(f"地址搜索出错: {str(e)}")
    return (addr if 'addr' in locals() else "", lon, lat, False, token)

def set_destination(postvars, valid_addr):
  if postvars.get("latitude") is not None and postvars.get("longitude") is not None:
    postvars["lat"] = postvars.get("latitude")
    postvars["lon"] = postvars.get("longitude")
    postvars["save_type"] = "recent"
    nav_confirmed(postvars)
    valid_addr = True
  else:
    addr = postvars.get("place_name")
    token = get_public_token()
    data, lon, lat, valid_addr, token = search_addr(addr, lon, lat, valid_addr, token)
    postvars["lat"] = lat
    postvars["lon"] = lon
    postvars["save_type"] = "recent"
    nav_confirmed(postvars)
    valid_addr= True
  return postvars, valid_addr

def nav_confirmed(postvars):
  if postvars is None:
    return

  try:
    lat = float(postvars.get("lat", 0))
    lng = float(postvars.get("lon", 0))
    save_type = postvars.get("save_type", "recent")
    name = postvars.get("name", "")

    # 如果使用高德地图，进行坐标转换
    if params.get_int("SearchInput") == 1:
      lng, lat = gcj02towgs84(lng, lat)

    # 保存导航目的地
    nav_dest = {
      "latitude": lat,
      "longitude": lng,
      "place_name": name if name else f"{lat:.6f},{lng:.6f}"
    }
    params.put("NavDestination", json.dumps(nav_dest))

    # 构建新的目的地记录
    new_dest = {
      "latitude": lat,
      "longitude": lng,
      "place_name": name if name else f"{lat:.6f},{lng:.6f}",
      "save_type": "favorite" if save_type != "recent" else "recent"
    }
    if save_type != "recent":
      new_dest["label"] = save_type

    # 获取现有目的地列表
    data = get_locations()
    dests = json.loads(data) if data != "[]" else []

    # 更新目的地列表
    if save_type == "recent":
      # 对于最近位置，添加到列表开头
      dests.insert(0, new_dest)
      # 保持最近位置不超过10个
      dests = [d for d in dests if d.get("save_type") == "favorite"] + \
              [d for d in dests if d.get("save_type") == "recent"][:10]
    else:
      # 对于收藏位置，更新或添加
      found = False
      for i, d in enumerate(dests):
        if d.get("save_type") == "favorite" and d.get("label") == save_type:
          dests[i] = new_dest
          found = True
          break
      if not found:
        dests.insert(0, new_dest)

    # 保存更新后的目的地列表
    params.put("ApiCache_NavDestinations", json.dumps(dests).rstrip("\n\r"))

  except Exception as e:
    print(f"Error in nav_confirmed: {str(e)}")

def public_token_input(postvars):
  if postvars is None or "pk_token_val" not in postvars or postvars.get("pk_token_val")[0] == "":
    return postvars
  else:
    token = postvars.get("pk_token_val").strip()
    if "pk." not in token:
      return postvars
    else:
        params.put("MapboxPublicKey", token)
  return token

def app_token_input(postvars):
  if postvars is None or "sk_token_val" not in postvars or postvars.get("sk_token_val")[0] == "":
    return postvars
  else:
    token = postvars.get("sk_token_val").strip()
    if "sk." not in token:
      return postvars
    else:
        params.put("MapboxSecretKey", token)
  return token

def gmap_key_input(postvars):
  if postvars is None or "gmap_key_val" not in postvars or postvars.get("gmap_key_val")[0] == "":
    return postvars
  else:
    token = postvars.get("gmap_key_val").strip()
    params.put("GMapKey", token)
  return token

def init_amap_params():
  """初始化高德地图相关参数"""
  try:
    print("开始初始化高德地图参数...")

    # 检查参数目录
    params_dir = "/data/params/d"
    if not os.path.exists(params_dir):
      try:
        os.makedirs(params_dir, mode=0o755, exist_ok=True)
        print(f"创建参数目录: {params_dir}")
      except Exception as e:
        print(f"创建参数目录失败: {str(e)}")
        return False

    # 设置默认参数
    try:
      # 设置 SearchInput 参数
      params.put_bool("SearchInput", True)
      print("SearchInput 参数设置成功")

      # 设置默认的 AMapKey 参数
      default_web_key = "faf2f8ab406a8da1231ef7e10d501b65"
      default_js_key = "fc2724b3c96a7f244b2211f05c5264be"

      # 检查现有参数
      existing_web_key = params.get("AMapKey1")
      existing_js_key = params.get("AMapKey2")

      # 只在参数不存在时设置默认值
      if existing_web_key is None:
        params.put("AMapKey1", default_web_key)
        print(f"设置 AMapKey1 默认值: {default_web_key}")

      if existing_js_key is None:
        params.put("AMapKey2", default_js_key)
        print(f"设置 AMapKey2 默认值: {default_js_key}")

      print("默认参数设置成功")
      return True

    except Exception as e:
      print(f"设置默认参数失败: {str(e)}")
      return False

  except Exception as e:
    print(f"高德地图参数初始化失败: {str(e)}")
    return False

def amap_key_input(postvars):
  """处理高德地图 API Key 的输入和保存"""
  try:
    if not postvars:
      print("错误: 未收到输入参数")
      return None

    # 获取并验证输入的 API Keys
    web_key = postvars.get("amap_key_val", "").strip()
    js_key = postvars.get("amap_key_val_2", "").strip()

    print(f"接收到的 API Keys - Web: {web_key}, JS: {js_key}")

    if not web_key or not js_key:
      print("错误: API Keys 不能为空")
      return None

    try:
      # 保存参数
      params.put("AMapKey1", web_key)
      print("AMapKey1 保存成功")
      params.put("AMapKey2", js_key)
      print("AMapKey2 保存成功")
      params.put_bool("SearchInput", True)
      print("SearchInput 保存成功")

      # 验证保存的结果
      saved_web_key, saved_js_key = get_amap_key()
      print(f"验证保存的参数 - Web: {saved_web_key}, JS: {saved_js_key}")

      if not saved_web_key or not saved_js_key:
        print("错误: 参数保存验证失败")
        return None

      print("API Keys 设置成功")
      return web_key

    except Exception as e:
      print(f"保存参数失败: {str(e)}")
      return None

  except Exception as e:
    print(f"API Key 输入处理失败: {str(e)}")
    return None

def gcj02towgs84(lng, lat):
  dlat = transform_lat(lng - 105.0, lat - 35.0)
  dlng = transform_lng(lng - 105.0, lat - 35.0)
  radlat = lat / 180.0 * pi
  magic = math.sin(radlat)
  magic = 1 - ee * magic * magic
  sqrtmagic = math.sqrt(magic)
  dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * pi)
  dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * pi)
  mglat = lat + dlat
  mglng = lng + dlng
  return [lng * 2 - mglng, lat * 2 - mglat]

def transform_lat(lng, lat):
  ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * math.sqrt(abs(lng))
  ret += (20.0 * math.sin(6.0 * lng * pi) + 20.0 * math.sin(2.0 * lng * pi)) * 2.0 / 3.0
  ret += (20.0 * math.sin(lat * pi) + 40.0 * math.sin(lat / 3.0 * pi)) * 2.0 / 3.0
  ret += (160.0 * math.sin(lat / 12.0 * pi) + 320 * math.sin(lat * pi / 30.0)) * 2.0 / 3.0
  return ret

def transform_lng(lng, lat):
  ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * math.sqrt(abs(lng))
  ret += (20.0 * math.sin(6.0 * lng * pi) + 20.0 * math.sin(2.0 * lng * pi)) * 2.0 / 3.0
  ret += (20.0 * math.sin(lng * pi) + 40.0 * math.sin(lng / 3.0 * pi)) * 2.0 / 3.0
  ret += (150.0 * math.sin(lng / 12.0 * pi) + 300.0 * math.sin(lng / 30.0 * pi)) * 2.0 / 3.0
  return ret

from openpilot.system.manager.manager import get_default_params_key
def get_all_toggle_values():
  all_keys = get_default_params_key()

  toggle_values = {}
  for key in all_keys:
    try:
      value = params.get(key)
    except Exception:
      value = b"0"
    toggle_values[key] = value.decode('utf-8') if value is not None else "0"

  return toggle_values

def store_toggle_values(updated_values):
  for key, value in updated_values.items():
    try:
      params.put(key, value.encode('utf-8'))
      #params_storage.put(key, value.encode('utf-8'))
    except Exception as e:
      print(f"Failed to update {key}: {e}")

  #params_memory.put_bool("FrogPilotTogglesUpdated", True)
  #time.sleep(1)
  #params_memory.put_bool("FrogPilotTogglesUpdated", False)
