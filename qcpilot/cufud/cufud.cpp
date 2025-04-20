#include "openpilot/qcpilot/cufud/cufud.h"
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <memory>
#include <optional>
#include <type_traits>
#include "cereal/messaging/messaging.h"
#include "openpilot/qcpilot/cufud/evaluators/calibrated_evaluator.h"
#include "openpilot/qcpilot/cufud/evaluators/can_valid_evaluator.h"
#include "openpilot/qcpilot/cufud/evaluators/car_recognized_evaluator.h"
#include "openpilot/qcpilot/cufud/evaluators/car_speed_evaluator.h"
#include "openpilot/qcpilot/cufud/evaluators/chassis_evaluator.h"
#include "openpilot/qcpilot/cufud/evaluators/const_evaluator.h"
#include "openpilot/qcpilot/cufud/evaluators/control_allowed_evaluator.h"
#include "openpilot/qcpilot/cufud/evaluators/echo_evaluator.h"
#include "openpilot/qcpilot/cufud/evaluators/evaluator.h"
#include "openpilot/qcpilot/cufud/evaluators/hardware_evaluator.h"
#include "openpilot/qcpilot/cufud/evaluators/init_timeout_evaluator.h"
#include "openpilot/qcpilot/cufud/evaluators/panda_safety_config_evaluator.h"
#include "openpilot/qcpilot/cufud/evaluators/posenet_evaluator.h"
#include "openpilot/qcpilot/cufud/evaluators/radar_state_evaluator.h"
#include "openpilot/qcpilot/cufud/evaluators/resource_evaluator.h"

namespace qcpilot {
namespace cufu {


const std::vector<const char *> kBasicSignals {"deviceState",
                                               "peripheralState",
                                               "liveCalibration",
                                               "pandaStates",
                                               "livePose",

                                               "modelV2",
                                               "controlsState",
                                               "radarState",
                                               // "carParams",
                                               "driverMonitoringState",
                                               "driverStateV2",
                                               "wideRoadCameraState",
                                               "managerState",
                                               "selfdriveState",
                                               "longitudinalPlan",
                                               "carState"};

const std::vector<const char *> kCameraSingals {
  "roadCameraState", "driverCameraState", "wideRoadCameraState"};

const std::vector<const char *> kSensorSingals {"accelerometer", "gyroscope"};

CuFuD::CuFuD(const cereal::CarParams::Reader &carParams) :
    // carParams_ {carParams},
    rateKeeper_ {"cufud", 100},
    isControllingEnabled_ {false},
    isSignalHealthy_ {false},
    isCameraHealthy_ {false},
    isSensorHealthy_ {false},
    isMyselfNotLagging_ {false},
    vehicleState_ {VehicleState::ERROR},
    contextPtr_ {Context::create()},
    mazdaStateSockPtr_ {SubSocket::create(contextPtr_.get(), "qcMazdaState")},
    subMasterPtr_ {std::make_unique<SubMaster>(kBasicSignals)},
    subMasterCameraPtr_ {std::make_unique<SubMaster>(kCameraSingals)},
    subMasterSensorPtr_ {std::make_unique<SubMaster>(kSensorSingals)},
    pubMaster_ {{"qcPilotCufuState"}},
    carRecognizedEvaluator_ {carParams.getBrand() != "mock"},
    onCarEvaluator_ {!carParams.getNotCar()},
    initTimeoutEvaluator_ {carStateReaderOpt_},
    carSpeedEvaluator_ {carStateReaderOpt_},
    canValidEvaluator_ {carStateReaderOpt_},
    resourceEvaluator_ {deviceStateReaderOpt_},
    hardwareEvaluator_ {peripheralStateReaderOpt_, deviceStateReaderOpt_},
    calibratedEvaluator_ {liveCalibrationReaderOpt_},
    pandaSafetyConfigEvaluator_ {carParams, pandaStatesReaderOpt_},
    controlAllowedEvaluator_ {isControllingEnabled_, pandaStatesReaderOpt_},
    signalHealthyEvaluator_ {isSignalHealthy_},
    cameraHealthyEvaluator_ {isCameraHealthy_},
    realtimeEvaluator_ {isMyselfNotLagging_},
    radarStateEvaluator_ {radarStateReaderOpt_},
    posenetEvaluator_ {livePoseReaderOpt_},
    sensorHealthyEvaluator_ {isSensorHealthy_},
    chassisEvaluator_ {carStateReaderOpt_},
    evaluators_ {&carRecognizedEvaluator_,
                 &onCarEvaluator_,
                 &initTimeoutEvaluator_,
                 &carSpeedEvaluator_,
                 &canValidEvaluator_,
                 &resourceEvaluator_,
                 &hardwareEvaluator_,
                 &calibratedEvaluator_,
                 &pandaSafetyConfigEvaluator_,
                 &controlAllowedEvaluator_,
                 &signalHealthyEvaluator_,
                 &cameraHealthyEvaluator_,
                 &realtimeEvaluator_,
                 &radarStateEvaluator_,
                 &posenetEvaluator_,
                 &sensorHealthyEvaluator_,
                 &chassisEvaluator_} {
    assert(mazdaStateSockPtr_ != nullptr);
    mazdaStateSockPtr_->setTimeout(20);    // MazdaState runs at 100Hz
    assert(subMasterPtr_ != nullptr);
    assert(subMasterCameraPtr_ != nullptr);
    assert(subMasterSensorPtr_ != nullptr);
    mazdaStateReaderOpt_.reset();
    carStateReaderOpt_.reset();
    deviceStateReaderOpt_.reset();
    peripheralStateReaderOpt_.reset();
    liveCalibrationReaderOpt_.reset();
    pandaStatesReaderOpt_.reset();
    radarStateReaderOpt_.reset();
    livePoseReaderOpt_.reset();
}

void CuFuD::loop() {
    while (true) {
        step();
        // No need to keep time, just monitor time. Because read block by carState
        isMyselfNotLagging_ = !rateKeeper_.monitorTime();
    }
}

void CuFuD::step() {
    updateInput();
    updateEvaluators();
    consolidateResult();
    publishResult();
}


void CuFuD::updateInput() {
    // Clear previous input
    mazdaStateReaderOpt_.reset();
    carStateReaderOpt_.reset();
    deviceStateReaderOpt_.reset();
    peripheralStateReaderOpt_.reset();
    liveCalibrationReaderOpt_.reset();
    pandaStatesReaderOpt_.reset();
    radarStateReaderOpt_.reset();
    livePoseReaderOpt_.reset();

    // Wait/Block for carState
    std::unique_ptr<Message> msg {mazdaStateSockPtr_->receive(false)};
    subMasterPtr_->update(0);
    subMasterCameraPtr_->update(0);
    subMasterSensorPtr_->update(0);
    if (msg) {
        capnp::FlatArrayMessageReader msgReader(mazdaStateBuf_.align(msg.get()));
        cereal::Event::Reader event = msgReader.getRoot<cereal::Event>();
        mazdaStateReaderOpt_ = event.getQcMazdaState();

        bool isCrzAvailable = mazdaStateReaderOpt_->getIsCruiseAvailable();
        bool isCruiseActive = mazdaStateReaderOpt_->getIsCruiseActive();
        bool isAccActive = mazdaStateReaderOpt_->getIsAccActive();

        if (isCrzAvailable) {
            if (isCruiseActive) {
                if (isAccActive) {
                    vehicleState_ = VehicleState::ACTIVE;
                } else {
                    vehicleState_ = VehicleState::HOLD;
                }
            } else {
                vehicleState_ = VehicleState::AVAILABLE;
            }
        } else {
            vehicleState_ = VehicleState::DISABLED;
        }

        std::printf("%hu\r\n", static_cast<std::uint16_t>(vehicleState_));


        if (subMasterPtr_->updated("carState")) {
            carStateReaderOpt_ = (*subMasterPtr_)["carState"].getCarState();
        }
        if (subMasterPtr_->updated("deviceState")) {
            deviceStateReaderOpt_ = (*subMasterPtr_)["deviceState"].getDeviceState();
        }
        if (subMasterPtr_->updated("peripheralState")) {
            peripheralStateReaderOpt_ = (*subMasterPtr_)["peripheralState"].getPeripheralState();
        }
        if (subMasterPtr_->updated("liveCalibration")) {
            liveCalibrationReaderOpt_ = (*subMasterPtr_)["liveCalibration"].getLiveCalibration();
        }
        if (subMasterPtr_->updated("pandaStates")) {
            pandaStatesReaderOpt_ = (*subMasterPtr_)["pandaStates"].getPandaStates();
        }
        if (subMasterPtr_->updated("radarState")) {
            radarStateReaderOpt_ = (*subMasterPtr_)["radarState"].getRadarState();
        }
        if (subMasterPtr_->updated("livePose")) {
            livePoseReaderOpt_ = (*subMasterPtr_)["livePose"].getLivePose();
        }
    }

    isSignalHealthy_ = subMasterPtr_->allAliveAndValid();

    // if (!isSignalHealthy_) {
    //     for (const char *signalName : kBasicSignals) {
    //         if (!subMasterPtr_->alive(signalName)) {
    //             std::printf("%s not alive\r\n", signalName);
    //         }
    //         if (!subMasterPtr_->valid(signalName)) {
    //             std::printf("%s not valid\r\n", signalName);
    //         }
    //     }
    // }
    isCameraHealthy_ = subMasterCameraPtr_->allAliveAndValid();
    isSensorHealthy_ = subMasterSensorPtr_->allAliveAndValid();
}

void CuFuD::updateEvaluators() {
    for (auto &evaluator : evaluators_) {
        evaluator->update();
    }
}

void CuFuD::consolidateResult() {
    bool isConditionSatisfied = true;
    for (const auto &evaluator : evaluators_) {
        isConditionSatisfied &= evaluator->isSatisfied();
    }

    // std::printf("long: %d  ", isConditionSatisfied);
    // std::vector<bool> evaresult;
    // for (auto &evaluator : evaluators_) {
    //     evaresult.push_back(evaluator->isSatisfied());
    // }
    // for (const bool b : evaresult) {
    //     std::printf("%d ", b);
    // }
    // std::printf("\r");

    isControllingEnabled_ = isConditionSatisfied;
}

void CuFuD::publishResult() {
    MessageBuilder message;
    cereal::QcPilotCufuState::Builder qcPilotCufuStateBuilder {
      message.initEvent().initQcPilotCufuState()};
    cereal::QcPilotCufuState::StateEvaluators::Builder evaluatorsBuilder {
      qcPilotCufuStateBuilder.initEvaluators()};

    evaluatorsBuilder.setCarRecognized(carRecognizedEvaluator_.isSatisfied());
    evaluatorsBuilder.setOnCar(onCarEvaluator_.isSatisfied());
    evaluatorsBuilder.setInitTimeout(initTimeoutEvaluator_.isSatisfied());
    evaluatorsBuilder.setCarSpeed(carSpeedEvaluator_.isSatisfied());
    evaluatorsBuilder.setCanValid(canValidEvaluator_.isSatisfied());
    evaluatorsBuilder.setResource(resourceEvaluator_.isSatisfied());
    evaluatorsBuilder.setHardware(hardwareEvaluator_.isSatisfied());
    evaluatorsBuilder.setCalibrated(calibratedEvaluator_.isSatisfied());
    evaluatorsBuilder.setPandaSafetyConfig(pandaSafetyConfigEvaluator_.isSatisfied());
    evaluatorsBuilder.setControlAllowed(controlAllowedEvaluator_.isSatisfied());
    evaluatorsBuilder.setSignalHealthy(signalHealthyEvaluator_.isSatisfied());
    evaluatorsBuilder.setCameraHealthy(cameraHealthyEvaluator_.isSatisfied());
    evaluatorsBuilder.setRealtime(realtimeEvaluator_.isSatisfied());
    evaluatorsBuilder.setRadarState(radarStateEvaluator_.isSatisfied());
    evaluatorsBuilder.setPosenet(posenetEvaluator_.isSatisfied());
    evaluatorsBuilder.setSensorHealthy(sensorHealthyEvaluator_.isSatisfied());
    evaluatorsBuilder.setChassis(chassisEvaluator_.isSatisfied());


    qcPilotCufuStateBuilder.setIsControlSatisfied(isControllingEnabled_);
    qcPilotCufuStateBuilder.setVehicleState(vehicleState_);
    pubMaster_.send("qcPilotCufuState", message);
}

}    // namespace cufu
}    // namespace qcpilot