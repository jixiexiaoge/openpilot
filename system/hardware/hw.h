#pragma once

#include <string>

#include "system/hardware/base.h"
#include "common/util.h"

#if __TICI__
#include "system/hardware/tici/hardware.h"
#define Hardware HardwareTici
#else
#include "system/hardware/pc/hardware.h"
#define Hardware HardwarePC
#endif

namespace Path {
  inline std::string openpilot_prefix() {
    return util::getenv("OPENPILOT_PREFIX", "");
  }

  inline std::string comma_home() {
    return util::getenv("HOME") + "/.comma" + Path::openpilot_prefix();
  }

  inline std::string log_root() {
    if (const char *env = getenv("LOG_ROOT")) {
      return env;
    }
    return Hardware::PC() ? Path::comma_home() + "/media/0/realdata" : "/data/media/0/realdata";
  }

  inline std::string params() {
    return util::getenv("PARAMS_ROOT", Hardware::PC() ? (Path::comma_home() + "/params") : "/data/params");
  }

  inline std::string persist_root() {
    if (Hardware::PC()) {
      return Path::comma_home() + "/persist";
    }

    static const std::string root = []() {
      constexpr const char *kPersist = "/persist";
      constexpr const char *kDataPersist = "/data/persist";
      if (access(kPersist, W_OK) == 0) {
        return std::string(kPersist);
      }
      if (access(kDataPersist, W_OK) == 0) {
        return std::string(kDataPersist);
      }
      return std::string(kPersist);
    }();
    return root;
  }

  inline std::string rsa_file() {
    return Path::persist_root() + "/comma/id_rsa";
  }

  inline std::string swaglog_ipc() {
    return "ipc:///tmp/logmessage" + Path::openpilot_prefix();
  }

  inline std::string download_cache_root() {
    if (const char *env = getenv("COMMA_CACHE")) {
      return env;
    }
    return "/tmp/comma_download_cache" + Path::openpilot_prefix() + "/";
  }

 inline std::string shm_path() {
    #ifdef __APPLE__
     return"/tmp";
    #else
     return "/dev/shm";
    #endif
 }

  inline std::string model_root() {
    return Hardware::PC() ? Path::comma_home() + "/media/0/models" : "/data/media/0/models";
  }

  inline std::string screen_recordings_root() {
    return Hardware::PC() ? Path::comma_home() + "/media/0/screen_recordings" : "/data/media/0/screen_recordings";
  }
}  // namespace Path
