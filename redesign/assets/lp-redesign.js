/**
 * LearnPokémon — redesign layer (works with lp-redesign.css).
 *
 * The app itself is a compiled bundle, so this file never changes what the
 * app renders. It only reads what is on the page and adds:
 *   1. labels   — marks each card tile with its type and whether it is a foil,
 *                 so the stylesheet can colour and animate it
 *   2. tilt     — cards lean toward the cursor (or finger) and catch the light
 *   3. flight   — opening a card flies it from its place in the grid into the
 *                 detail view, and back again on close
 *   4. pack     — the pack in the middle of the timeline gets a foil glint
 *
 * Everything here is cosmetic. If this file fails to load, the site works
 * exactly as before.
 */
(function () {
  "use strict";
  if (window.__lpRedesign) return;
  window.__lpRedesign = true;

  var doc = document;
  var html = doc.documentElement;
  html.classList.add("lp2");

  var mqReduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  var reduced = function () { return mqReduce.matches; };

  /* ------------------------------------------------------------ 1. labels */

  var ALIAS = { lightning: "electric", colorless: "normal", metal: "steel", darkness: "dark" };
  // Which small hover effect each type gets (see "type hint" in the stylesheet).
  var FX = {
    fire: "rise", water: "rise", poison: "rise",
    ice: "fall", flying: "sweep", normal: "sweep", steel: "sweep",
    electric: "flash", fighting: "flash", ground: "fall", rock: "fall",
    grass: "drift", bug: "drift", psychic: "drift", ghost: "drift",
    fairy: "drift", dark: "drift", dragon: "drift",
  };
  // Rarities printed with a shiny finish. Plain "Rare" (non-holo) is not one.
  var FOIL = /holo|ultra|secret|rainbow|hyper|illustration|amazing|radiant|shin|legend|prism|star|ace spec|double rare|vmax|vstar|\bv\b|\bex\b|\bgx\b|break|prime|lv\.?x|promo|classic/i;

  function typeFromPill(node) {
    var pill = node.querySelector(".type-pill");
    if (!pill) return "";
    var t = pill.textContent.trim().toLowerCase();
    return ALIAS[t] || t;
  }

  function label(node) {
    var nameEl = node.querySelector("strong");
    var key = (node.getAttribute("data-flip-id") || "") + "|" + (nameEl ? nameEl.textContent : "");
    if (node.__lpKey === key) return;
    node.__lpKey = key;
    var type = typeFromPill(node);
    if (type) {
      node.setAttribute("data-lp-type", type);
      node.setAttribute("data-lp-fx", FX[type] || "sweep");
    } else {
      node.removeAttribute("data-lp-type");
      node.removeAttribute("data-lp-fx");
    }
    // The line reads "#4 · Rare Holo" or "Base #4 · Rare Holo"; only the rarity
    // at the end counts, so a set called "Legendary Collection" isn't mistaken for one.
    var meta = node.querySelector("em");
    var rarity = meta ? meta.textContent.split("·").pop() : "";
    if (FOIL.test(rarity)) node.setAttribute("data-lp-foil", "");
    else node.removeAttribute("data-lp-foil");
  }

  var scanQueued = false;
  function scan() {
    scanQueued = false;
    var nodes = doc.querySelectorAll(".card-tile, .ja-card, .dex-cell, .printing-card");
    for (var i = 0; i < nodes.length; i++) label(nodes[i]);
    markPack();
    watchModal();
  }
  function queueScan() {
    if (scanQueued) return;
    scanQueued = true;
    requestAnimationFrame(scan);
  }

  /* -------------------------------------------------------------- 2. tilt */

  var TILT_TARGETS = ".card-tile, .ja-card, .printing-card, .art-frame, .pack.is-center";
  var MAX_DEG = { "card-tile": 13, "printing-card": 10, "art-frame": 9, pack: 10 };
  var active = null;
  var pending = null;
  var frame = 0;

  function tiltBox(node) {
    // Measure the picture, not the whole tile, so the light lands on the card.
    if (node.classList.contains("art-frame")) return node;
    return node.querySelector("img, .thumb-fallback, .ja-missing") || node;
  }

  function applyTilt() {
    frame = 0;
    if (!pending || !active) return;
    var box = tiltBox(active).getBoundingClientRect();
    if (!box.width || !box.height) return;
    var x = Math.max(0, Math.min(1, (pending.x - box.left) / box.width));
    var y = Math.max(0, Math.min(1, (pending.y - box.top) / box.height));
    var kind = active.classList.contains("art-frame") ? "art-frame"
      : active.classList.contains("pack") ? "pack"
      : active.classList.contains("printing-card") ? "printing-card" : "card-tile";
    var max = MAX_DEG[kind];
    var s = active.style;
    s.setProperty("--lp-px", (x * 100).toFixed(1) + "%");
    s.setProperty("--lp-py", (y * 100).toFixed(1) + "%");
    s.setProperty("--lp-ry", ((x - 0.5) * 2 * max).toFixed(2) + "deg");
    s.setProperty("--lp-rx", ((0.5 - y) * 2 * max).toFixed(2) + "deg");
    // 0 at the centre of the card, 1 at a corner: drives how strong the glare is.
    s.setProperty("--lp-far", Math.min(1, Math.hypot(x - 0.5, y - 0.5) * 2).toFixed(3));
  }

  function setActive(node) {
    if (active === node) return;
    if (active) {
      active.classList.remove("lp-active");
      var old = active;
      // Let the stylesheet ease the card back to flat, then drop the numbers.
      setTimeout(function () {
        if (old === active) return;
        ["--lp-px", "--lp-py", "--lp-rx", "--lp-ry", "--lp-far"].forEach(function (p) {
          old.style.removeProperty(p);
        });
      }, 500);
    }
    active = node;
    if (active) active.classList.add("lp-active");
  }

  function onMove(e) {
    if (reduced()) return;
    var t = e.target;
    var node = t && t.closest ? t.closest(TILT_TARGETS) : null;
    if (e.pointerType === "touch" && !touching) node = null;
    setActive(node);
    if (!node) return;
    pending = { x: e.clientX, y: e.clientY };
    if (!frame) frame = requestAnimationFrame(applyTilt);
  }

  // Touch: a finger landing on a card is usually the start of a scroll, so wait
  // a beat before reacting. If the browser turns the touch into a scroll it
  // cancels the pointer first and nothing lights up.
  var touching = false;
  var touchTimer = 0;
  function onDown(e) {
    if (e.pointerType !== "touch") return;
    clearTimeout(touchTimer);
    touchTimer = setTimeout(function () {
      touching = true;
      onMove(e);
    }, 90);
  }
  function endTouch(keepMs) {
    clearTimeout(touchTimer);
    touching = false;
    var held = active;
    // A tap opens the card almost at once; keep the lean just long enough to be seen.
    setTimeout(function () { if (active === held) setActive(null); }, keepMs);
  }

  doc.addEventListener("pointermove", onMove, { passive: true });
  doc.addEventListener("pointerdown", onDown, { passive: true });
  doc.addEventListener("pointerup", function (e) { if (e.pointerType === "touch") endTouch(260); }, { passive: true });
  doc.addEventListener("pointercancel", function () { endTouch(0); }, { passive: true });
  html.addEventListener("pointerleave", function () { setActive(null); });
  window.addEventListener("blur", function () { setActive(null); });

  /* ------------------------------------------------------------ 3. flight */

  var EASE = "cubic-bezier(.2,.85,.25,1)";
  var origin = null; // where the last opened card came from
  var modalSeen = null;
  var closing = null;
  var veil = null;

  function pictureOf(node) {
    return node ? node.querySelector("img") : null;
  }

  function onScreen(r) {
    return r.width > 4 && r.bottom > 0 && r.top < window.innerHeight && r.right > 0 && r.left < window.innerWidth;
  }

  // The flying card is a snapshot painted from the picture already on screen,
  // so it shows instantly instead of waiting on the network for a second copy.
  function snapshot(img, rect) {
    if (!img || !img.complete || !img.naturalWidth) return null;
    var dpr = Math.min(2, window.devicePixelRatio || 1);
    var c = doc.createElement("canvas");
    c.width = Math.max(1, Math.round(rect.width * dpr));
    c.height = Math.max(1, Math.round(rect.height * dpr));
    var fit = Math.min(c.width / img.naturalWidth, c.height / img.naturalHeight);
    var w = img.naturalWidth * fit;
    var h = img.naturalHeight * fit;
    try {
      c.getContext("2d").drawImage(img, (c.width - w) / 2, (c.height - h) / 2, w, h);
    } catch (e) {
      return null;
    }
    return c;
  }

  function makeGhost(canvas, rect, radius) {
    canvas.className = "lp-ghost";
    canvas.style.cssText =
      "left:" + rect.left + "px;top:" + rect.top + "px;width:" + rect.width + "px;height:" + rect.height + "px;" +
      "border-radius:" + radius;
    doc.body.appendChild(canvas);
    return canvas;
  }

  function between(from, to) {
    var sx = to.width / from.width;
    var sy = to.height / from.height;
    var s = Math.min(sx, sy); // pictures are letterboxed, never stretched
    var dx = to.left + to.width / 2 - (from.left + from.width / 2);
    var dy = to.top + to.height / 2 - (from.top + from.height / 2);
    return { dx: dx, dy: dy, s: s };
  }

  // Remember what was clicked, before the app opens the detail view.
  doc.addEventListener(
    "click",
    function (e) {
      var t = e.target;
      if (!t || !t.closest) return;
      var src = t.closest(".card-tile, .ja-card, .dex-cell, .printing-card, .first-card");
      var img = pictureOf(src);
      if (src && img && img.complete && img.naturalWidth) {
        origin = { node: src, img: img, rect: img.getBoundingClientRect(), src: img.currentSrc || img.src, at: performance.now() };
      }
      // Closing: note where the big card is right now, because the app removes it instantly.
      var back = t.closest(".modal-back");
      if (back && (t === back || t.closest(".modal-close"))) noteClose(back);
    },
    true
  );
  doc.addEventListener(
    "keydown",
    function (e) {
      if (e.key !== "Escape") return;
      var back = doc.querySelector(".modal-back");
      if (back) noteClose(back);
    },
    true
  );

  function noteClose(back) {
    var frameEl = back.querySelector(".art-frame");
    var img = pictureOf(frameEl);
    if (!frameEl || !img) return;
    var rect = frameEl.getBoundingClientRect();
    closing = { rect: rect, src: img.currentSrc || img.src, shot: snapshot(img, rect), at: performance.now() };
  }

  function flyOpen(back) {
    var frameEl = back.querySelector(".art-frame");
    if (!frameEl || !origin || performance.now() - origin.at > 900) return;
    if (reduced() || !onScreen(origin.rect)) return;
    var o = origin;
    var isCard = frameEl.classList.contains("is-card");
    // Show the small picture under the big one until the full-size image arrives.
    var big = pictureOf(frameEl);
    if (isCard && big && !(big.complete && big.naturalWidth)) {
      frameEl.style.setProperty("--lp-ph", 'url("' + o.src.replace(/"/g, "%22") + '")');
      big.addEventListener("load", function () { frameEl.style.removeProperty("--lp-ph"); }, { once: true });
    }
    back.classList.add("lp-flying");
    requestAnimationFrame(function () {
      var to = frameEl.getBoundingClientRect();
      if (!to.width) { back.classList.remove("lp-flying"); return; }
      var shot = snapshot(o.img, o.rect);
      if (!shot) { back.classList.remove("lp-flying"); return; }
      var ghost = makeGhost(shot, o.rect, isCard ? "4.6% / 3.3%" : "0");
      o.img.classList.add("lp-lifted");
      var m = between(o.rect, to);
      var lift = Math.min(1.12, m.s * 1.04);
      var anim = ghost.animate(
        [
          { transform: "translate(0,0) scale(1) rotate(0deg)", offset: 0 },
          { transform: "translate(" + m.dx * 0.55 + "px," + (m.dy * 0.55 - 26) + "px) scale(" + (1 + (lift * m.s - 1) * 0.62) + ") rotate(" + (m.dx > 0 ? 3 : -3) + "deg)", offset: 0.55 },
          { transform: "translate(" + m.dx + "px," + m.dy + "px) scale(" + m.s + ") rotate(0deg)", offset: 1 },
        ],
        { duration: 460, easing: EASE, fill: "forwards" }
      );
      var land = function () {
        back.classList.remove("lp-flying");
        back.classList.add("lp-landed");
        o.img.classList.remove("lp-lifted");
        var fade = ghost.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 140, fill: "forwards" });
        fade.onfinish = fade.oncancel = function () { ghost.remove(); };
      };
      anim.onfinish = land;
      anim.oncancel = land;
    });
  }

  function flyClose() {
    var c = closing;
    closing = null;
    if (!c || performance.now() - c.at > 500 || reduced()) return;
    // A soft fade where the dark backdrop was, so the page doesn't snap back.
    if (!veil) {
      veil = doc.createElement("div");
      veil.className = "lp-veil";
    }
    doc.body.appendChild(veil);
    var v = veil.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 260, easing: "ease-out", fill: "forwards" });
    v.onfinish = v.oncancel = function () { veil.remove(); };

    var o = origin;
    if (!o || !o.node.isConnected || !o.img.isConnected) return;
    var to = o.img.getBoundingClientRect();
    if (!onScreen(to) || !onScreen(c.rect)) return;
    // Only fly home if the big card still shows the picture that was opened.
    var same = function (a, b) { return a.replace(/_hires|\/(high|low)\./g, "") === b.replace(/_hires|\/(high|low)\./g, ""); };
    if (!same(c.src, o.src) && !o.node.classList.contains("dex-cell")) return;
    var isCard = !o.node.classList.contains("dex-cell");
    var shot = c.shot || snapshot(o.img, c.rect);
    if (!shot) return;
    var ghost = makeGhost(shot, c.rect, isCard ? "4.6% / 3.3%" : "0");
    o.img.classList.add("lp-lifted");
    var m = between(c.rect, to);
    var anim = ghost.animate(
      [
        { transform: "translate(0,0) scale(1)" },
        { transform: "translate(" + m.dx + "px," + m.dy + "px) scale(" + m.s + ")" },
      ],
      { duration: 340, easing: EASE, fill: "forwards" }
    );
    var done = function () {
      o.img.classList.remove("lp-lifted");
      ghost.remove();
    };
    anim.onfinish = done;
    anim.oncancel = done;
  }

  function watchModal() {
    var back = doc.querySelector(".modal-back");
    if (back === modalSeen) return;
    var was = modalSeen;
    modalSeen = back;
    html.classList.toggle("lp-modal-open", !!back);
    if (back && !was) flyOpen(back);
    else if (!back && was) flyClose();
  }

  /* -------------------------------------------------------------- 4. pack */

  // The glint is clipped to the pack's own outline, which needs the image URL.
  function markPack() {
    var box = doc.querySelector(".pack.is-center .pack-artbox");
    if (!box) return;
    var img = box.querySelector("img");
    var src = img && (img.currentSrc || img.src);
    if (!src || box.__lpSrc === src) return;
    box.__lpSrc = src;
    box.style.setProperty("--lp-pack", 'url("' + src.replace(/"/g, "%22") + '")');
  }

  /* -------------------------------------------------------------- start */

  function start() {
    scan();
    new MutationObserver(function (list) {
      // The battle changes classes several times a second; none of that needs a rescan.
      for (var i = 0; i < list.length; i++) {
        var t = list[i].target;
        if (t.nodeType === 1 && !t.closest(".lp-vs-root")) { queueScan(); return; }
      }
    }).observe(doc.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["class", "src"],
    });
  }
  if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", start);
  else start();
})();
