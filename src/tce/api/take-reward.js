/* A short, silent burst beside a saved take. The caller owns the visible
   confirmation and supplies a server-confirmed session or talk ID. */
(() => {
  "use strict";

  const key = "tce-celebrated-takes";
  const seen = new Set();
  const colors = ["#f6bd39", "#318267", "#ee7553", "#4085bc", "#8766b6"];

  function show(id, anchor) {
    if (!id || !anchor || window.TCE_SCOPED || document.hidden || !anchor.getClientRects().length) return;
    try {
      const stored = JSON.parse(localStorage.getItem(key) || "[]");
      if (Array.isArray(stored)) stored.forEach(value => seen.add(value));
    } catch { /* The in-memory set also works in a private tab. */ }
    if (seen.has(id)) return;
    seen.add(id);
    try { localStorage.setItem(key, JSON.stringify([...seen].slice(-64))); } catch { /* optional */ }
    if (matchMedia("(prefers-reduced-motion: reduce)").matches || !Element.prototype.animate) return;

    const box = anchor.getBoundingClientRect();
    if (box.bottom <= 0 || box.top >= innerHeight) return;
    const layer = document.createElement("div");
    layer.className = "take-confetti";
    layer.setAttribute("aria-hidden", "true");
    layer.style.cssText = "position:fixed;inset:0;overflow:hidden;pointer-events:none;z-index:20";
    document.body.append(layer);
    const x = Math.min(innerWidth - 24, Math.max(24, box.right - box.width * .22));
    const y = Math.max(16, Math.min(innerHeight - 12, box.top + 14));
    for (let i = 0; i < 22; i++) {
      const piece = document.createElement("i");
      piece.style.cssText = `position:absolute;left:${x}px;top:${y}px;width:5px;height:9px;border-radius:2px;background:${colors[i % colors.length]}`;
      layer.append(piece);
      const dx = (i / 21 - .5) * (125 + Math.random() * 90);
      const rise = 24 + Math.random() * 56;
      piece.animate([
        { transform: "translate(0,0) rotate(0)" },
        { transform: `translate(${dx * .65}px,-${rise}px) rotate(${i * 17}deg)`, offset: .42 },
        { transform: `translate(${dx}px,${rise * .7}px) rotate(${i * 31}deg)`, opacity: 0 },
      ], { duration: 700 + Math.random() * 230, fill: "forwards" });
    }
    setTimeout(() => layer.remove(), 1000);
  }

  window.TCETakeReward = { show };
})();
