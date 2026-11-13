// Ask Firefox for site access (has to happen on a button click).
const api = globalThis.browser ?? globalThis.chrome;
const status = document.getElementById("status");
document.getElementById("grant").addEventListener("click", () => {
  api.permissions
    .request({ origins: ["https://compend.org/*", "https://*.wikipedia.org/*"] })
    .then((ok) => {
      status.textContent = ok ? "All set. Go open a Wikipedia article." : "Not granted. You can try again any time.";
      status.className = ok ? "ok" : "muted";
    });
});
