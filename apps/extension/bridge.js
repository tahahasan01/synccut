// Runs on the SyncCut app page: relays messages between the page and the extension.

(() => {
  const version = chrome.runtime.getManifest().version;
  const hello = () => window.postMessage({ source: "synccut-ext", type: "hello", version }, location.origin);

  window.addEventListener("message", (e) => {
    if (e.source !== window || e.data?.source !== "synccut-app") return;
    if (e.data.type === "ping") return hello();
    chrome.runtime.sendMessage({ kind: "app", type: e.data.type }).catch(() => {});
  });

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg?.kind === "to-app") window.postMessage(msg.payload, location.origin);
  });

  hello();
})();
