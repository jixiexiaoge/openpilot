/* ---------- Home: current car ---------- */
async function loadCurrentCar() {
  try {
    const values = await bulkGet(["CarSelected3"]);
    const v = values["CarSelected3"];
    curCarLabelCar.textContent = (v && String(v).trim().length) ? String(v) : "-";
    curCarLabelSetting.textContent = (v && String(v).trim().length) ? String(v) : "-";
  } catch (e) {
    curCarLabelCar.textContent = "-";
    curCarLabelSetting.textContent = "-";
  }
}

async function loadRecordState() {
  try {
    const values = await bulkGet(["ScreenRecord"]);
    const v = values["ScreenRecord"];

    const isOn =
      v === true ||
      v === 1 ||
      v === "1" ||
      v === "true" ||
      v === "True";

    btnRecordToggle.classList.toggle("active", isOn);
    btnRecordToggle.textContent = isOn
      ? `${UI_STRINGS[LANG].record} ON`
      : `${UI_STRINGS[LANG].record} OFF`;
  } catch (e) {
    btnRecordToggle.classList.remove("active");
    btnRecordToggle.textContent = UI_STRINGS[LANG].record || "Record";
  }
}
async function toggleRecord() {
  try {
    const values = await bulkGet(["ScreenRecord"]);
    const v = values["ScreenRecord"];

    const isOn =
      v === true ||
      v === 1 ||
      v === "1" ||
      v === "true" ||
      v === "True";

    await setParam("ScreenRecord", !isOn);
    await loadRecordState();
  } catch (e) {
    alert((UI_STRINGS[LANG].record || "Failed to toggle record: ") + e.message);
  }
}

/* ---------- Cars: load list + maker/model UI ---------- */
async function loadCars() {
  carMeta.textContent = "loading...";
  makerList.innerHTML = "";
  modelList.innerHTML = "";
  CURRENT_MAKER = null;
  showCarScreen("makers", false);

  const r = await fetch("/api/cars");
  const j = await r.json();
  if (!j.ok) {
    carMeta.textContent = "Failed: " + (j.error || "unknown");
    return;
  }
  CARS = j; // { ok:true, sources:[...], makers:{Hyundai:[...],Genesis:[...]} ... }

  const sources = (j.sources || []).join(", ");
  carMeta.textContent = sources ? ("sources: " + sources) : "ok";

  renderMakers();
}

function renderMakers() {
  makerList.innerHTML = "";
  const makers = CARS && CARS.makers ? Object.keys(CARS.makers) : [];
  makers.sort((a, b) => a.localeCompare(b));

  for (const mk of makers) {
    const arr = CARS.makers[mk] || [];
    const b = document.createElement("button");
    b.className = "btn groupBtn";
    b.textContent = `${mk} (${arr.length})`;
    b.onclick = () => {
      CURRENT_MAKER = mk;
      renderModels(mk);
      showCarScreen("models", true);
    };
    makerList.appendChild(b);
  }
}

function renderModels(maker) {
  modelList.innerHTML = "";
  const arr = (CARS.makers && CARS.makers[maker]) ? CARS.makers[maker] : [];
  modelTitle.textContent = maker;
  modelMeta.textContent = `${arr.length} models`;

  // �� ����̴ϱ� ��ư ��/�� ���ϰ�: groupBtn ����
  for (const fullLine of arr) {
    // fullLine ��: "Hyundai Grandeur 2018-19"
    // CarSelected3���� maker�� ���� �־�� �� �� "Grandeur 2018-19"
    const modelOnly = stripMaker(fullLine, maker);

    const b = document.createElement("button");
    b.className = "btn groupBtn";
    b.textContent = modelOnly;
    b.onclick = () => onSelectCar(maker, modelOnly, fullLine);
    modelList.appendChild(b);
  }
}

function stripMaker(fullLine, maker) {
  // maker + ������ 1���� ����
  const prefix = maker + " ";
  if (fullLine.startsWith(prefix)) return fullLine.slice(prefix.length).trim();
  // Ȥ�� "Hyundai"�� �ƴ� �ٸ� ǥ��� fallback: ù �ܾ� ����
  const sp = fullLine.split(" ");
  if (sp.length >= 2) return sp.slice(1).join(" ").trim();
  return fullLine.trim();
}

async function onSelectCar(maker, modelOnly, fullLine) {
  const msg = (UI_STRINGS[LANG].confirm_car || "Select this car?") + `\n\n${maker} ${modelOnly}\n\nThis will set CarSelected3 = "${modelOnly}".`;
  if (!confirm(msg)) return;

  try {
    await setParam("CarSelected3", fullLine);
  } catch (e) {
    alert((UI_STRINGS[LANG].failed_set_car || "Failed to set car: ") + e.message);
    return;
  }

  // Home ǥ�� ������Ʈ
  curCarLabelCar.textContent = modelOnly;
  curCarLabelSetting.textContent = modelOnly;

  const rb = confirm(UI_STRINGS[LANG].confirm_reboot || "Reboot now?");
  if (!rb) {
    alert(UI_STRINGS[LANG].reboot_later || "Selected. Reboot later to apply.");
    return;
  }

  try {
    const r = await fetch("/api/reboot", { method: "POST" });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || "reboot failed");
    alert(UI_STRINGS[LANG].rebooting || "Rebooting...");
  } catch (e) {
    alert((UI_STRINGS[LANG].reboot_failed || "Reboot failed: ") + e.message);
  }
}

/* ---------- Settings ---------- */
async function loadSettings() {
  const meta = document.getElementById("settingsMeta");
  meta.textContent = "loading...";

  const r = await fetch("/api/settings");
  const j = await r.json();
  if (!j.ok) {
    meta.textContent = "Failed: " + (j.error || "unknown");
    return;
  }

  SETTINGS = j;
  UNIT_CYCLE = j.unit_cycle || UNIT_CYCLE;

  meta.textContent = `path: ${j.path} | has_params: ${j.has_params} | type_api: ${j.has_param_type}`;

  if (!DEBUG_UI) {
    meta.style.display = "none";
    const gm = document.getElementById("groupMeta");
    if (gm) gm.style.display = "none";
    const cm = document.getElementById("carMeta");
    if (cm) cm.style.display = "none";
  }

  renderGroups();
  CURRENT_GROUP = null;
  showSettingScreen("groups", false);
}

function renderGroups() {
  const box = document.getElementById("groupList");
  box.innerHTML = "";

  (SETTINGS.groups || []).forEach(g => {
    let label = g.group;
    if (LANG === "zh") label = g.cgroup || g.egroup || g.group;
    else if (LANG === "en") label = g.egroup || g.group;

    const b = document.createElement("button");
    b.className = "btn groupBtn";
    b.textContent = `${label} (${g.count})`;
    b.onclick = () => selectGroup(g.group);
    box.appendChild(b);
  });
}

function selectGroup(group) {
  CURRENT_GROUP = group;
  showSettingScreen("items", true);
  renderItems(group);
}

async function renderItems(group) {
  const meta = document.getElementById("groupMeta");
  const itemsBox = document.getElementById("items");
  itemsBox.innerHTML = "";

  const list = SETTINGS.items_by_group[group] || [];
  if (meta) meta.textContent = `${group} / ${list.length}`;
  settingTitle.textContent = "Setting - " + group;

  const names = list.map(p => p.name);
  let values = {};
  try {
    values = await bulkGet(names);
  } catch (e) {
    values = {};
  }

  for (const p of list) {
    const name = p.name;
    if (!(name in UNIT_INDEX)) UNIT_INDEX[name] = 0;

    const title = formatItemText(p, "title", "etitle", "");
    const descr = formatItemText(p, "descr", "edescr", "");

    const el = document.createElement("div");
    el.className = "setting";

    const top = document.createElement("div");
    top.className = "settingTop";

    const left = document.createElement("div");
    left.innerHTML = `
      <div class="title">${escapeHtml(title)}</div>
      <div class="name">${escapeHtml(name)}</div>
      <div class="muted" style="margin-top:6px;">
        min=${p.min}, max=${p.max}, default=${p.default}
      </div>
    `;

    const ctrl = document.createElement("div");
    ctrl.className = "ctrl";

    const btnMinus = document.createElement("button");
    btnMinus.className = "smallBtn";
    btnMinus.textContent = "-";

    const val = document.createElement("div");
    val.className = "pill val";

    const btnPlus = document.createElement("button");
    btnPlus.className = "smallBtn";
    btnPlus.textContent = "+";

    const unitBtn = document.createElement("button");
    unitBtn.className = "smallBtn";
    unitBtn.textContent = "unit: " + UNIT_CYCLE[UNIT_INDEX[name]];

    unitBtn.onclick = () => {
      UNIT_INDEX[name] = (UNIT_INDEX[name] + 1) % UNIT_CYCLE.length;
      unitBtn.textContent = "unit: " + UNIT_CYCLE[UNIT_INDEX[name]];
    };

    ctrl.appendChild(btnMinus);
    ctrl.appendChild(val);
    ctrl.appendChild(btnPlus);
    ctrl.appendChild(unitBtn);

    top.appendChild(left);
    top.appendChild(ctrl);

    const d = document.createElement("div");
    d.className = "descr";
    d.textContent = descr;

    el.appendChild(top);
    el.appendChild(d);
    itemsBox.appendChild(el);

    // initial value
    const cur = (name in values) ? values[name] : p.default;
    val.textContent = String(cur);

    async function applyDelta(sign) {
      const step = UNIT_CYCLE[UNIT_INDEX[name]];
      let curv = Number(val.textContent);
      if (Number.isNaN(curv)) curv = Number(p.default);

      let next = curv + sign * step;
      next = clamp(next, Number(p.min), Number(p.max));

      if (Number.isInteger(p.min) && Number.isInteger(p.max) && Number.isInteger(step)) {
        next = Math.round(next);
      }

      try {
        await setParam(name, next);
        val.textContent = String(next);
      } catch (e) {
        alert((UI_STRINGS[LANG].set_failed || "set failed: ") + e.message);
      }
    }

    btnMinus.onclick = () => applyDelta(-1);
    btnPlus.onclick = () => applyDelta(+1);
  }
}


/* ---------- Back key / history ---------- */
history.replaceState({ page: "home" }, "");

window.addEventListener("popstate", async (ev) => {
  const st = ev.state || { page: "home" };

  if (st.page === "home") {
    CURRENT_GROUP = null;
    CURRENT_MAKER = null;
    showPage("home", false);
    return;
  }

  if (st.page === "setting") {
    showPage("setting", false);
    const screen = st.screen || "groups";
    CURRENT_GROUP = st.group || null;

    if (screen === "items" && CURRENT_GROUP) {
      showSettingScreen("items", false);
      renderItems(CURRENT_GROUP);
    } else {
      showSettingScreen("groups", false);
    }
    return;
  }

  if (st.page === "car") {
    showPage("car", false);
    if (!CARS) await loadCars();

    const screen = st.screen || "makers";
    CURRENT_MAKER = st.maker || null;

    if (screen === "models" && CURRENT_MAKER) {
      renderModels(CURRENT_MAKER);
      showCarScreen("models", false);
    } else {
      showCarScreen("makers", false);
    }
    return;
  }

  if (st.page == "tools") {
    showPage("tools", false);
    return;
  }

  if (st.page === "branch") {
    showPage("branch", false);
    // �귣ġ ����� ������ �ٽ� �ε�
    if (!BRANCHES || !BRANCHES.length) {
      loadBranchesAndShow().catch(() => {});
    }
    return;
  }

});


function toolsOutSet(s) {
  const out = document.getElementById("toolsOut");
  if (out) out.textContent = String(s);
}

function toolsMetaSet(s) {
  const meta = document.getElementById("toolsMeta");
  if (meta) meta.textContent = String(s);
}

async function postJson(url, bodyObj) {
  const r = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(bodyObj || {})
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || !j.ok) throw new Error(j.error || ("HTTP " + r.status));
  return j;
}

async function runTool(action, payload) {
  toolsMetaSet("running: " + action);
  toolsOutSet("...");

  // �������� { ok:true, out:"...", rc:0 } �̷� ���·� �ָ� ���� ����
  const j = await postJson("/api/tools", { action, ...(payload || {}) });

  toolsMetaSet("done: " + action);
  if (j.out != null) {
    toolsOutSet(j.out);
  } else {
    toolsOutSet(JSON.stringify(j, null, 2));
  }

  return j;
}

function confirmText(msg, placeholder = "") {
  const v = prompt(msg, placeholder);
  if (v === null) return null;
  return String(v).trim();
}


function initToolsPage() {
  // ��ư ���ε� (�� ����)
  const bindOnce = (id, fn) => {
    const el = document.getElementById(id);
    if (!el || el.dataset.bound === "1") return;
    el.dataset.bound = "1";
    el.onclick = fn;
  };

  toolsMetaSet("ready");

  bindOnce("btnGitPull", async () => {
    try {
      await runTool("git_pull");
    } catch (e) {
      toolsMetaSet("error");
      toolsOutSet("git pull failed: " + e.message);
      alert(e.message);
    }
  });

  bindOnce("btnGitSync", async () => {
    if (!confirm(UI_STRINGS[LANG].git_sync_confirm || "Run git sync?")) return;
    try {
      await runTool("git_sync");
    } catch (e) {
      toolsMetaSet("error");
      toolsOutSet("git sync failed: " + e.message);
      alert(e.message);
    }
  });

  bindOnce("btnGitReset", async () => {
    if (!confirm(UI_STRINGS[LANG].git_reset_confirm || "Run git reset? (DANGEROUS)")) return;

    // �ɼ� �ʿ��ϸ� prompt�� �ޱ�
    // ��: hard / soft, target
    const mode = confirmText("reset mode? (hard/soft/mixed)", "hard");
    if (!mode) return;

    const target = confirmText("reset target? (e.g. HEAD~1 or origin/master)", "HEAD");
    if (!target) return;

    try {
      await runTool("git_reset", { mode, target });
    } catch (e) {
      toolsMetaSet("error");
      toolsOutSet("git reset failed: " + e.message);
      alert(e.message);
    }
  });
  bindOnce("btnGitBranch", async () => {
    await loadBranchesAndShow();
  });


  bindOnce("btnSendTmuxLog", async () => {
    try {
      const j = await runTool("send_tmux_log");

      if (j.file) {
        window.location.href = j.file;
      }
    } catch (e) {
      toolsMetaSet("error");
      toolsOutSet("send tmux log failed: " + e.message);
      alert(e.message);
    }
  });

  bindOnce("btnDeleteVideos", async () => {
    if (!confirm(UI_STRINGS[LANG].delete_videos_confirm || "Delete ALL videos? (DANGEROUS)")) return;
    try {
      await runTool("delete_all_videos");
    } catch (e) {
      toolsMetaSet("error");
      toolsOutSet("delete videos failed: " + e.message);
      alert(e.message);
    }
  });

  bindOnce("btnDeleteLogs", async () => {
    if (!confirm(UI_STRINGS[LANG].delete_logs_confirm || "Delete ALL logs? (DANGEROUS)")) return;
    try {
      await runTool("delete_all_logs");
    } catch (e) {
      toolsMetaSet("error");
      toolsOutSet("delete logs failed: " + e.message);
      alert(e.message);
    }
  });

  bindOnce("btnRebuildAll", async () => {
    if (!confirm("Rebuild all?\n\ncd /data/openpilot\nscons -c\nrm -rf prebuilt\nsudo reboot")) return;
    try {
      await runTool("rebuild_all");
    } catch (e) {
      toolsMetaSet("error");
      toolsOutSet("rebuild_all failed: " + e.message);
      alert(e.message);
    }
  });

  bindOnce("btnBackupSettings", async () => {
    try {
      const j = await runTool("backup_settings");
      if (j.file) window.location.href = j.file; //  �ٿ�ε�
    } catch (e) {
      toolsMetaSet("error");
      toolsOutSet("backup failed: " + e.message);
      alert(e.message);
    }
  });

  bindOnce("btnRestoreSettings", async () => {
    const inp = document.getElementById("restoreFile");
    if (!inp || !inp.files || !inp.files[0]) {
      alert(UI_STRINGS[LANG].select_backup_file || "Select a backup json file first.");
      return;
    }

    if (!confirm(UI_STRINGS[LANG].restore_confirm || "Restore settings from file?\n\nThis will overwrite many Params values.")) return;

    try {
      toolsMetaSet("uploading...");
      toolsOutSet("...");

      const fd = new FormData();
      fd.append("file", inp.files[0]);

      const r = await fetch("/api/params_restore", { method: "POST", body: fd });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || !j.ok) throw new Error(j.error || ("HTTP " + r.status));

      toolsMetaSet("restore done");
      toolsOutSet(JSON.stringify(j.result, null, 2));

      if (confirm(UI_STRINGS[LANG].restore_done_reboot || "Restore done.\nReboot now?")) {
        await runTool("reboot");
        toolsMetaSet("rebooting...");
        toolsOutSet("reboot requested");
      }
    } catch (e) {
      toolsMetaSet("error");
      toolsOutSet("restore failed: " + e.message);
      alert(e.message);
    }
  });

  bindOnce("btnReboot", async () => {
    if (!confirm(UI_STRINGS[LANG].confirm_reboot || "Reboot now?")) return;
    try {
      // �װ� �̹� ���� /api/reboot�� �� �Ÿ� �̰ɷ� �ٲ㵵 ��:
      // await postJson("/api/reboot", {});
      await runTool("reboot");
      toolsMetaSet("rebooting...");
      toolsOutSet("reboot requested");
    } catch (e) {
      toolsMetaSet("error");
      toolsOutSet("reboot failed: " + e.message);
      alert(e.message);
    }
  });

  bindOnce("btnSysCmdRun", async () => {
    const inp = document.getElementById("sysCmdInput");
    const cmd = (inp?.value || "").trim();
    if (!cmd) return;

    toolsOutSet("running: " + cmd + "\n");

    try {
      const j = await runTool("shell_cmd", { cmd });
      // j.out�� stdout/stderr ��ģ ���
      toolsOutSet(j.out || "(no output)");
    } catch (e) {
      toolsOutSet("error: " + e.message);
      alert(e.message);
    }
  });
}

async function loadBranchesAndShow() {
  showPage("branch", true);
  if (!branchMeta || !branchList) {
    alert(UI_STRINGS[LANG].branch_dom_missing || "Branch DOM missing");
    return;
  }
  branchMeta.textContent = "loading...";
  branchList.innerHTML = "";
  BRANCHES = [];

  try {
    const j = await runTool("git_branch_list");
    BRANCHES = j.branches || [];
    branchMeta.textContent = `${BRANCHES.length} branches`;

    renderBranchList();
  } catch (e) {
    branchMeta.textContent = "Failed: " + e.message;
  }
}

function renderBranchList() {
  branchList.innerHTML = "";

  for (const br of BRANCHES) {
    const b = document.createElement("button");
    b.className = "btn groupBtn";
    b.textContent = br;
    b.onclick = () => onSelectBranch(br);
    branchList.appendChild(b);
  }
}

async function onSelectBranch(branch) {
  if (!confirm((UI_STRINGS[LANG].checkout_confirm || "Checkout branch?") + `\n\n${branch}\n\nContinue?`)) return;

  try {
    await runTool("git_checkout", { branch });
    alert(UI_STRINGS[LANG].branch_changed || "Branch changed.");
  } catch (e) {
    alert((UI_STRINGS[LANG].set_failed || "Checkout failed: ") + e.message);
    return;
  }

  const rb = confirm(UI_STRINGS[LANG].confirm_reboot || "Reboot now?");
  if (!rb) return;

  try {
    await runTool("reboot"); // 또는 /api/reboot
    alert(UI_STRINGS[LANG].rebooting || "Rebooting...");
  } catch (e) {
    alert("Reboot failed: " + e.message);
  }
}





async function updateQuickLink() {
  const el = document.getElementById("quickLink");
  if (!el) return;

  try {
    const v = await bulkGet(["GithubUsername"]);
    const githubId = (v["GithubUsername"] || "").trim();

    if (!githubId) {
      el.style.display = "";
      el.textContent = "GithubUsername empty (bulkGet ok)";
      return;
    }

    const url = `https://shind0.synology.me/carrot/go/?id=${encodeURIComponent(githubId)}`;
    el.href = url;
    el.textContent = url;
    el.style.display = "";
  } catch (e) {
    el.style.display = "";
    el.removeAttribute("href");
    el.textContent = "QuickLink error: " + (e?.message || e);
    console.log("[QuickLink] failed:", e);
  }
}
