chrome.storage.local.get("recording").then(({ recording }) => {
  const el = document.getElementById("status");
  el.textContent = recording ? "● Recording" : "Idle";
  el.classList.toggle("rec", Boolean(recording));
});
