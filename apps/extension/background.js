// Collects browser events while a SyncCut take is recording and forwards them
// to the SyncCut app tab. Recording state lives in storage so it survives the
// service worker being suspended.

const now = () => performance.timeOrigin + performance.now();

async function getState() {
  const { recording = false, appTabId = null } = await chrome.storage.local.get(["recording", "appTabId"]);
  return { recording, appTabId };
}

async function setRecording(recording, appTabId) {
  await chrome.storage.local.set({ recording, appTabId: recording ? appTabId : null });
  await chrome.action.setBadgeText({ text: recording ? "REC" : "" });
  if (recording) await chrome.action.setBadgeBackgroundColor({ color: "#dc2626" });
}

async function toApp(payload) {
  const { appTabId } = await getState();
  if (appTabId == null) return;
  try {
    await chrome.tabs.sendMessage(appTabId, { kind: "to-app", payload: { source: "synccut-ext", ...payload } });
  } catch {
    // App tab closed or reloaded; stop recording state so nothing keeps collecting.
    await setRecording(false, null);
  }
}

async function emit(event, tabId) {
  const { recording, appTabId } = await getState();
  if (!recording || tabId === appTabId) return;
  await toApp({ type: "event", event: { epoch_ms: now(), tab_id: tabId ?? null, ...event } });
}

chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg?.kind === "app") {
    if (msg.type === "recording-start") setRecording(true, sender.tab?.id ?? null);
    if (msg.type === "recording-stop") setRecording(false, null);
    return;
  }
  if (msg?.kind === "page-event" && sender.tab) {
    emit({ ...msg.event, epoch_ms: msg.event.epoch_ms ?? now(), url: sender.tab.url, title: sender.tab.title }, sender.tab.id);
  }
});

chrome.tabs.onActivated.addListener(async ({ tabId, windowId }) => {
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  emit({ type: "tab_activated", window_id: windowId, url: tab?.url, title: tab?.title }, tabId);
});
chrome.tabs.onCreated.addListener((tab) => emit({ type: "tab_created", window_id: tab.windowId, url: tab.pendingUrl || tab.url }, tab.id));
chrome.tabs.onRemoved.addListener((tabId) => emit({ type: "tab_closed" }, tabId));
chrome.windows.onFocusChanged.addListener((windowId) => {
  if (windowId !== chrome.windows.WINDOW_ID_NONE) emit({ type: "window_focus", window_id: windowId });
});

chrome.webNavigation.onCommitted.addListener((d) => {
  if (d.frameId !== 0) return;
  const history = (d.transitionQualifiers || []).includes("forward_back");
  emit({ type: history ? "history" : "navigation", url: d.url, transition: d.transitionType }, d.tabId);
});
chrome.webNavigation.onCompleted.addListener((d) => {
  if (d.frameId === 0) emit({ type: "page_loaded", url: d.url }, d.tabId);
});

chrome.commands.onCommand.addListener(async (command) => {
  const { recording } = await getState();
  if (command === "next-beat" && recording) toApp({ type: "command", command: "next-beat" });
});

chrome.runtime.onStartup.addListener(() => setRecording(false, null));
chrome.runtime.onInstalled.addListener(() => setRecording(false, null));
