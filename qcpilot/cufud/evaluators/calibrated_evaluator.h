#ifndef __QCPILOT_CUFUD_EVALUATORS_CALIBRATED_EVALUATOR_H__
#define __QCPILOT_CUFUD_EVALUATORS_CALIBRATED_EVALUATOR_H__

#include <optional>
#include "cereal/messaging/messaging.h"
#include "openpilot/qcpilot/cufud/evaluators/evaluator.h"


namespace qcpilot {
namespace cufu {
namespace evaluators {

class CalibratedEvaluator : public Evaluator {
  public:
    CalibratedEvaluator(
      const std::optional<cereal::LiveCalibrationData::Reader> &liveCalibrationOpt) :
        liveCalibrationOpt_ {liveCalibrationOpt} {}

    inline virtual void update() override {
        if (liveCalibrationOpt_.has_value()) {
            isSatisfied_ = liveCalibrationOpt_->getCalStatus() ==
                           cereal::LiveCalibrationData::Status::CALIBRATED;
        }
    }

  private:
    const std::optional<cereal::LiveCalibrationData::Reader> &liveCalibrationOpt_;
};
}    // namespace evaluators
}    // namespace cufu
}    // namespace qcpilot

#endif
