#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

/* ===================== GPIO 定义 ===================== */
#define RELAY1_PIN 26
#define RELAY2_PIN 27

/* ===================== BLE UUID ===================== */
#define SERVICE_UUID        "12345678-1234-1234-1234-1234567890ab"
#define CHARACTERISTIC_UUID "87654321-4321-4321-4321-ba0987654321"

/* ===================== 全局变量 ===================== */
BLECharacteristic *pCharacteristic;
bool deviceConnected = false;
volatile unsigned long lastRelay1OnTime = 0;
volatile unsigned long lastRelay2OnTime = 0;
const unsigned long RELAY_AUTO_OFF_MS = 5000;

/* ===================== 继电器控制函数 ===================== */
void setRelay1(bool on) {
  digitalWrite(RELAY1_PIN, on ? HIGH : LOW);
  if (on) {
    lastRelay1OnTime = millis();
    if (lastRelay1OnTime == 0) lastRelay1OnTime = 1; // 避免0值冲突
  } else {
    lastRelay1OnTime = 0;
  }
}

void setRelay2(bool on) {
  digitalWrite(RELAY2_PIN, on ? HIGH : LOW);
  if (on) {
    lastRelay2OnTime = millis();
    if (lastRelay2OnTime == 0) lastRelay2OnTime = 1;
  } else {
    lastRelay2OnTime = 0;
  }
}

/* ===================== BLE 回调类 ===================== */
class MyServerCallbacks: public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) {
      deviceConnected = true;
    };
    void onDisconnect(BLEServer* pServer) {
      deviceConnected = false;
      // 断开连接时安全起见关闭继电器
      setRelay1(false);
      setRelay2(false);
      // 重新开始广播
      BLEDevice::startAdvertising();
    }
};

class MyCallbacks: public BLECharacteristicCallbacks {
    void onWrite(BLECharacteristic *pCharacteristic) {
      std::string value = pCharacteristic->getValue();
      if (value.length() >= 2) {
        uint8_t cmd = (uint8_t)value[0];
        uint8_t checksum = (uint8_t)value[1];
        
        // 校验逻辑：cmd + checksum == 0xFF
        if ((uint8_t)(cmd + checksum) == 0xFF) {
          if (cmd == 0xA1) { // 转向继电器开启
            setRelay1(true);
          } else if (cmd == 0xA0) { // 转向继电器关闭
            setRelay1(false);
          }
        }
      }
    }
};

/* ===================== 维护函数 (需在 loop 中调用) ===================== */
void updateRelays() {
  unsigned long now = millis();
  
  // 继电器1自动回弹 (5秒)
  if (lastRelay1OnTime > 0 && (now - lastRelay1OnTime >= RELAY_AUTO_OFF_MS)) {
    setRelay1(false);
  }
  
  // 继电器2自动回弹 (5秒)
  if (lastRelay2OnTime > 0 && (now - lastRelay2OnTime >= RELAY_AUTO_OFF_MS)) {
    setRelay2(false);
  }
}

/* ===================== 初始化函数 (需在 setup 中调用) ===================== */
void initESP32() {
  // 初始化 GPIO
  pinMode(RELAY1_PIN, OUTPUT);
  pinMode(RELAY2_PIN, OUTPUT);
  setRelay1(false);
  setRelay2(false);

  // 初始化 BLE
  BLEDevice::init("ESP32_Relay_Control");
  BLEServer *pServer = BLEDevice::createServer();
  pServer->setCallbacks(new MyServerCallbacks());

  BLEService *pService = pServer->createService(SERVICE_UUID);
  
  // 创建特征值，需包含 WRITE 权限
  pCharacteristic = pService->createCharacteristic(
                      CHARACTERISTIC_UUID,
                      BLECharacteristic::PROPERTY_READ |
                      BLECharacteristic::PROPERTY_WRITE |
                      BLECharacteristic::PROPERTY_NOTIFY
                    );

  pCharacteristic->setCallbacks(new MyCallbacks());
  pCharacteristic->addDescriptor(new BLE2902());

  pService->start();
  
  // 开始广播
  BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(SERVICE_UUID);
  pAdvertising->setScanResponse(true);
  pAdvertising->setMinPreferred(0x06);  // set value to 0x00 to not advertise this parameter
  pAdvertising->setMinPreferred(0x12);
  BLEDevice::startAdvertising();
}
