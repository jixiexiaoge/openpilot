#pragma once

#include "opendbc/safety/declarations.h"

#if defined(__has_include)
  #if __has_include("panda/board/faults_declarations.h")
    #include "panda/board/faults_declarations.h"
  #endif
#endif

#ifndef FAULT_RELAY_MALFUNCTION
  #define FAULT_RELAY_MALFUNCTION (1UL << 0)
  void fault_occurred(uint32_t fault);
#endif
