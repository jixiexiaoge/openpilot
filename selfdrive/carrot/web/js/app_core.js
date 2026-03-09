const DEBUG_UI = false;

let SETTINGS = null;
let CURRENT_GROUP = null;
let LANG = "ko"; // "ko" | "en" | "zh"

const UI_STRINGS = {
  ko: {
    home: "홈",
    setting: "설정",
    tools: "도구",
    fleet: "플릿",
    lang: "언어",
    server_state: "서버 상태",
    quick_link: "퀵 링크",
    car_select: "차량 선택",
    makers: "제조사",
    models: "모델",
    groups: "그룹",
    items: "항목",
    back: "뒤로",
    change: "변경",
    git_commands: "Git 명령",
    user_system: "사용자 / 시스템",
    reboot: "재부팅",
    backup: "백업",
    restore: "복구",
    apply: "적용",
    confirm_car: "이 차량을 선택하시겠습니까?",
    confirm_reboot: "지금 재부팅하시겠습니까?",
    reboot_later: "선택되었습니다. 적용하려면 나중에 재부팅하세요.",
    rebooting: "재부팅 중...",
    git_sync_confirm: "Git sync를 실행하시겠습니까?",
    git_reset_confirm: "Git reset을 실행하시겠습니까? (위험)",
    delete_videos_confirm: "모든 비디오를 삭제하시겠습니까? (위험)",
    delete_logs_confirm: "모든 로그를 삭제하시겠습니까? (위험)",
    select_backup_file: "먼저 백업 json 파일을 선택하세요.",
    restore_confirm: "파일에서 설정을 복구하시겠습니까?\n\n많은 Params 값이 덮어씌워집니다.",
    restore_done_reboot: "복구가 완료되었습니다.\n지금 재부팅하시겠습니까?",
    checkout_confirm: "브랜치를 체크아웃하시겠습니까?",
    branch_changed: "브랜치가 변경되었습니다.",
    quick_link_hint: "* 길게 눌러 링크저장",
    git_hint: "* reset/branch는 위험할 수 있으니 confirm 뜹니다.",
    sys_hint: "* delete/reboot는 confirm 후 실행합니다.",
    restore_hint: "* restore 후 reboot 권장",
    failed_set_car: "차량 선택 저장 실패: ",
    reboot_failed: "재부팅 실패: ",
    set_failed: "설정 실패: ",
    branch_dom_missing: "브랜치 DOM 요소를 찾을 수 없습니다.",
    fullscreen_not_supported: "이 브라우저는 전체화면을 지원하지 않습니다.",
    record: "녹화",
    record_on: "녹화중",
    record_off: "녹화대기",
  },
  en: {
    home: "Home",
    setting: "Setting",
    tools: "Tools",
    fleet: "Fleet",
    lang: "Lang",
    server_state: "Server State",
    quick_link: "Quick Link",
    car_select: "Car Select",
    makers: "Makers",
    models: "Models",
    groups: "Groups",
    items: "Items",
    back: "Back",
    change: "Change",
    git_commands: "Git Commands",
    user_system: "User / System",
    reboot: "Reboot",
    backup: "Backup",
    restore: "Restore",
    apply: "Apply",
    confirm_car: "Select this car?",
    confirm_reboot: "Reboot now?",
    reboot_later: "Selected. Reboot later to apply.",
    rebooting: "Rebooting...",
    git_sync_confirm: "Run git sync?",
    git_reset_confirm: "Run git reset? (DANGEROUS)",
    delete_videos_confirm: "Delete ALL videos? (DANGEROUS)",
    delete_logs_confirm: "Delete ALL logs? (DANGEROUS)",
    select_backup_file: "Select a backup json file first.",
    restore_confirm: "Restore settings from file?\n\nThis will overwrite many Params values.",
    restore_done_reboot: "Restore done.\nReboot now?",
    checkout_confirm: "Checkout branch?",
    branch_changed: "Branch changed.",
    quick_link_hint: "* Long press to save link",
    git_hint: "* Reset/branch will prompt for confirmation.",
    sys_hint: "* Delete/reboot will prompt for confirmation.",
    restore_hint: "* Reboot recommended after restore.",
    failed_set_car: "Failed to set car: ",
    reboot_failed: "Reboot failed: ",
    set_failed: "Set failed: ",
    branch_dom_missing: "Branch DOM elements missing.",
    fullscreen_not_supported: "Fullscreen not supported on this browser.",
    record: "Record",
    record_on: "Recording",
    record_off: "Idle",
  },
  zh: {
    home: "首页",
    setting: "设置",
    tools: "工具",
    fleet: "车队",
    lang: "语言",
    server_state: "服务器状态",
    quick_link: "快速链接",
    car_select: "车辆选择",
    makers: "制造商",
    models: "车型",
    groups: "分组",
    items: "项",
    back: "返回",
    change: "修改",
    git_commands: "Git 命令",
    user_system: "用户 / 系统",
    reboot: "重启",
    backup: "备份",
    restore: "还原",
    apply: "应用",
    confirm_car: "选择此车辆吗？",
    confirm_reboot: "现在重启吗？",
    reboot_later: "已选择。请稍后重启以应用更改。",
    rebooting: "正在重启...",
    git_sync_confirm: "执行 Git 同步吗？",
    git_reset_confirm: "执行 Git 重置吗？（危险）",
    delete_videos_confirm: "删除所有视频吗？（危险）",
    delete_logs_confirm: "删除所有日志吗？（危险）",
    select_backup_file: "请先选择一个备份 JSON 文件。",
    restore_confirm: "从文件还原设置吗？\n\n这将覆盖许多参数值。",
    restore_done_reboot: "还原完成。\n现在重启吗？",
    checkout_confirm: "切换分支吗？",
    branch_changed: "分支已切换。",
    quick_link_hint: "* 长按保存链接",
    git_hint: "* 重置/分支操作会弹出确认提示。",
    sys_hint: "* 删除/重启操作会弹出确认提示。",
    restore_hint: "* 还原后建议重启。",
    failed_set_car: "保存车辆选择失败: ",
    reboot_failed: "重启失败: ",
    set_failed: "设置失败: ",
    branch_dom_missing: "找不到分支 DOM 元素。",
    fullscreen_not_supported: "此浏览器不支持全屏。",
    record: "录制",
    record_on: "录制中",
    record_off: "待机",
  }
};

const DRIVE_MODES = {
  ko: { normal: "일반", eco: "연비", safe: "안전", sport: "고속" },
  en: { normal: "Normal", eco: "Eco", safe: "Safe", sport: "Sport" },
  zh: { normal: "标准", eco: "经济", safe: "安全", sport: "运动" }
};

let UNIT_CYCLE = [1, 2, 5, 10, 50, 100];
const UNIT_INDEX = {}; // per name

// Car select data
let CARS = null;                 // { makers: {Hyundai:[...], Genesis:[...]} }
let CURRENT_MAKER = null;

const btnHome = document.getElementById("btnHome");
const btnSetting = document.getElementById("btnSetting");
const btnFleet = document.getElementById("btnFleet");
const btnLang = document.getElementById("btnLang");
const langLabel = document.getElementById("langLabel");
const btnTools = document.getElementById("btnTools");
const btnToolsBack = document.getElementById("btnToolsBack");
const btnRecordToggle = document.getElementById("btnRecordToggle");

btnTools.onclick = () => showPage("tools");
btnToolsBack.onclick = () => showPage("home");

const btnChangeCar = document.getElementById("btnChangeCar");
const curCarLabelCar = document.getElementById("curCarLabelCar");
const curCarLabelSetting = document.getElementById("curCarLabelSetting");

// Setting screens
const settingTitle = document.getElementById("settingTitle");
const btnBackGroups = document.getElementById("btnBackGroups");
const screenGroups = document.getElementById("settingScreenGroups");
const screenItems = document.getElementById("settingScreenItems");
const itemsTitle = document.getElementById("itemsTitle");

// Car screens
const carTitle = document.getElementById("carTitle");
const btnBackCar = document.getElementById("btnBackCar");
const carMeta = document.getElementById("carMeta");
const carScreenMakers = document.getElementById("carScreenMakers");
const carScreenModels = document.getElementById("carScreenModels");
const makerList = document.getElementById("makerList");
const modelList = document.getElementById("modelList");
const modelTitle = document.getElementById("modelTitle");
const modelMeta = document.getElementById("modelMeta");

btnHome.onclick = () => showPage("home", true);
btnRecordToggle.onclick = () => toggleRecord();
btnSetting.onclick = () => showPage("setting", true);

btnFleet.onclick = () => {
  const ip = location.hostname;
  const url = `http://${ip}:8082/`;
  window.open(url, "_blank", "noopener");
};

btnLang.onclick = () => toggleLang();

btnChangeCar.onclick = () => showPage("car", true);
btnBackCar.onclick = () => history.back();
carTitle.onclick = () => history.back();
modelTitle.onclick = () => showCarScreen("makers"); // ��ȭ�鿡�� Ÿ��Ʋ ���� makers��

// Branch select
let BRANCHES = [];
const branchTitle = document.getElementById("branchTitle");
const btnBackBranch = document.getElementById("btnBackBranch");
const branchMeta = document.getElementById("branchMeta");
const branchList = document.getElementById("branchList");

// Quick Link
const quickLink = document.getElementById("quickLink");

btnBackBranch.onclick = () => history.back();
branchTitle.onclick = () => history.back();

function showPage(page, pushHistory = false) {
  document.getElementById("pageHome").style.display = (page === "home") ? "" : "none";
  document.getElementById("pageSetting").style.display = (page === "setting") ? "" : "none";
  document.getElementById("pageCar").style.display = (page === "car") ? "" : "none";
  document.getElementById("pageTools").style.display = (page === "tools") ? "" : "none";
  document.getElementById("pageBranch").style.display = (page === "branch") ? "" : "none";

  btnHome.classList.toggle("active", page === "home");
  btnSetting.classList.toggle("active", page === "setting");

  if (page === "home") {
    loadCurrentCar().catch(() => {});
    loadRecordState().catch(() => {});
    updateQuickLink().catch(() => {});
  }

  if (page === "setting") {
    showSettingScreen("groups", false);
    if (!SETTINGS) loadSettings();
  }

  if (page === "car") {
    showCarScreen("makers", false);
    if (!CARS) loadCars();
  }
  if (page === "tools") {
    initToolsPage();
  }

  const state =
    (page === "home") ? { page: "home" } :
    (page === "setting") ? { page: "setting", screen: "groups", group: null } :
    (page === "car") ? { page: "car", screen: "makers", maker: null } :
    (page === "tools") ? { page: "tools" } :
    (page === "branch") ? { page: "branch" } :
    { page: "home" };

  if (pushHistory) history.pushState(state, "");
  else history.replaceState(state, "");
}

/* ---------- screen transitions (Setting) ---------- */
function showSettingScreen(which, pushHistory = false) {
  const isGroups = (which === "groups");
  const showEl = isGroups ? screenGroups : screenItems;
  const hideEl = isGroups ? screenItems : screenGroups;

  btnBackGroups.style.display = isGroups ? "none" : "";
  settingTitle.textContent = isGroups ? "Setting" : ("Setting - " + (CURRENT_GROUP || ""));

  showEl.style.display = "";
  requestAnimationFrame(() => showEl.classList.remove("hidden"));

  hideEl.classList.add("hidden");
  setTimeout(() => { hideEl.style.display = "none"; }, 170);

  if (pushHistory) {
    history.pushState({ page: "setting", screen: which, group: CURRENT_GROUP || null }, "");
  }
}

btnBackGroups.onclick = () => history.back();
settingTitle.onclick = () => history.back();
itemsTitle.onclick = () => history.back();

/* ---------- screen transitions (Car) ---------- */
function showCarScreen(which, pushHistory = false) {
  const isMakers = (which === "makers");
  const showEl = isMakers ? carScreenMakers : carScreenModels;
  const hideEl = isMakers ? carScreenModels : carScreenMakers;

  showEl.style.display = "";
  requestAnimationFrame(() => showEl.classList.remove("hidden"));

  hideEl.classList.add("hidden");
  setTimeout(() => { hideEl.style.display = "none"; }, 170);

  if (pushHistory) {
    history.pushState({ page: "car", screen: which, maker: CURRENT_MAKER || null }, "");
  }
}

function toggleLang() {
  if (LANG === "ko") LANG = "en";
  else if (LANG === "en") LANG = "zh";
  else LANG = "ko";

  langLabel.textContent = LANG.toUpperCase();

  // Update static UI text
  renderUIText();
  loadRecordState().catch(() => {});

  if (SETTINGS) {
    renderGroups();
    if (CURRENT_GROUP) renderItems(CURRENT_GROUP);
  }
}

function renderUIText() {
  const s = UI_STRINGS[LANG];
  if (!s) return;

  setText("btnHome", s.home);
  setText("btnSetting", s.setting);
  setText("btnTools", s.tools);
  setText("btnFleet", s.fleet);
  // langLabel is handled in toggleLang

  // Home
  setText("homeTitle", s.home);
  setText("btnRecordToggle", s.record);
  setText("serverStateTitle", s.server_state);
  setText("quickLinkTitle", s.quick_link);

  // Car Select
  setText("carTitle", s.car_select);
  setText("btnBackCar", s.back);
  setText("makersTitle", s.makers);
  setText("modelTitle", s.models);

  // Setting
  setText("settingTitleText", s.setting); // Use a specific ID if needed
  setText("btnBackGroups", s.back);
  setText("btnChangeCar", s.change);
  setText("groupsTitle", s.groups);
  setText("itemsTitle", s.items);

  // Tools
  setText("toolsTitle", s.tools);
  setText("btnToolsBack", s.back);
  setText("gitCommandsTitle", s.git_commands);
  setText("userSystemTitle", s.user_system);
  setText("btnReboot", s.reboot);
  setText("btnBackupSettings", s.backup);
  setText("btnRestoreSettings", s.restore);

  setText("quickLinkHint", s.quick_link_hint);
  setText("gitHint", s.git_hint);
  setText("sysHint", s.sys_hint);
  setText("restoreHint", s.restore_hint);
}

function setText(id, txt) {
  const el = document.getElementById(id);
  if (el) el.textContent = txt;
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatItemText(p, keyKo, keyEn, fallback = "") {
  if (LANG === "zh") return (p["c" + keyEn.slice(1)] || p[keyEn] || p[keyKo] || fallback);
  if (LANG === "ko") return (p[keyKo] ?? fallback);
  return (p[keyEn] ?? p[keyKo] ?? fallback);
}

function clamp(v, mn, mx) {
  if (Number.isFinite(mn) && v < mn) return mn;
  if (Number.isFinite(mx) && v > mx) return mx;
  return v;
}

/* ---------- Params helpers ---------- */
async function bulkGet(names) {
  const q = encodeURIComponent(names.join(","));
  const r = await fetch("/api/params_bulk?names=" + q);
  const j = await r.json();
  if (!j.ok) throw new Error(j.error || "bulk failed");
  return j.values || {};
}

async function setParam(name, value) {
  const r = await fetch("/api/param_set", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, value })
  });
  const j = await r.json();
  if (!j.ok) throw new Error(j.error || "set failed");
  return true;
}
