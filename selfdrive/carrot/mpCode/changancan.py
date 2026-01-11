crc8_tab = [0x0, 0x1d, 0x3a, 0x27, 0x74, 0x69, 0x4e, 0x53,
  0xe8, 0xf5, 0xd2, 0xcf, 0x9c, 0x81, 0xa6, 0xbb,
  0xcd, 0xd0, 0xf7, 0xea, 0xb9, 0xa4, 0x83, 0x9e,
  0x25, 0x38, 0x1f, 0x2, 0x51, 0x4c, 0x6b, 0x76,
  0x87, 0x9a, 0xbd, 0xa0, 0xf3, 0xee, 0xc9, 0xd4,
  0x6f, 0x72, 0x55, 0x48, 0x1b, 0x6, 0x21, 0x3c,
  0x4a, 0x57, 0x70, 0x6d, 0x3e, 0x23, 0x4, 0x19,
  0xa2, 0xbf, 0x98, 0x85, 0xd6, 0xcb, 0xec, 0xf1,
  0x13, 0xe, 0x29, 0x34, 0x67, 0x7a, 0x5d, 0x40,
  0xfb, 0xe6, 0xc1, 0xdc, 0x8f, 0x92, 0xb5, 0xa8,
  0xde, 0xc3, 0xe4, 0xf9, 0xaa, 0xb7, 0x90, 0x8d,
  0x36, 0x2b, 0xc, 0x11, 0x42, 0x5f, 0x78, 0x65,
  0x94, 0x89, 0xae, 0xb3, 0xe0, 0xfd, 0xda, 0xc7,
  0x7c, 0x61, 0x46, 0x5b, 0x8, 0x15, 0x32, 0x2f,
  0x59, 0x44, 0x63, 0x7e, 0x2d, 0x30, 0x17, 0xa,
  0xb1, 0xac, 0x8b, 0x96, 0xc5, 0xd8, 0xff, 0xe2,
  0x26, 0x3b, 0x1c, 0x1, 0x52, 0x4f, 0x68, 0x75,
  0xce, 0xd3, 0xf4, 0xe9, 0xba, 0xa7, 0x80, 0x9d,
  0xeb, 0xf6, 0xd1, 0xcc, 0x9f, 0x82, 0xa5, 0xb8,
  0x3, 0x1e, 0x39, 0x24, 0x77, 0x6a, 0x4d, 0x50,
  0xa1, 0xbc, 0x9b, 0x86, 0xd5, 0xc8, 0xef, 0xf2,
  0x49, 0x54, 0x73, 0x6e, 0x3d, 0x20, 0x7, 0x1a,
  0x6c, 0x71, 0x56, 0x4b, 0x18, 0x5, 0x22, 0x3f,
  0x84, 0x99, 0xbe, 0xa3, 0xf0, 0xed, 0xca, 0xd7,
  0x35, 0x28, 0xf, 0x12, 0x41, 0x5c, 0x7b, 0x66,
  0xdd, 0xc0, 0xe7, 0xfa, 0xa9, 0xb4, 0x93, 0x8e,
  0xf8, 0xe5, 0xc2, 0xdf, 0x8c, 0x91, 0xb6, 0xab,
  0x10, 0xd, 0x2a, 0x37, 0x64, 0x79, 0x5e, 0x43,
  0xb2, 0xaf, 0x88, 0x95, 0xc6, 0xdb, 0xfc, 0xe1,
  0x5a, 0x47, 0x60, 0x7d, 0x2e, 0x33, 0x14, 0x9,
  0x7f, 0x62, 0x45, 0x58, 0xb, 0x16, 0x31, 0x2c,
  0x97, 0x8a, 0xad, 0xb0, 0xe3, 0xfe, 0xd9, 0xc4]

def crc_calculate_crc8(data):
  crc = 0xFF

  for byte in data:
    crc = crc8_tab[crc ^ byte]

  return crc ^ 0xFF


def crc16_ccitt_false(data: bytes, poly=0x1021, init_val=0xFFFF) -> int:
    crc = init_val
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ poly
            else:
                crc <<= 1
            crc &= 0xFFFF  # 保持16位
    return crc


def create_244_command(packer, msg: dict, accel, counter, longActive):
    values = {}
    values = {s: msg[s] for s in [
        "sig_108",
        "sig_107",
        "sig_106",
        "sig_105",
        "sig_104",
        "sig_103",
        "sig_102",
        "sig_101",
        "sig_100",
        "sig_099",
        "sig_098",
        "sig_097",
        "sig_096",
        "sig_095",
        "sig_094",
        "sig_093",
        "sig_092",
        "sig_091",
        "sig_090",
        "sig_089",
        "sig_088",
        "sig_087",
        "sig_086",
        "sig_085",
        "sig_084",
        "sig_083",
        "sig_082",
        "sig_081",
    ]}

    # 改进刹车响应性
    brake_value = 0
    if accel < -0.1:
        # 非线性映射，使轻微减速更敏感，强刹车更强力
        if accel < -1.5:
            # 强刹车区域
            brake_value = 1
        else:
            # 正常减速区域，增强响应性
            brake_value = 1 if accel < -0.5 else 0

    values.update({
        "sig_081": accel,  # 加速度
        "sig_084": 1,
        "sig_088": brake_value,  # 改进刹车激活逻辑
        "sig_092": counter,
        "sig_103": counter,
        "sig_091": 3 if longActive else 2,
        # 调整加速度响应曲线，提高低速区域响应性
        "sig_099": (120 + (accel - 0.05) /0.03 * 30)-5000 if accel > 0 else -5000,
        "sig_100": 1 if longActive else 0,
    })
    dat = packer.make_can_msg("msg_016", 0, values)[1]
    values["sig_093"] = crc_calculate_crc8(dat[:7])
    values["sig_104"] = crc_calculate_crc8(dat[8:15])
    return packer.make_can_msg("msg_016", 0, values)


def create_1BA_command(packer, msg: dict, angle, latCtrlActive, counter):
    values = {}
    values = {s: msg[s] for s in [
        "sig_080",
        "sig_079",
        "sig_078",
        "sig_077",
        "sig_076",
        "sig_075",
    ]}
    values.update({
        # 调整转向限制值，增加安全裕度
        "sig_075": 9.50,  # 增加转向限制
        "sig_076": -9.50,  # 增加转向限制
        "sig_077": angle,
        "sig_078": latCtrlActive,
        "sig_079": counter,
    })
    dat = packer.make_can_msg("msg_015", 0, values)[1]

    values["sig_080"] = crc_calculate_crc8(dat[:7])
    return packer.make_can_msg("msg_015", 0, values)

def create_17E_command(packer, msg: dict, longActive, counter):
    values = {}
    values = {s: msg[s] for s in [
        "sig_043",
        "sig_042",
        "sig_041",
        "sig_040",
        "sig_039",
        "sig_038",
        "sig_037",
        "sig_036",
        "sig_035",
        "sig_034",
        "sig_033",
    ]}
    values.update({
    #     "sig_033": sigs[0] + 1 if longActive else sigs[0],
        "sig_042": counter,
    })
    dat = packer.make_can_msg("msg_006", 0, values)[1]
    values["sig_043"] = crc_calculate_crc8(dat[:7])

    return packer.make_can_msg("msg_006", 2, values)

def create_307_command(packer, msg: dict, counter, cruiseSpeed):
    values = {}
    values = {s: msg[s] for s in [
        "sig_375",
        "sig_374",
        "sig_373",
        "sig_372",
        "sig_371",
        "sig_370",
        "sig_369",
        "sig_368",
        "sig_367",
        "sig_366",
        "sig_365",
        "sig_364",
        "sig_363",
        "sig_362",
        "sig_361",
        "sig_360",
        "sig_359",
        "sig_358",
        "sig_357",
        "sig_356",
        "sig_355",
        "sig_354",
        "sig_353",
        "sig_352",
        "sig_351",
        "sig_350",
        "sig_349",
        "sig_348",
        "sig_347",
        "sig_346",
        "sig_345",
        "sig_344",
        "sig_343",
        "sig_342",
        "sig_341",
        "sig_340",
        "sig_339",
        "sig_338",
        "sig_337",
        "sig_336",
    ]}
    values.update({
        "sig_336": cruiseSpeed,
        # "sig_339": 2,
        # "sig_337": 1,
        # "sig_341": 1,
        # "sig_340": 0,
        # "sig_372": sigs[0],
        # "sig_373": sigs[1],
        # "sig_374": sigs[2],
        # "sig_375": sigs[3],
        "sig_342": counter,
        "sig_346": counter,
        "sig_348": counter,
        "sig_354": counter,
    })
    dat = packer.make_can_msg("msg_037", 0, values)[1]
    values["sig_343"] = crc_calculate_crc8(dat[:7])
    values["sig_347"] = crc_calculate_crc8(dat[8:15])
    values["sig_349"] = crc_calculate_crc8(dat[16:23])
    values["sig_355"] = crc_calculate_crc8(dat[24:31])
    return packer.make_can_msg("msg_037", 0, values)


def create_31A_command(packer, msg: dict, counter, longActive):
    values = {}
    values = {s: msg[s] for s in [
        "sig_423",
        "sig_422",
        "sig_421",
        "sig_420",
        "sig_419",
        "sig_418",
        "sig_417",
        "sig_416",
        "sig_415",
        "sig_414",
        "sig_413",
        "sig_412",
        "sig_411",
        "sig_410",
        "sig_409",
        "sig_408",
        "sig_407",
        "sig_406",
        "sig_405",
        "sig_404",
        "sig_403",
        "sig_402",
        "sig_401",
        "sig_400",
        "sig_399",
        "sig_398",
        "sig_397",
        "sig_396",
        "sig_395",
        "sig_394",
        "sig_393",
        "sig_392",
        "sig_391",
        "sig_390",
        "sig_389",
        "sig_388",
        "sig_387",
        "sig_386",
    ]}
    values.update({
        # 在退出智能驾驶时更好地处理控制权转移
        "sig_390": 1,  # 设置为常开以改善控制权转移
        "sig_398": 1,  # 设置为常开以改善控制权转移
        "sig_408": 3 if longActive else 0,  # 完全关闭而不是部分激活
        "sig_410": 1,
        "sig_411": 2 if longActive else 0,
        "sig_395": counter,
        "sig_406": counter,
        "sig_415": counter,
        "sig_422": counter,
    })
    dat = packer.make_can_msg("msg_040", 0, values)[1]
    values["sig_396"] = crc_calculate_crc8(dat[:7])
    values["sig_407"] = crc_calculate_crc8(dat[8:15])
    values["sig_416"] = crc_calculate_crc8(dat[16:23])
    values["sig_423"] = crc_calculate_crc8(dat[24:31])
    return packer.make_can_msg("msg_040", 0, values)

