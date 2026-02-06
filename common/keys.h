#pragma once

#include <map>
#include <string>

// Model Signing Keys
// key_id → 공개키 (Base64) 매핑
// Ed25519 공개키 형식

static const std::map<std::string, std::string> MODEL_SIGNING_KEYS = {
    // Ed25519 공개키 (raw bytes, Base64 인코딩)
    {"key_2025_01", "yFPR4om9LyYvQjzRzSiyyso9wc2bP1egmg/PjKa79fg="},  // 현재 키
};

// 현재 모델 셀렉터 버전
static const int MODEL_SELECTOR_VERSION = 1;
