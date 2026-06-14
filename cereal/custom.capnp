using Cxx = import "./include/c++.capnp";
$Cxx.namespace("cereal");

@0xb526ba661d550a59;

# custom.capnp: a home for empty structs reserved for custom forks
# These structs are guaranteed to remain reserved and empty in mainline
# cereal, so use these if you want custom events in your fork.

# DO rename the structs
# DON'T change the identifier (e.g. @0x81c2f05a394cf4af)

struct AlwaysOnLateral {
  state @0 :AlwaysOnLateralState;
  enabled @1 :Bool;
  active @2 :Bool;
  available @3 :Bool;

  enum AlwaysOnLateralState {
    disabled @0;
    paused @1;
    enabled @2;
    softDisabling @3;
    overriding @4;
  }
}

# Same struct as Log.RadarState.LeadData
struct LeadData {
  dRel @0 :Float32;
  yRel @1 :Float32;
  vRel @2 :Float32;
  aRel @3 :Float32;
  vLead @4 :Float32;
  dPath @6 :Float32;
  vLat @7 :Float32;
  vLeadK @8 :Float32;
  aLeadK @9 :Float32;
  fcw @10 :Bool;
  status @11 :Bool;
  aLeadTau @12 :Float32;
  modelProb @13 :Float32;
  radar @14 :Bool;
  radarTrackId @15 :Int32 = -1;

  aLeadDEPRECATED @5 :Float32;
}

struct IQState @0x81c2f05a394cf4af {
  aol @0 :AlwaysOnLateral;

  enum AudibleAlert {
    none @0;

    engage @1;
    disengage @2;
    refuse @3;

    warningSoft @4;
    warningImmediate @5;

    prompt @6;
    promptRepeat @7;
    promptDistracted @8;

    # unused, these are reserved for upstream events so we don't collide
    reserved9 @9;
    reserved10 @10;
    reserved11 @11;
    reserved12 @12;
    reserved13 @13;
    reserved14 @14;
    reserved15 @15;
    reserved16 @16;
    reserved17 @17;
    reserved18 @18;
    reserved19 @19;
    reserved20 @20;
    reserved21 @21;
    reserved22 @22;
    reserved23 @23;
    reserved24 @24;
    reserved25 @25;
    reserved26 @26;
    reserved27 @27;
    reserved28 @28;
    reserved29 @29;
    reserved30 @30;

    promptSingleLow @31;
    promptSingleHigh @32;
  }
}

struct IQModelManager @0xaedffd8f31e7b55d {
  activeBundle @0 :ModelBundle;
  selectedBundle @1 :ModelBundle;
  availableBundles @2 :List(ModelBundle);

  struct DownloadUri {
    uri @0 :Text;
    sha256 @1 :Text;
  }

  enum DownloadStatus {
    notDownloading @0;
    downloading @1;
    downloaded @2;
    cached @3;
    failed @4;
  }

  struct DownloadProgress {
    status @0 :DownloadStatus;
    progress @1 :Float32;
    eta @2 :UInt32;
  }

  struct Artifact {
    fileName @0 :Text;
    downloadUri @1 :DownloadUri;
    downloadProgress @2 :DownloadProgress;
  }

  struct Model {
    type @0 :Type;
    artifact @1 :Artifact;  # Main artifact
    metadata @2 :Artifact;  # Metadata artifact

    enum Type {
      supercombo @0;
      navigation @1;
      vision @2;
      policy @3;
      offPolicy @4;
      onPolicy @5;
    }
  }

  enum Runner {
    snpe @0;
    tinygrad @1;
    stock @2;
  }

  struct Override {
    key @0 :Text;
    value @1 :Text;
  }

  struct ModelBundle {
    index @0 :UInt32;
    internalName @1 :Text;
    displayName @2 :Text;
    models @3 :List(Model);
    status @4 :DownloadStatus;
    generation @5 :UInt32;
    environment @6 :Text;
    runner @7 :Runner;
    is20hz @8 :Bool;
    ref @9 :Text;
    minimumSelectorVersion @10 :UInt32;
    overrides @11 :List(Override);
  }
}

struct IQPlan @0xf35cc4560bbf6ec2 {
  iqDynamic @0 :IQDynamicControl;
  longitudinalPlanSource @1 :LongitudinalPlanSource;
  iqNavState @2 :IQNavPlanState;
  speedLimit @3 :SpeedLimit;
  vTarget @4 :Float32;
  aTarget @5 :Float32;
  events @6 :List(IQOnroadEvent.Event);
  e2eAlerts @7 :E2eAlerts;

  struct IQDynamicControl {
    state @0 :IQDynamicControlState;
    enabled @1 :Bool;
    active @2 :Bool;

    enum IQDynamicControlState {
      acc @0;
      blended @1;
    }
  }

  struct IQNavPlanState {
    nav @0 :Nav;

    struct Nav {
      engaged @0 :Bool;
      provider @1 :IQNavState.LongitudinalProvider;
      state @2 :IQNavState.LongitudinalState;
      speedTarget @3 :Float32;
      accelTarget @4 :Float32;
      valid @5 :Bool;
    }
  }

  struct SpeedLimit {
    resolver @0 :Resolver;
    assist @1 :Assist;

    struct Resolver {
      speedLimit @0 :Float32;
      distToSpeedLimit @1 :Float32;
      source @2 :Source;
      speedLimitOffset @3 :Float32;
      speedLimitLast @4 :Float32;
      speedLimitFinal @5 :Float32;
      speedLimitFinalLast @6 :Float32;
      speedLimitValid @7 :Bool;
      speedLimitLastValid @8 :Bool;
    }

    struct Assist {
      state @0 :AssistState;
      enabled @1 :Bool;
      active @2 :Bool;
      vTarget @3 :Float32;
      aTarget @4 :Float32;
    }

    enum Source {
      none @0;
      car @1;
      map @2;
    }

    enum AssistState {
      disabled @0;
      inactive @1; # No speed limit set or not enabled by parameter.
      preActive @2;
      pending @3; # Awaiting new speed limit.
      adapting @4; # Reducing speed to match new speed limit.
      active @5; # Cruising at speed limit.
    }
  }

  enum LongitudinalPlanSource {
    cruise @0;
    nav @1;
    speedLimitAssist @2;
  }

  struct E2eAlerts {
    greenLightAlert @0 :Bool;
    leadDepartAlert @1 :Bool;
  }
}

struct IQOnroadEvent @0xda96579883444c35 {
  events @0 :List(Event);

  struct Event {
    name @0 :EventName;

    # event types
    enable @1 :Bool;
    noEntry @2 :Bool;
    warning @3 :Bool;   # alerts presented only when  enabled or soft disabling
    userDisable @4 :Bool;
    softDisable @5 :Bool;
    immediateDisable @6 :Bool;
    preEnable @7 :Bool;
    permanent @8 :Bool; # alerts presented regardless of openpilot state
    overrideLateral @10 :Bool;
    overrideLongitudinal @9 :Bool;
  }

  enum EventName {
    lkasEnable @0;
    lkasDisable @1;
    manualSteeringRequired @2;
    manualLongitudinalRequired @3;
    silentLkasEnable @4;
    silentLkasDisable @5;
    silentBrakeHold @6;
    silentWrongGear @7;
    silentReverseGear @8;
    silentDoorOpen @9;
    silentSeatbeltNotLatched @10;
    silentParkBrake @11;
    controlsMismatchLateral @12;
    hyundaiRadarTracksConfirmed @13;
    experimentalModeSwitched @14;
    wrongCarModeAlertOnly @15;
    pedalPressedAlertOnly @16;
    laneTurnLeft @17;
    laneTurnRight @18;
    speedLimitPreActive @19;
    speedLimitActive @20;
    speedLimitChanged @21;
    speedLimitPending @22;
    e2eChime @23;
    navTurnLeft @24;
    navTurnRight @25;
    navExitLeft @26;
    navExitRight @27;
    steeringOverrideReengageAlc @28;
    speedCameraAhead @29;
  }
}

struct IQCarParams @0x80ae746ee2596b11 {
  flags @0 :UInt32;        # flags for car specific quirks in iqpilot
  safetyParam @1 : Int16;  # flags for iqpilot's custom safety flags
  pcmCruiseSpeed @3 :Bool;
  enableGasInterceptor @4 :Bool;

  neuralNetworkFeedForward @2 :NeuralNetworkFeedForward;

  struct NeuralNetworkFeedForward {
    model @0 :Model;
    fuzzyFingerprint @1 :Bool;

    struct Model {
      path @0 :Text;
      name @1 :Text;
    }
  }
}

struct IQCarControl @0xa5cd762cd951a455 {
  aol @0 :AlwaysOnLateral;
  params @1 :List(Param);
  leadOne @2 :LeadData;
  leadTwo @3 :LeadData;
  angleOffsetDeg @4 :Float32;

  struct Param {
    key @0 :Text;
    type @2 :ParamType;
    value @3 :Data;

    valueDEPRECATED @1 :Text; # The data type change may cause issues with backwards compatibility.
  }

  enum ParamType {
    string @0;
    bool @1;
    int @2;
    float @3;
    time @4;
    json @5;
    bytes @6;
  }
}

struct IQBackupManager @0xf98d843bfd7004a3 {
  backupStatus @0 :Status;
  restoreStatus @1 :Status;
  backupProgress @2 :Float32;
  restoreProgress @3 :Float32;
  lastError @4 :Text;
  currentBackup @5 :BackupInfo;
  backupHistory @6 :List(BackupInfo);

  enum Status {
    idle @0;
    inProgress @1;
    completed @2;
    failed @3;
  }

  struct Version {
    major @0 :UInt16;
    minor @1 :UInt16;
    patch @2 :UInt16;
    build @3 :UInt16;
    branch @4 :Text;
  }

  struct MetadataEntry {
    key @0 :Text;
    value @1 :Text;
    tags @2 :List(Text);
  }

  struct BackupInfo {
    deviceId @0 :Text;
    version @1 :UInt32;
    config @2 :Text;
    isEncrypted @3 :Bool;
    createdAt @4 :Text;  # ISO timestamp
    updatedAt @5 :Text;  # ISO timestamp
    iqpilotVersion @6 :Version;
    backupMetadata @7 :List(MetadataEntry);
  }
}

struct IQCarState @0xb86e6369214c01c8 {
  speedLimit @0 :Float32;
  accelPressed @1 :Bool;
  decelPressed @2 :Bool;
  alcOverrideAlert @3 :Bool;
}

struct IQLiveData @0xf416ec09499d9d19 {
  speedLimitValid @0 :Bool;
  speedLimit @1 :Float32;
  speedLimitAheadValid @2 :Bool;
  speedLimitAhead @3 :Float32;
  speedLimitAheadDistance @4 :Float32;
  roadName @5 :Text;
}

struct IQModelDataV2 @0xa1680744031fdb2d {
  laneTurnDirection @0 :TurnDirection;

  enum TurnDirection {
    none @0;
    turnLeft @1;
    turnRight @2;
  }
}

enum NavDirection {
  none @0;
  left @1;
  right @2;
}

struct IQNavState @0xcb9fd56c7057593a {
  # Navigation state and guidance information
  active @0 :Bool;                          # Whether navigation is currently active
  destinationValid @1 :Bool;                # Whether we have a valid destination

  # Current position and route info
  distanceRemaining @2 :Float32;            # Total distance remaining to destination (m)
  timeRemaining @3 :Float32;                # Estimated time remaining to destination (s)
  currentSegmentIndex @4 :UInt32;           # Index of current route segment
  totalSegments @5 :UInt32;                 # Total number of segments in route

  # Next maneuver information
  nextManeuverValid @6 :Bool;               # Whether next maneuver data is valid
  nextManeuverDistance @7 :Float32;         # Distance to next maneuver (m)
  nextManeuverType @8 :ManeuverType;        # Type of next maneuver
  nextManeuverDirection @9 :IQModelDataV2.TurnDirection;  # Direction for next maneuver
  nextManeuverDescription @10 :Text;        # Human-readable maneuver description
  nextManeuverAngle @21 :Float32;           # Turn angle in degrees (for angle-adaptive enforcement)

  # Turn desire control for lateral planning
  shouldSendTurnDesire @11 :Bool;           # Whether to send turn desires to model
  turnDesireDirection @12 :IQModelDataV2.TurnDirection;   # Direction for turn desire

  # Lane change desire control for highway exits/ramps (>45 mph)
  shouldSendLaneChangeDesire @22 :Bool;     # Whether to send lane change desires for high-speed exits
  laneChangeDesireDirection @23 :IQModelDataV2.TurnDirection;  # Direction for lane change desire

  # Speed guidance for longitudinal planning
  targetSpeed @13 :Float32;                 # Target speed for upcoming maneuver (m/s)
  targetSpeedValid @14 :Bool;               # Whether target speed is valid

  # Destination info
  destinationLatitude @15 :Float64;
  destinationLongitude @16 :Float64;
  destinationName @17 :Text;

  # Lane positioning guidance for exits/turns
  shouldSendLanePositioning @18 :Bool;      # Whether to send lane positioning desires (keepLeft/keepRight)
  lanePositioningDirection @19 :IQModelDataV2.TurnDirection;  # Direction for lane positioning

  # Lane tracking debug info (model vs GPS comparison for testing)
  laneDebugInfo @20 :LaneDebugInfo;

  # Navigation-specific UI event fields (separate from model/desire system)
  navTurnDesireDirection @24 :NavDirection;           # For "Navigation: Turning Left/Right" UI alerts
  navLaneChangeDesireDirection @25 :NavDirection;     # For "Navigation: Initiating Lane Change" UI alerts
  navLanePositioningDirection @26 :NavDirection;      # For future lane positioning UI alerts
  navSpeedTargetActive @27 :Bool;                     # For "Navigation: Reducing Speed" UI alert

  # Second next maneuver information (for "Then" section in navigation banner UI)
  secondNextManeuverValid @28 :Bool;                  # Whether second next maneuver data is valid
  secondNextManeuverType @29 :ManeuverType;           # Type of second next maneuver
  secondNextManeuverDirection @30 :NavDirection;      # Direction for second next maneuver
  secondNextManeuverDistance @31 :Float32;            # Distance to second next maneuver (m)
  nextManeuverModifier @32 :Text;                     # Raw Mapbox modifier for next maneuver (slight_left, sharp_right, etc.)
  secondNextManeuverModifier @33 :Text;               # Raw Mapbox modifier for second next maneuver
  longitudinalProvider @34 :LongitudinalProvider;     # Active source of nav longitudinal influence
  longitudinalState @35 :LongitudinalState;           # Current nav longitudinal state machine output
  longitudinalEngaged @36 :Bool;                      # Whether nav longitudinal influence is currently active
  speedTarget @37 :Float32;                           # Nav longitudinal speed target (m/s)
  accelTarget @38 :Float32;                           # Nav longitudinal accel target (m/s^2)
  valid @39 :Bool;                                    # Whether nav longitudinal target is valid
  maneuverPhase @40 :ManeuverPhase;                   # IQ nav maneuver phase for desire/FSM integration
  maneuverDirection @41 :NavDirection;                # Direction of active IQ nav maneuver phase
  command @42 :Command;                               # Short-lived IQ nav command trigger for desire/FSM integration
  commandDirection @43 :NavDirection;                 # Direction associated with current IQ nav command
  commandIndex @44 :UInt32;                           # Monotonic counter incremented when nav emits a new IQ command
  cameraValid @45 :Bool;                              # Whether a speed camera ahead is currently detected
  cameraType @46 :CameraType;                         # Type of the upcoming speed camera
  cameraDistance @47 :Float32;                        # Distance to the upcoming camera (m)
  cameraSpeedLimit @48 :Float32;                      # Enforced speed limit at the camera (m/s)

  enum CameraType {
    none @0;
    fixedSpeed @1;       # Fixed speed camera
    mobileSpeed @2;      # Mobile/handheld speed camera
    sectionStart @3;     # Average-speed (section) zone start
    sectionEnd @4;       # Average-speed (section) zone end
    averageZone @5;      # Within an average-speed zone
    redLight @6;         # Red-light camera
    bump @7;             # Speed bump
  }

  enum ManeuverType {
    none @0;
    turn @1;              # Regular turn at intersection
    exit @2;              # Highway exit
    merge @3;             # Merge onto highway
    fork @4;              # Road fork
    continueStraight @5;  # Continue straight
    arrive @6;            # Arrive at destination
    roundabout @7;        # Enter/exit roundabout
  }

  enum LongitudinalProvider {
    none @0;
    route @1;
    mapbox @2;
    vision @3;
    offlineOsm @4;
    camera @5;
  }

  enum LongitudinalState {
    disabled @0;
    enabled @1;
    entering @2;
    active @3;
    leaving @4;
    overriding @5;
  }

  enum ManeuverPhase {
    none @0;
    turnPrepare @1;
    turnActive @2;
    highwayPrepare @3;
    highwayCommit @4;
  }

  enum Command {
    none @0;
    laneChange @1;
  }

  struct LaneDebugInfo {
    modelLane @0 :Text;             # "left", "middle", "right", "unknown"
    modelConfidence @1 :Float32;     # 0.0-1.0
    gpsLane @2 :Text;                # "left", "middle", "right", "unknown"
    gpsConfidence @3 :Float32;       # 0.0-1.0
    lateralOffset @4 :Float32;       # Meters from road centerline (negative=left, positive=right)
    gpsAccuracy @5 :Float32;         # GPS position accuracy (meters)
    agreement @6 :Bool;              # Do model and GPS agree?
  }
}

struct IQNavRenderState @0x9f7fd1b65971a4d1 {
  active @0 :Bool;
  currentLatitude @1 :Float64;
  currentLongitude @2 :Float64;
  bearingDeg @3 :Float32;
  routePolyline @4 :List(NavPoint);
  routePolylineSimplified @5 :List(NavPoint);
  nextManeuverLatitude @6 :Float64;
  nextManeuverLongitude @7 :Float64;
  nextManeuverType @8 :IQNavState.ManeuverType;
  nextManeuverDirection @9 :NavDirection;
  nextManeuverDistance @10 :Float32;
  destinationLatitude @11 :Float64;
  destinationLongitude @12 :Float64;
  zoomHint @13 :Float32;

  struct NavPoint {
    latitude @0 :Float64;
    longitude @1 :Float64;
  }
}

struct CustomReserved10 @0xa8e2e4a8c6f4d3b2 {
}

struct CustomReserved11 @0xc2243c65e0340384 {
}

struct CustomReserved12 @0x9ccdc8676701b412 {
}

struct CustomReserved13 @0xcd96dafb67a082d0 {
}

struct CustomReserved14 @0xb057204d7deadf3f {
}

struct CustomReserved15 @0xbd443b539493bc68 {
}

struct CustomReserved16 @0xfc6241ed8877b611 {
}

# Reserved placeholders holding log.capnp Event union ordinals @143/@144/@145, freed when the
# mapd v2 schema below was reverted from merge 353be8b. When re-adding mapd v2 by hand, drop the
# matching placeholders and restore the mapd union members in log.capnp.
struct CustomReserved17 @0x9d835fe3aba193a6 {
}

struct CustomReserved18 @0xc0542788c997fa0c {
}

struct CustomReserved19 @0xd4b4369426f697c3 {
}

# ===== mapd v2 schema — reverted from merge 353be8b (re-add by hand when mapd v2 lands cleanly) =====
# NOTE: struct ids must match the mapd binary exactly when re-enabled.
# struct MapdDownloadLocationDetails @0xff889853e7b0987f {
#   location @0 :Text;
#   totalFiles @1 :UInt32;
#   downloadedFiles @2 :UInt32;
# }
#
# struct MapdDownloadProgress @0xfaa35dcac85073a2 {
#   active @0 :Bool;
#   cancelled @1 :Bool;
#   totalFiles @2 :UInt32;
#   downloadedFiles @3 :UInt32;
#   locations @4 :List(Text);
#   locationDetails @5 :List(MapdDownloadLocationDetails);
# }
#
# struct MapdPathPoint @0xd6f78acca1bc3939 {
#   latitude @0 :Float64;
#   longitude @1 :Float64;
#   curvature @2 :Float32;
#   targetVelocity @3 :Float32;
# }
#
# enum MapdRoadContext {
#   freeway @0;
#   city @1;
#   unknown @2;
# }
#
# enum MapdWaySelectionType {
#   current @0;
#   predicted @1;
#   possible @2;
#   extended @3;
#   fail @4;
# }
#
# enum MapdInputType {
#   download @0;
#   setTargetLateralAccel @1;
#   setSpeedLimitOffset @2;
#   setSpeedLimitControl @3;
#   setMapCurveSpeedControl @4;
#   setVisionCurveSpeedControl @5;
#   setLogLevel @6;
#   setVisionCurveTargetLatA @7;
#   setVisionCurveMinTargetV @8;
#   reloadSettings @9;
#   saveSettings @10;
#   setEnableSpeed @11;
#   setVisionCurveUseEnableSpeed @12;
#   setMapCurveUseEnableSpeed @13;
#   setSpeedLimitUseEnableSpeed @14;
#   setHoldLastSeenSpeedLimit @15;
#   setTargetSpeedJerk @16;
#   setTargetSpeedAccel @17;
#   setTargetSpeedTimeOffset @18;
#   setDefaultLaneWidth @19;
#   setMapCurveTargetLatA @20;
#   loadDefaultSettings @21;
#   loadRecommendedSettings @22;
#   setSlowDownForNextSpeedLimit @23;
#   setSpeedUpForNextSpeedLimit @24;
#   setHoldSpeedLimitWhileChangingSetSpeed @25;
#   loadPersistentSettings @26;
#   cancelDownload @27;
#   setLogJson @28;
#   setLogSource @29;
#   setExternalSpeedLimitControl @30;
#   setExternalSpeedLimit @31;
#   setSpeedLimitPriority @32;
#   setSpeedLimitChangeRequiresAccept @33;
#   acceptSpeedLimit @34;
#   setPressGasToAcceptSpeedLimit @35;
#   setAdjustSetSpeedToAcceptSpeedLimit @36;
#   setAcceptSpeedLimitTimeout @37;
#   setPressGasToOverrideSpeedLimit @38;
# }
#
# struct MapdExtendedOut @0xa30662f84033036c {
#   downloadProgress @0 :MapdDownloadProgress;
#   settings @1 :Text;
#   path @2 :List(MapdPathPoint);
# }
#
# struct MapdIn @0xc86a3d38d13eb3ef {
#   type @0 :MapdInputType;
#   float @1 :Float32;
#   str @2 :Text;
#   bool @3 :Bool;
# }
#
# struct MapdOut @0xa4f1eb3323f5f582 {
#   wayName @0 :Text;
#   wayRef @1 :Text;
#   roadName @2 :Text;
#   speedLimit @3 :Float32;
#   nextSpeedLimit @4 :Float32;
#   nextSpeedLimitDistance @5 :Float32;
#   hazard @6 :Text;
#   nextHazard @7 :Text;
#   nextHazardDistance @8 :Float32;
#   advisorySpeed @9 :Float32;
#   nextAdvisorySpeed @10 :Float32;
#   nextAdvisorySpeedDistance @11 :Float32;
#   oneWay @12 :Bool;
#   lanes @13 :UInt8;
#   tileLoaded @14 :Bool;
#   speedLimitSuggestedSpeed @15 :Float32;
#   suggestedSpeed @16 :Float32;
#   estimatedRoadWidth @17 :Float32;
#   roadContext @18 :MapdRoadContext;
#   distanceFromWayCenter @19 :Float32;
#   visionCurveSpeed @20 :Float32;
#   mapCurveSpeed @21 :Float32;
#   waySelectionType @22 :MapdWaySelectionType;
#   speedLimitAccepted @23 :Bool;
# }
