#ifndef __QCPILOT_CUFUD_EVALUATORS_CHASSIS_EVALUATOR_H__
#define __QCPILOT_CUFUD_EVALUATORS_CHASSIS_EVALUATOR_H__

#include <optional>
#include "cereal/messaging/messaging.h"
#include "openpilot/qcpilot/cufud/evaluators/evaluator.h"


namespace qcpilot {
namespace cufu {
namespace evaluators {

class ChassisEvaluator : public Evaluator {
  public:
    ChassisEvaluator(const std::optional<cereal::QcMazdaState::Reader>& mazdaStateReaderOpt) :
        mazdaStateReaderOpt_ {mazdaStateReaderOpt} {}

    inline virtual void update() override {
        if (mazdaStateReaderOpt_.has_value()) {
            const bool isLkasBlocked = mazdaStateReaderOpt_->getIsLkasBlocked();
            isSatisfied_ = !isLkasBlocked;
        }
    }

  private:
    const std::optional<cereal::QcMazdaState::Reader>& mazdaStateReaderOpt_;
};
}    // namespace evaluators
}    // namespace cufu
}    // namespace qcpilot

#endif
