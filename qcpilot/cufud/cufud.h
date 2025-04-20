#ifndef __QCPILOT_CUFUD_CUFUD_H__
#define __QCPILOT_CUFUD_CUFUD_H__

#include <array>
#include <memory>
#include <optional>
#include <tuple>
#include "cereal/messaging/messaging.h"
#include "openpilot/common/ratekeeper.h"
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

class CuFuD {
  public:
    CuFuD(const cereal::CarParams::Reader &carParams);
    void loop();

  private:
    using VehicleState = ::cereal::QcPilotCufuState::VehicleState;

    void step();
    void updateInput();
    void updateEvaluators();
    void consolidateResult();
    void publishResult();

    // const cereal::CarParams::Reader &carParams_;
    RateKeeper rateKeeper_;
    bool isControllingEnabled_ {false};
    bool isSignalHealthy_ {false};
    bool isCameraHealthy_ {false};
    bool isSensorHealthy_ {false};
    bool isMyselfNotLagging_ {false};
    VehicleState vehicleState_ {VehicleState::ERROR};

    std::unique_ptr<Context> contextPtr_;
    std::unique_ptr<SubSocket> mazdaStateSockPtr_;
    AlignedBuffer mazdaStateBuf_;
    std::unique_ptr<SubMaster> subMasterPtr_;
    std::unique_ptr<SubMaster> subMasterCameraPtr_;
    std::unique_ptr<SubMaster> subMasterSensorPtr_;

    PubMaster pubMaster_;

    std::optional<cereal::QcMazdaState::Reader> mazdaStateReaderOpt_;
    std::optional<cereal::CarState::Reader> carStateReaderOpt_;
    std::optional<cereal::DeviceState::Reader> deviceStateReaderOpt_;
    std::optional<cereal::PeripheralState::Reader> peripheralStateReaderOpt_;
    std::optional<cereal::LiveCalibrationData::Reader> liveCalibrationReaderOpt_;
    std::optional<capnp::List<cereal::PandaState, capnp::Kind::STRUCT>::Reader>
      pandaStatesReaderOpt_;
    std::optional<cereal::RadarState::Reader> radarStateReaderOpt_;
    std::optional<cereal::LivePose::Reader> livePoseReaderOpt_;

    evaluators::ConstEvaluator carRecognizedEvaluator_;
    evaluators::ConstEvaluator onCarEvaluator_;
    evaluators::InitTimeoutEvaluator initTimeoutEvaluator_;
    evaluators::CarSpeedEvaluator carSpeedEvaluator_;
    evaluators::CanValidEvaluator canValidEvaluator_;
    evaluators::ResourceEvaluator resourceEvaluator_;
    evaluators::HardwareEvaluator hardwareEvaluator_;
    evaluators::CalibratedEvaluator calibratedEvaluator_;
    evaluators::PandaSafetyConfigEvaluator pandaSafetyConfigEvaluator_;
    evaluators::ControlAllowedEvaluator controlAllowedEvaluator_;
    evaluators::EchoEvaluator signalHealthyEvaluator_;
    evaluators::EchoEvaluator cameraHealthyEvaluator_;
    evaluators::EchoEvaluator realtimeEvaluator_;
    evaluators::RadarStateEvaluator radarStateEvaluator_;
    evaluators::PosenetEvaluator posenetEvaluator_;
    evaluators::EchoEvaluator sensorHealthyEvaluator_;
    evaluators::ChassisEvaluator chassisEvaluator_;


    std::array<evaluators::Evaluator *, 17U> evaluators_;
};

}    // namespace cufu
}    // namespace qcpilot

#endif