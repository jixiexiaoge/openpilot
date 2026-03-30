# Pixel 3에서 openpilot 모델 컴파일 가이드

> Google Pixel 3 (blueline, Snapdragon 845, Adreno 630)에서
> tinygrad QCOM 백엔드를 사용하여 openpilot 모델을 컴파일하는 전체 가이드

---

## 개요

comma 3X와 Pixel 3은 동일한 SoC(Snapdragon 845)와 GPU(Adreno 630)를 사용합니다.
comma 3X의 AGNOS(Ubuntu 기반 OS)에 포함된 OpenCL 라이브러리를 Pixel 3에 가져와서
tinygrad QCOM 백엔드로 모델을 컴파일할 수 있습니다.

### 동작 원리

```
tinygrad QCOM 백엔드
  ├── /dev/kgsl-3d0 (KGSL ioctl) → GPU 메모리 할당, 명령어 제출, 실행
  └── libOpenCL.so (OpenCL)      → 셰이더 소스코드 → GPU 바이너리 컴파일
```

### 주의사항

- Pixel 3의 RAM은 **4GB**로, 모델 컴파일 시 메모리가 부족할 수 있음
- 발열 쓰로틀링에 주의 (방열 권장)
- 이 가이드는 실험적이며, 공식 지원 경로가 아님

---

## Phase 1: Pixel 3 준비 (부트로더 언락 + LineageOS + Magisk)

### 1-1. 사전 준비

- PC에 Android SDK Platform Tools 설치 (adb, fastboot)
- Pixel 3에서 **개발자 옵션** 활성화 → **USB 디버깅** 켜기
- Pixel 3에서 **OEM 잠금 해제** 활성화 (설정 > 개발자 옵션)

### 1-2. 부트로더 언락

```bash
# PC에서
adb devices                    # 기기 연결 확인
adb reboot bootloader          # 부트로더 모드로 재부팅
fastboot devices               # fastboot 연결 확인
fastboot flashing unlock       # 부트로더 잠금 해제 (데이터 초기화됨!)
```

> ⚠️ 부트로더 언락 시 모든 데이터가 삭제됩니다.

### 1-3. LineageOS 설치

1. **Android 12 순정 펌웨어를 먼저 설치** (LineageOS 요구사항)
   - https://developers.google.com/android/images#blueline 에서 다운로드

2. **LineageOS 다운로드** (blueline)
   - https://wiki.lineageos.org/devices/blueline/
   - 최신 버전(22.x) 또는 안정적인 20/21 권장

3. **Lineage Recovery 플래시 및 설치**
```bash
# Lineage Recovery 플래시
fastboot flash boot boot.img

# 리커버리 부팅 후 LineageOS 사이드로드
adb -d sideload lineageos-*.zip
```

### 1-4. Magisk 루팅

1. Magisk APK 설치 (https://github.com/topjohnwu/Magisk/releases)
2. LineageOS의 `boot.img` 추출
3. Magisk 앱에서 **Install > Select and Patch a File** → boot.img 선택
4. 패치된 이미지를 PC로 복사 후 플래시:

```bash
adb pull /sdcard/Download/magisk_patched-*.img .
adb reboot bootloader
fastboot flash boot magisk_patched-*.img
fastboot reboot
```

5. Magisk 앱 실행 → "Installed" 확인

### 1-5. SELinux Permissive 설정 (영구)

**방법 A: Magisk 모듈 (권장 — 재부팅 후에도 유지)**

1. https://github.com/noobexon1/magisk_selinux_permissive 에서 ZIP 다운로드
2. Magisk > Modules > Install from storage → ZIP 선택
3. 재부팅

**방법 B: 수동 (임시 — 재부팅 시 초기화)**

```bash
su
setenforce 0
getenforce   # "Permissive" 출력 확인
```

---

## Phase 2: Termux 환경 설정

### 2-1. Termux 설치

> ⚠️ **F-Droid에서 설치** (Google Play 버전은 오래됨)
> https://f-droid.org/en/packages/com.termux/

### 2-2. 기본 패키지 설치

```bash
pkg update && pkg upgrade -y
pkg install -y python python-numpy python-pip clang make git
```

### 2-3. GPU 접근 확인

```bash
# KGSL 디바이스 확인
ls -la /dev/kgsl-3d0
# 출력: crw-rw-rw- 1 system system ... /dev/kgsl-3d0

# SELinux 확인
su -c getenforce
# 출력: Permissive
```

---

## Phase 3: comma 3X OpenCL 라이브러리 설치

Google Pixel 시리즈는 OpenCL을 제거/비활성화했으므로,
**comma 3X AGNOS에서 사용하는 동일한 라이브러리**를 가져옵니다.

### 3-1. agnos-builder에서 라이브러리 다운로드

```bash
# PC에서
git clone https://github.com/commaai/agnos-builder.git
cd agnos-builder
```

### 3-2. 필요한 파일 목록

#### GPU 펌웨어 (7개 파일)
`agnos-builder/userspace/firmware/` → Pixel 3의 `/lib/firmware/`

```
a630_gmu.bin      # GPU Management Unit 펌웨어
a630_sqe.fw       # 셰이더/시퀀서 엔진 펌웨어
a630_zap.b00      # GPU Secure Zone (세그먼트 0)
a630_zap.b01      # GPU Secure Zone (세그먼트 1)
a630_zap.b02      # GPU Secure Zone (세그먼트 2)
a630_zap.elf      # GPU Secure Zone ELF
a630_zap.mdt      # GPU Secure Zone 메타데이터
```

> 참고: Android/LineageOS에서는 GPU 펌웨어가 이미 포함되어 있으므로
> 이 파일들은 **보통 불필요**합니다. 문제 발생 시에만 복사하세요.

#### OpenCL 핵심 라이브러리 (3개 + 심볼릭 링크)
`agnos-builder/userspace/libs/` → Pixel 3의 `/vendor/lib64/` 또는 Termux `$PREFIX/lib/`

```
libOpenCL.so.1.0.0    # (89KB) Qualcomm OpenCL ICD 구현체
libOpenCL.so.1        → libOpenCL.so.1.0.0 (심볼릭 링크)
libOpenCL.so          → libOpenCL.so.1.0.0 (심볼릭 링크)
```

#### Qualcomm GPU 런타임 라이브러리 (3개)

```
libllvm-qcom.so       # (37MB) Qualcomm LLVM — 셰이더 컴파일러 백엔드 (가장 큰 파일)
libCB.so              # (2MB)  Command Buffer 라이브러리
libgsl.so             # (1.1MB) KGSL userspace 라이브러리
```

#### Android 프레임워크 shim 라이브러리 (8개 + 심볼릭 링크)

QC OpenCL 라이브러리의 런타임 의존성:

```
liblog.so.0.0.0       + liblog.so.0
libcutils.so.0.0.0    + libcutils.so.0
libutils.so.0.0.0     + libutils.so.0
libbase.so.0.0.0      + libbase.so.0
libbinder.so.0.0.0    + libbinder.so.0
libhardware.so.0.0.0  + libhardware.so.0
libsync.so.0.0.0      + libsync.so.0
libplatformconfig.so.0.0.0 + libplatformconfig.so.0
```

#### 추가 QC 라이브러리 (1개)

```
libqdMetaData.so      # (10KB) Qualcomm 디스플레이 메타데이터
```

### 3-3. 의존성 체인

```
tinygrad (ops_qcom.py)
  ├── /dev/kgsl-3d0 (직접 ioctl — 추가 라이브러리 불필요)
  └── CLCompiler → libOpenCL.so
                     ├── libllvm-qcom.so (LLVM 셰이더 컴파일러)
                     ├── libCB.so (Command Buffer)
                     ├── libgsl.so (KGSL userspace)
                     ├── liblog.so.0
                     ├── libcutils.so.0
                     ├── libutils.so.0
                     ├── libbase.so.0
                     ├── libbinder.so.0
                     ├── libhardware.so.0
                     ├── libsync.so.0
                     ├── libplatformconfig.so.0
                     └── libqdMetaData.so
```

### 3-4. Pixel 3에 설치

**옵션 A: /vendor/lib64/ 에 설치 (루팅 필요)**

```bash
# PC에서 agnos-builder/userspace/libs/ 의 모든 .so 파일을 Pixel 3로 전송
adb root
adb remount

# 핵심 라이브러리
adb push libOpenCL.so.1.0.0 /vendor/lib64/
adb shell "ln -sf libOpenCL.so.1.0.0 /vendor/lib64/libOpenCL.so"
adb shell "ln -sf libOpenCL.so.1.0.0 /vendor/lib64/libOpenCL.so.1"

# QC GPU 라이브러리
adb push libllvm-qcom.so /vendor/lib64/
adb push libCB.so /vendor/lib64/
adb push libgsl.so /vendor/lib64/

# Android shim 라이브러리 (모두 /vendor/lib64/ 에)
for lib in liblog libcutils libutils libbase libbinder libhardware libsync libplatformconfig; do
  adb push ${lib}.so.0.0.0 /vendor/lib64/
  adb shell "ln -sf ${lib}.so.0.0.0 /vendor/lib64/${lib}.so.0"
done

adb push libqdMetaData.so /vendor/lib64/
```

**옵션 B: Termux $PREFIX/lib/ 에 설치 (더 간단)**

```bash
# Termux 내에서 (파일을 미리 /sdcard/ 에 복사해둔 상태)
cp /sdcard/libs/*.so* $PREFIX/lib/

# 심볼릭 링크 생성
cd $PREFIX/lib
ln -sf libOpenCL.so.1.0.0 libOpenCL.so
ln -sf libOpenCL.so.1.0.0 libOpenCL.so.1
for lib in liblog libcutils libutils libbase libbinder libhardware libsync libplatformconfig; do
  ln -sf ${lib}.so.0.0.0 ${lib}.so.0
done
```

### 3-5. LD_LIBRARY_PATH 설정

```bash
# ~/.bashrc 에 추가
echo 'export LD_LIBRARY_PATH=/vendor/lib64:$PREFIX/lib:$LD_LIBRARY_PATH' >> ~/.bashrc
source ~/.bashrc
```

### 3-6. OpenCL 동작 확인

```bash
# clinfo 빌드 (선택사항)
pkg install -y clinfo
clinfo

# 기대 출력:
# Platform:  QUALCOMM Snapdragon(TM)
# Device:    QUALCOMM Adreno(TM)
# OpenCL:    2.0
```

---

## Phase 4: tinygrad 설치 및 테스트

### 4-1. tinygrad 설치

```bash
# openpilot에 포함된 tinygrad 사용 또는 최신 버전 클론
git clone https://github.com/tinygrad/tinygrad.git ~/tinygrad
cd ~/tinygrad
pip install -e .
pip install onnx
```

### 4-2. 기본 테스트

```bash
# OpenCL 백엔드 테스트
GPU=1 python -c "
from tinygrad import Tensor, Device
print('Device:', Device.DEFAULT)
t = Tensor([1, 2, 3]).realize()
print('Result:', t.numpy())
"

# QCOM 백엔드 테스트 (직접 KGSL)
QCOM=1 python -c "
from tinygrad import Tensor, Device
print('Device:', Device.DEFAULT)
t = Tensor([1, 2, 3]).realize()
print('Result:', t.numpy())
"
```

### 4-3. GPU ID 확인

tinygrad가 Adreno 630을 정상 인식하는지 확인:

```bash
QCOM=1 DEBUG=1 python -c "from tinygrad import Device; Device['QCOM']"
# gpu_id = 630 이 출력되어야 함 (700 미만이면 정상)
```

---

## Phase 5: openpilot 모델 컴파일

### 5-1. 모델 파일 준비

openpilot ONNX 모델을 Pixel 3에 복사:

```bash
# PC에서 (openpilot 저장소의 모델 파일)
adb push driving_vision.onnx /sdcard/models/
adb push driving_policy.onnx /sdcard/models/
```

### 5-2. 메타데이터 생성

```bash
cd ~/tinygrad  # 또는 openpilot 디렉토리

python /path/to/openpilot/selfdrive/modeld/get_model_metadata.py \
  /sdcard/models/driving_vision.onnx \
  /sdcard/models/driving_vision_metadata.pkl

python /path/to/openpilot/selfdrive/modeld/get_model_metadata.py \
  /sdcard/models/driving_policy.onnx \
  /sdcard/models/driving_policy_metadata.pkl
```

### 5-3. tinygrad 컴파일

```bash
# 환경 변수 설정 (comma 3X와 동일)
export DEV=QCOM
export FLOAT16=1
export NOLOCALS=1
export IMAGE=2
export JIT_BATCH_SIZE=0

# Vision 모델 컴파일
python ~/tinygrad/examples/openpilot/compile3.py \
  /sdcard/models/driving_vision.onnx \
  /sdcard/models/driving_vision_tinygrad.pkl

# Policy 모델 컴파일
python ~/tinygrad/examples/openpilot/compile3.py \
  /sdcard/models/driving_policy.onnx \
  /sdcard/models/driving_policy_tinygrad.pkl
```

### 5-4. 컴파일 결과 확인

성공 시 다음과 같은 출력:

```
loaded model
created tensors
run 0
run 1
run 2
captured XX kernels
jit run validated
kernel_count=XX, read_image_count=XX, gated_read_image_count=XX
mdl size is XX.XX M
pkl size is XX.XX M
**** compile done ****
```

### 5-5. 컴파일된 모델을 comma 3X로 전송 (선택)

```bash
# Pixel 3에서 컴파일한 PKL을 comma 3X의 /data/models/ 로 복사
scp /sdcard/models/*_tinygrad.pkl comma@<comma-ip>:/data/models/
scp /sdcard/models/*_metadata.pkl comma@<comma-ip>:/data/models/
```

---

## 트러블슈팅

### "libOpenCL.so not found" 에러

```bash
# 라이브러리 경로 확인
ls -la /vendor/lib64/libOpenCL*
ls -la $PREFIX/lib/libOpenCL*

# LD_LIBRARY_PATH 확인
echo $LD_LIBRARY_PATH

# 의존성 확인 (누락된 라이브러리 체크)
# readelf가 없으면: pkg install binutils
readelf -d /vendor/lib64/libOpenCL.so.1.0.0
```

### "Permission denied" /dev/kgsl-3d0

```bash
# SELinux 확인
su -c getenforce

# 권한 확인/수정
su -c "chmod 666 /dev/kgsl-3d0"
su -c "ls -laZ /dev/kgsl-3d0"
```

### OOM (Out of Memory) — 4GB RAM 한계

```bash
# 불필요한 앱/서비스 종료
su -c "am kill-all"

# Swap 활성화 (Magisk 모듈: JEROMEX Swap Manager)
# 또는 수동:
su
dd if=/dev/zero of=/data/swapfile bs=1M count=2048
mkswap /data/swapfile
swapon /data/swapfile

# 작은 모델부터 테스트
# dmonitoring_model이 driving_vision보다 작음
```

### GPU 타임아웃

```bash
# 타임아웃 시간 늘리기
export HCQDEV_WAIT_TIMEOUT_MS=60000

# 발열 모니터링
su -c "cat /sys/class/thermal/thermal_zone*/temp"
```

### 발열 관리

- 케이스 제거
- 선풍기/방열판 사용
- 충전하면서 컴파일 X (발열 증가)
- 한 번에 하나씩 컴파일

---

## 참고 링크

- [agnos-builder (OpenCL 라이브러리 소스)](https://github.com/commaai/agnos-builder)
- [tinygrad QCOM 백엔드](https://github.com/tinygrad/tinygrad/blob/master/tinygrad/runtime/ops_qcom.py)
- [LineageOS Pixel 3 (blueline)](https://wiki.lineageos.org/devices/blueline/)
- [Magisk](https://github.com/topjohnwu/Magisk/releases)
- [SELinux Permissive 모듈](https://github.com/noobexon1/magisk_selinux_permissive)
- [Freedreno Rusticl OpenCL (오픈소스 대안)](https://www.phoronix.com/news/Freedreno-Rusticl-Mesa-24.3)
- [Termux](https://f-droid.org/en/packages/com.termux/)
