/*
  OTA 更新頁的行為：上傳更新包、要求套用、顯示狀態與進度
  Choose File ─> Update ─> PUT /api/upload ─> POST /api/apply
                     輪詢 /api/status ─> 版本、裝置名稱、進度條、log 窗
*/
const STATES = {
  verifying: "Verifying package...",
  writing: "Writing image. Do not power off.",
  pending: "Rebooting and checking the new version...",
  committed: "Update succeeded.",
  failed: "Update failed.",
  rolled_back: "Rolled back to the previous version.",
};
const ERRORS = {
  bad_bundle: "Invalid or incomplete update package.",
  bad_hash: "Update package is corrupted.",
  wrong_device: "Update package is for a different device.",
  not_newer: "Update package is not newer than the current version.",
  too_large: "Image is larger than the partition.",
  busy: "Another update is in progress.",
  write_failed: "Writing failed.",
  interrupted: "The previous update was interrupted.",
  health_failed: "The new version failed the health check.",
  commit_failed: "The new version booted but could not be confirmed.",
  rolled_back: "The new version did not boot.",
  no_space: "Not enough space on the device.",
  no_upload: "No uploaded package.",
};
// 裝置忙碌中的狀態，以及進度條上顯示的文字
const LABELS = { verifying: "Verifying", writing: "Writing", pending: "Rebooting" };
const BUSY = Object.keys(LABELS);
const $ = (id) => document.getElementById(id);
let working = false;    // 上傳或送出更新要求中
let latest = null;      // 最近一次狀態；null 代表還沒連上或斷線
let lastKey = null;     // 狀態有變才寫 log
let version = null;
let offline = false;
let generation = 0;     // 送出更新前發出的查詢結果要丟掉

function log(text) {
  const time = new Date().toLocaleTimeString("en-GB");
  $("log").textContent += `[${time}] ${text}\n`;
  $("log").scrollTop = $("log").scrollHeight;
}

function progress(percent, label) {
  $("progress").style.setProperty("--percent", percent);
  $("progress").setAttribute("aria-valuenow", percent);
  $("progress").setAttribute("aria-valuetext", label);
  $("progress-text").textContent = label;
  $("progress-fill").textContent = label;
}

// 依裝置狀態畫進度條；null 代表斷線
function showStatus(status) {
  if (!status) return progress(0, "Reconnecting...");
  if (!status.progress) return progress(0, LABELS[status.state] || "Ready");
  const { part, percent } = status.progress;
  progress(percent, `Writing ${part} ${percent}%`);
}

function buttons() {
  const busy = working || !latest || BUSY.includes(latest.state);
  $("choose").disabled = busy;
  $("update").disabled = busy || !$("file").files.length;
}

function describe(status) {
  if (status.state === "idle") return "Ready.";
  let text = STATES[status.state] || status.state;
  if (status.progress) {
    text = `Writing ${status.progress.part}: ${status.progress.percent}% (do not power off)`;
  }
  if (status.target) text += ` [version ${status.target}]`;
  if (status.error) text += ` ${ERRORS[status.error] || status.error}`;
  return text;
}

function render(status) {
  if (offline) log("Reconnected.");
  offline = false;
  if (version !== null && version !== status.version) {
    log(`Current version is now ${status.version}.`);
  }
  version = status.version;
  $("version").textContent = version;
  $("device").textContent = status.device;
  const key = JSON.stringify([status.state, status.error, status.target, status.progress]);
  if (key !== lastKey) {
    // 第一次載入時看到的結束狀態是上一次的結果
    const firstLoad = lastKey === null && generation === 0;
    const isPreviousResult = firstLoad
      && status.state !== "idle" && !BUSY.includes(status.state);
    log((isPreviousResult ? "Last update: " : "") + describe(status));
    lastKey = key;
  }
  latest = status;
  if (!working) showStatus(status);
}

async function poll() {
  const sent = generation;
  if (!working) {
    try {
      const response = await fetch("/api/status", { signal: AbortSignal.timeout(5000) });
      if (!response.ok) throw new Error();
      const status = await response.json();
      if (sent === generation && !working) render(status);
    } catch {
      if (sent === generation && !working) {
        if (!offline) log("Connection lost. The device may be rebooting...");
        offline = true;
        latest = null;
        showStatus(latest);
      }
    }
    buttons();
  }
  setTimeout(poll, 1000);
}

function upload(file) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    let logged = 0;
    request.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      const percent = Math.floor(e.loaded / e.total * 100);
      progress(percent, `Uploading ${percent}%`);
      if (percent >= logged + 10) {
        logged = percent - percent % 10;
        log(`Uploading: ${logged}%`);
      }
    };
    request.onload = () => {
      let body = {};
      try { body = JSON.parse(request.responseText); } catch {}
      if (request.status === 202) resolve(body.version);
      else reject(ERRORS[body.error] || `HTTP ${request.status}`);
    };
    request.onerror = () => reject("Connection lost.");
    request.open("PUT", "/api/upload");
    request.send(file);
  });
}

async function apply() {
  let body;
  try {
    body = await (await fetch("/api/apply", { method: "POST" })).json();
  } catch {
    throw "Could not send the update request.";
  }
  if (!body.ok) throw ERRORS[body.error] || body.error;
}

$("choose").addEventListener("click", () => $("file").click());

// 收合時無法捲動，展開時補捲到最新的訊息
$("logbox").addEventListener("toggle", () => { $("log").scrollTop = $("log").scrollHeight; });

$("file").addEventListener("change", () => {
  const file = $("file").files[0];
  $("filename").textContent = file ? file.name : "No file chosen";
  $("filename").title = file ? file.name : "";
  buttons();
});

/*
  按 Update 之後：
  working=true（暫停顯示輪詢結果）
    ─> upload() ─> apply() ─┬─ 成功 ─> 假定狀態為 verifying
                            └─ 失敗 ─> log 顯示原因
    ─> working=false ─> poll() 接手顯示裝置狀態
  generation 前後各加一次：丟掉這段期間發出的舊查詢結果
*/
$("update").addEventListener("click", async () => {
  const file = $("file").files[0];
  if (!file) return;
  working = true;
  generation++;
  buttons();
  progress(0, "Uploading 0%");
  log(`Uploading ${file.name}...`);
  try {
    log(`Upload complete: version ${await upload(file)}.`);
    await apply();
    log("Update started.");
    lastKey = null;
    latest = { state: "verifying" };
  } catch (message) {
    log(`Update failed. ${message}`);
  }
  showStatus(latest);
  generation++;
  working = false;
  buttons();
});

poll();
