import cv2  
import numpy as np  
import matplotlib.pyplot as plt  
import glob  
from flask import Flask, render_template, Response, jsonify  
import threading  
import time  
import os  
import sys  
  
# 添加openpilot路径  
sys.path.append('/data/openpilot')  
  
try:  
    from msgq.visionipc import VisionIpcClient, VisionStreamType  
except ImportError as e:  
    print(f"Failed to import VisionIPC: {e}")  
    print("Please ensure openpilot is properly installed and the path is correct")  
    sys.exit(1)  
  
app = Flask(__name__)  
  
# 全局变量存储最新识别数据  
latest_metadata = {  
    'left_type': 'Unknown',  
    'right_type': 'Unknown',  
    'curvature': 0.0,  
    'departure': 0.0  
}  
  
# VisionIPC客户端  
vipc_client = None  
frame_lock = threading.Lock()  
  
"参数设置"  
nx = 9  
ny = 6  
file_paths = glob.glob("./camera_cal/calibration*.jpg")  
  
# 绘制对比图  
def plot_contrast_image(origin_img, converted_img, origin_img_title="origin_img", converted_img_title="converted_img",  
                        converted_img_gray=False):  
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 20))  
    ax1.set_title = origin_img_title  
    ax1.imshow(origin_img)  
    ax2.set_title = converted_img_title  
    if converted_img_gray == True:  
        ax2.imshow(converted_img, cmap="gray")  
    else:  
        ax2.imshow(converted_img)  
    plt.show()  
  
# 相机校正：外参，内参，畸变系数  
def cal_calibrate_params(file_paths):  
    object_points = []  
    image_points = []  
    objp = np.zeros((nx * ny, 3), np.float32)  
    objp[:, :2] = np.mgrid[0:nx, 0:ny].T.reshape(-1, 2)  
      
    for file_path in file_paths:  
        img = cv2.imread(file_path)  
        if img is None:  
            continue  
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)  
        rect, coners = cv2.findChessboardCorners(gray, (nx, ny), None)  
        if rect == True:  
            object_points.append(objp)  
            image_points.append(coners)  
      
    if len(object_points) == 0:  
        print("No valid calibration images found")  
        return None, None, None, None, None  
      
    ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(object_points, image_points, gray.shape[::-1], None, None)  
    return ret, mtx, dist, rvecs, tvecs  
  
# 图像去畸变：利用相机校正的内参，畸变系数  
def img_undistort(img, mtx, dist):  
    if mtx is None or dist is None:  
        return img  
    dis = cv2.undistort(img, mtx, dist, None, mtx)  
    return dis  
  
# 车道线提取  
def pipeline(img, s_thresh=(170, 255), sx_thresh=(40, 200)):  
    img = np.copy(img)  
    hls = cv2.cvtColor(img, cv2.COLOR_RGB2HLS).astype(float)  
    l_chanel = hls[:, :, 1]  
    s_chanel = hls[:, :, 2]  
    sobelx = cv2.Sobel(l_chanel, cv2.CV_64F, 1, 0)  
    abs_sobelx = np.absolute(sobelx)  
    scaled_sobel = np.uint8(255 * abs_sobelx / np.max(abs_sobelx))  
    sxbinary = np.zeros_like(scaled_sobel)  
    sxbinary[(scaled_sobel >= sx_thresh[0]) & (scaled_sobel <= sx_thresh[1])] = 1  
    s_binary = np.zeros_like(s_chanel)  
    s_binary[(s_chanel >= s_thresh[0]) & (s_chanel <= s_thresh[1])] = 1  
    color_binary = np.zeros_like(sxbinary)  
    color_binary[((sxbinary == 1) | (s_binary == 1)) & (l_chanel > 100)] = 1  
    return color_binary  
  
# 透视变换  
def cal_perspective_params(img, points):  
    offset_x = 330  
    offset_y = 0  
    img_size = (img.shape[1], img.shape[0])  
    src = np.float32(points)  
    dst = np.float32([[offset_x, offset_y], [img_size[0] - offset_x, offset_y],  
                      [offset_x, img_size[1] - offset_y], [img_size[0] - offset_x, img_size[1] - offset_y]])  
    M = cv2.getPerspectiveTransform(src, dst)  
    M_inverse = cv2.getPerspectiveTransform(dst, src)  
    return M, M_inverse  
  
# 根据参数矩阵完成透视变换  
def img_perspect_transform(img, M):  
    img_size = (img.shape[1], img.shape[0])  
    return cv2.warpPerspective(img, M, img_size)  
  
# 精确定位车道线  
def cal_line_param(binary_warped):  
    histogram = np.sum(binary_warped[:, :], axis=0)  
    midpoint = int(histogram.shape[0] / 2)  
    leftx_base = np.argmax(histogram[:midpoint])  
    rightx_base = np.argmax(histogram[midpoint:]) + midpoint  
      
    nwindows = 9  
    window_height = int(binary_warped.shape[0] / nwindows)  
    nonzero = binary_warped.nonzero()  
    nonzeroy = np.array(nonzero[0])  
    nonzerox = np.array(nonzero[1])  
    leftx_current = leftx_base  
    rightx_current = rightx_base  
    margin = 100  
    minpix = 50  
    left_lane_inds = []  
    right_lane_inds = []  
    left_active_windows = 0  
    right_active_windows = 0  
  
    for window in range(nwindows):  
        win_y_low = binary_warped.shape[0] - (window + 1) * window_height  
        win_y_high = binary_warped.shape[0] - window * window_height  
        win_xleft_low = leftx_current - margin  
        win_xleft_high = leftx_current + margin  
        win_xright_low = rightx_current - margin  
        win_xright_high = rightx_current + margin  
  
        good_left_inds = ((nonzeroy >= win_y_low) & (nonzeroy < win_y_high) &  
                          (nonzerox >= win_xleft_low) & (nonzerox < win_xleft_high)).nonzero()[0]  
        good_right_inds = ((nonzeroy >= win_y_low) & (nonzeroy < win_y_high) &  
                           (nonzerox >= win_xright_low) & (nonzerox < win_xright_high)).nonzero()[0]  
        left_lane_inds.append(good_left_inds)  
        right_lane_inds.append(good_right_inds)  
  
        if len(good_left_inds) > minpix:  
            leftx_current = int(np.mean(nonzerox[good_left_inds]))  
            left_active_windows += 1  
        if len(good_right_inds) > minpix:  
            rightx_current = int(np.mean(nonzerox[good_right_inds]))  
            right_active_windows += 1  
  
    left_lane_inds = np.concatenate(left_lane_inds)  
    right_lane_inds = np.concatenate(right_lane_inds)  
    leftx = nonzerox[left_lane_inds]  
    lefty = nonzeroy[left_lane_inds]  
    rightx = nonzerox[right_lane_inds]  
    righty = nonzeroy[right_lane_inds]  
  
    if len(leftx) == 0 or len(rightx) == 0:  
        return None, None, "Unknown", "Unknown"  
  
    left_fit = np.polyfit(lefty, leftx, 2)  
    right_fit = np.polyfit(righty, rightx, 2)  
      
    left_type = "Solid" if left_active_windows > 7 else "Dashed"  
    right_type = "Solid" if right_active_windows > 7 else "Dashed"  
      
    return left_fit, right_fit, left_type, right_type  
  
# 填充车道线之间的多边形  
def fill_lane_poly(img, left_fit, right_fit):  
    if left_fit is None or right_fit is None:  
        return np.dstack((img, img, img)) * 255  
    y_max = img.shape[0]  
    out_img = np.dstack((img, img, img)) * 255  
    left_points = [[left_fit[0] * y ** 2 + left_fit[1] * y + left_fit[2], y] for y in range(y_max)]  
    right_points = [[right_fit[0] * y ** 2 + right_fit[1] * y + right_fit[2], y] for y in range(y_max - 1, -1, -1)]  
    line_points = np.vstack((left_points, right_points))  
    cv2.fillPoly(out_img, np.int_([line_points]), (0, 255, 0))  
    return out_img  
  
# 计算车道线曲率  
def cal_radius(img, left_fit, right_fit):  
    if left_fit is None or right_fit is None:  
        cv2.putText(img, 'Radius of Curvature = N/A(m)', (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)  
        return img, 0.0  
      
    ym_per_pix = 30/720  
    xm_per_pix = 3.7/700  
    y_max = img.shape[0]  
    ploty = np.linspace(0, y_max-1, y_max)  
    left_x = left_fit[0]*ploty**2 + left_fit[1]*ploty + left_fit[2]  
    right_x = right_fit[0]*ploty**2 + right_fit[1]*ploty + right_fit[2]  
  
    left_fit_cr = np.polyfit(ploty*ym_per_pix, left_x*xm_per_pix, 2)  
    right_fit_cr = np.polyfit(ploty*ym_per_pix, right_x*xm_per_pix, 2)  
  
    y_eval = np.max(ploty)  
    left_curverad = ((1 + (2*left_fit_cr[0]*y_eval*ym_per_pix + left_fit_cr[1])**2)**1.5) / np.absolute(2*left_fit_cr[0])  
    right_curverad = ((1 + (2*right_fit_cr[0]*y_eval*ym_per_pix + right_fit_cr[1])**2)**1.5) / np.absolute(2*right_fit_cr[0])  
      
    avg_radius = (left_curverad + right_curverad) / 2  
  
    cv2.putText(img, 'Radius of Curvature = {:.2f}(m)'.format(avg_radius), (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)  
    return img, avg_radius  
  
# 计算车道线中心  
def cal_line_center(img):  
    undistort_img = img_undistort(img, mtx, dist)  
    rigin_pipeline_img = pipeline(undistort_img)  
    trasform_img = img_perspect_transform(rigin_pipeline_img, M)  
    left_fit, right_fit, _, _ = cal_line_param(trasform_img)  
    if left_fit is None or right_fit is None:  
        return img.shape[1] / 2  
    y_max = img.shape[0]  
    left_x = left_fit[0]*y_max**2 + left_fit[1]*y_max + left_fit[2]  
    right_x = right_fit[0]*y_max**2 + right_fit[1]*y_max + right_fit[2]  
    return (left_x + right_x) / 2  
  
def cal_center_departure(img, left_fit, right_fit, left_type, right_type):  
    if left_fit is None or right_fit is None:  
        cv2.putText(img, 'Vehicle detection failed', (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)  
        return img, 0.0  
      
    y_max = img.shape[0]  
    left_x = left_fit[0]*y_max**2 + left_fit[1]*y_max + left_fit[2]  
    right_x = right_fit[0]*y_max**2 + right_fit[1]*y_max + right_fit[2]  
    xm_per_pix = 3.7/700  
      
    car_center = img.shape[1] / 2  
    lane_center_current = (left_x + right_x) / 2  
    center_depart = (lane_center_current - car_center) * xm_per_pix  
      
    if center_depart > 0:  
        text = 'Vehicle is {:.2f}m right of center'.format(center_depart)  
    elif center_depart < 0:  
        text = 'Vehicle is {:.2f}m left of center'.format(-center_depart)  
    else:  
        text = 'Vehicle is in the center'  
    cv2.putText(img, text, (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)  
      
    cv2.putText(img, f'Left Line: {left_type}', (20, 150), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)  
    cv2.putText(img, f'Right Line: {right_type}', (20, 200), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)  
      
    return img, center_depart  
  
def process_image(img):  
    global latest_metadata  
    # 图像去畸变  
    undistort_img = img_undistort(img, mtx, dist)  
    # 车道线检测  
    rigin_pipline_img = pipeline(undistort_img)  
    # 透视变换  
    transform_img = img_perspect_transform(rigin_pipline_img, M)  
    # 拟合车道线并识别类型  
    left_fit, right_fit, left_type, right_type = cal_line_param(transform_img)  
    # 绘制安全区域  
    result = fill_lane_poly(transform_img, left_fit, right_fit)  
    transform_img_inv = img_perspect_transform(result, M_inverse)  
  
    # 曲率和偏离距离及类型显示  
    transform_img_inv, curvature = cal_radius(transform_img_inv, left_fit, right_fit)  
    transform_img_inv, departure = cal_center_departure(transform_img_inv, left_fit, right_fit, left_type, right_type)  
      
    # 更新全局数据  
    latest_metadata = {  
        'left_type': left_type,  
        'right_type': right_type,  
        'curvature': curvature,  
        'departure': departure  
    }  
      
    transform_img_inv = cv2.addWeighted(undistort_img, 1, transform_img_inv, 0.5, 0)  
    return transform_img_inv  
  
# 初始化VisionIPC客户端  
def init_vipc_client():  
    global vipc_client  
    try:  
        vipc_client = VisionIpcClient("camerad", VisionStreamType.VISION_STREAM_ROAD, True)  
        if not vipc_client.connect(True):  
            print("Failed to connect to road camera stream")  
            return False  
          
        print(f"Connected to camera stream: {vipc_client.width}x{vipc_client.height}")  
        return True  
    except Exception as e:  
        print(f"Failed to initialize VisionIPC client: {e}")  
        return False  
  
# 从YUV转换为RGB  
def yuv_to_rgb(yuv_buf, width, height):  
    """将YUV420格式转换为RGB"""  
    try:  
        y_size = width * height  
        uv_size = y_size // 4  
          
        y = yuv_buf[:y_size].reshape(height, width)  
        u = yuv_buf[y_size:y_size + uv_size].reshape(height // 2, width // 2)  
        v = yuv_buf[y_size + uv_size:].reshape(height // 2, width // 2)  
          
        # 上采样UV通道  
        u_up = cv2.resize(u, (width, height), interpolation=cv2.INTER_LINEAR)  
        v_up = cv2.resize(v, (width, height), interpolation=cv2.INTER_LINEAR)  
          
        # YUV转RGB  
        yuv = cv2.merge([y, u_up, v_up])  
        rgb = cv2.cvtColor(yuv, cv2.COLOR_YUV2RGB)  
          
        return rgb  
    except Exception as e:  
        print(f"Error in YUV to RGB conversion: {e}")  
        return np.zeros((height, width, 3), dtype=np.uint8)  
  
# 修改后的帧生成函数  
def gen_frames():  
    global vipc_client  
      
    if vipc_client is None:  
        print("VisionIPC client not initialized")  
        return  
      
    while True:  
        try:  
            # 获取最新帧  
            frame_data = vipc_client.recv()  
            if frame_data is None:  
                time.sleep(0.01)  
                continue  
              
            # 转换YUV到RGB  
            rgb_img = yuv_to_rgb(frame_data.data, vipc_client.width, vipc_client.height)  
              
            # 处理图像进行车道线检测  
            processed_img = process_image(rgb_img)  
              
            # 转换为BGR用于JPEG编码  
            bgr_img = cv2.cvtColor(processed_img, cv2.COLOR_RGB2BGR)  
              
             # 编码为JPEG  
            ret, buffer = cv2.imencode('.jpg', bgr_img)  
            if ret:  
                frame_bytes = buffer.tobytes()  
                yield (b'--frame\r\n'  
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')  
              
        except Exception as e:  
            print(f"Error processing frame: {e}")  
            time.sleep(0.01)  
            continue  
  
@app.route('/video_feed')  
def video_feed():  
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')  
  
@app.route('/metadata')  
def get_metadata():  
    return jsonify(latest_metadata)  
  
@app.route('/')  
def index():  
    return render_template('index.html')  
  
# 初始化全局参数  
ret, mtx, dist, rvecs, tvecs = cal_calibrate_params(file_paths)  
# 透视变换参考点 (根据comma3摄像头分辨率调整)  
points = [[850, 550], [1078, 550], [300, 950], [1628, 950]]  
# 获取透视变换矩阵  
ref_img = cv2.imread('./test/straight_lines2.jpg') if os.path.exists('./test/straight_lines2.jpg') else np.zeros((1208, 1928, 3), dtype=np.uint8)  
M, M_inverse = cal_perspective_params(ref_img, points)  
  
if __name__ == "__main__":  
    # 初始化VisionIPC客户端  
    if not init_vipc_client():  
        print("Failed to initialize camera client. Exiting...")  
        exit(1)  
      
    print("正在启动 Web 服务器，请访问 http://localhost:8888")  
    print("确保已启动openpilot的camerad服务")  
    app.run(host='0.0.0.0', port=8888, debug=False, threaded=True)