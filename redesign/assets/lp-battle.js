/**
 * LearnPokémon — set-page battle, turn-based (replaces lp-vs-battle.js).
 *
 * Two Pokémon from the CURRENT set fight using the numbers printed on their
 * cards: HP, attack names and damage, weakness and resistance. One attacks,
 * the other reacts, HP drops, and when one faints the next challenger from
 * the set walks in.
 *
 * Two layouts, picked by screen width (see lp-redesign.css):
 *   flank — wide screens: fighters stand in the page margins, behind the cards
 *   stage — everything narrower: a band under the set header, in the page flow
 *
 * The attack artwork itself (fire, water, lightning…) is still drawn by
 * lp-vs-battle.css, so the class names it expects are kept:
 *   .lp-vs-root.is-firing-left/right, .lp-vs-flank.is-attacking/.is-hit,
 *   .lp-vs-fx[data-kind]
 *
 * Decorative only: aria-hidden, pointer-events none, off for reduced motion.
 */
(function () {
  "use strict";
  if (window.__lpBattle) return;
  window.__lpBattle = true;

  // Same palette the app uses for its type pills, so the glow matches the labels.
  var TYPE_COLOR = {
    normal: "#A8A77A", fire: "#EE8130", water: "#6390F0", electric: "#F7D02C",
    grass: "#7AC74C", ice: "#96D9D6", fighting: "#C22E28", poison: "#A33EA1",
    ground: "#E2BF65", flying: "#A98FF3", psychic: "#F95587", bug: "#A6B91A",
    rock: "#B6A136", ghost: "#735797", dragon: "#6F35FC", dark: "#705746",
    steel: "#B7B7CE", fairy: "#D685AD",
  };
  var TYPE_LIGHT = {
    normal: "#fff6d8", fire: "#ffd56a", water: "#d7f3ff", electric: "#fff4b0",
    grass: "#d4f5a4", ice: "#f3fbff", fighting: "#ffb199", poison: "#e7a0e8",
    ground: "#f0ddb0", flying: "#e4dcff", psychic: "#f3d9ff", bug: "#e4f5a0",
    rock: "#efe0a0", ghost: "#d9c8ee", dragon: "#d7c6ff", dark: "#c7b8e8",
    steel: "#eef1f4", fairy: "#ffe0f0",
  };
  var ALIAS = { lightning: "electric", colorless: "normal", metal: "steel", darkness: "dark" };

  var FLANK_QUERY = "(min-width: 1600px) and (min-height: 521px)";
  var TURN_MS = 2700; // one full attack, start to start
  var KO_PAUSE_MS = 1500; // loser stays down this long before the next one enters
  var MAX_WINS = 3; // a winner retires after this many, so the pair keeps changing

  var SPRITE = function (id, official) {
    return official
      ? "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/" + id + ".png"
      : "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/" + id + ".png";
  };

  var root = null;
  var el = {}; // left/right: { flank, img, name, bar, hpText, dmg, fx }
  var caption = null;

  var activeKey = null;
  var loadingKey = null;
  var deadKeys = new Set(); // sets with fewer than two Pokémon: nothing to stage
  var isJa = false;
  var roster = [];
  var cursor = 0;
  var fighters = { left: null, right: null };
  var nextSide = "left";
  var timers = [];
  var running = false;
  var visibleKeys = [];
  var tileIO = null;
  var stageIO = null;
  var stageOnScreen = true;
  var lastPath = "";
  var cardCache = new Map();
  var reducedMotion = false;
  var mqFlank = null;
  var heroRO = null;

  /* ------------------------------------------------------------ data */

  function kindOf(types) {
    var raw = String((types && types[0]) || "colorless").trim().toLowerCase();
    raw = ALIAS[raw] || raw;
    return TYPE_COLOR[raw] ? raw : "normal";
  }

  function num(v) {
    var n = parseInt(String(v == null ? "" : v).replace(/[^\d]/g, ""), 10);
    return isFinite(n) ? n : 0;
  }

  function pathInfo(pathname) {
    var m = (pathname || location.pathname).match(/^\/(?:(ja|en-ja|ja-en)\/)?sets\/([^/]+)\/?$/i);
    if (!m) return null;
    return { id: decodeURIComponent(m[2]), isJa: /^(ja|en-ja)$/i.test(m[1] || "") };
  }

  function toFighter(c) {
    var superType = String(c.supertype || c.category || "");
    var dexList = c.nationalPokedexNumbers || c.dexId || [];
    if (!/pok/i.test(superType) && !dexList.length) return null;
    var dex = Number(dexList[0]);
    if (!isFinite(dex) || dex < 1 || dex > 1025) return null;
    var types = c.types || [];
    var moves = (c.attacks || [])
      .map(function (a) { return { name: a.name || "", damage: num(a.damage) }; })
      .filter(function (a) { return a.name; });
    var hp = num(c.hp) || 60;
    return {
      dex: dex,
      cardId: c.id || "",
      name: c.name || "Pokémon #" + dex,
      kind: kindOf(types),
      type: String(types[0] || "Colorless").toLowerCase(),
      maxHp: hp,
      hp: hp,
      moves: moves,
      weak: c.weaknesses || [],
      resist: c.resistances || [],
      wins: 0,
    };
  }

  function uniqueRoster(cards) {
    var byDex = new Map();
    (cards || []).forEach(function (c) {
      var f = toFighter(c);
      if (f && !byDex.has(f.dex)) byDex.set(f.dex, f);
    });
    return Array.from(byDex.values());
  }

  function loadEnCards(setId) {
    var key = "en:" + setId;
    if (cardCache.has(key)) return Promise.resolve(cardCache.get(key));
    return fetch("/data/cards/" + encodeURIComponent(setId) + ".json")
      .then(function (res) {
        if (!res.ok) throw new Error("cards " + res.status);
        return res.json();
      })
      .then(function (data) {
        var list = uniqueRoster(Array.isArray(data) ? data : []);
        cardCache.set(key, list);
        return list;
      });
  }

  function hydrateJa(briefs) {
    var out = [];
    var chunks = [];
    for (var i = 0; i < briefs.length; i += 8) chunks.push(briefs.slice(i, i + 8));
    return chunks
      .reduce(function (p, slice) {
        return p.then(function () {
          if (out.length >= 24) return;
          return Promise.all(
            slice.map(function (b) {
              return fetch("https://api.tcgdex.net/v2/ja/cards/" + encodeURIComponent(b.id))
                .then(function (r) { return r.ok ? r.json() : null; })
                .catch(function () { return null; });
            })
          ).then(function (parts) {
            parts.forEach(function (p) {
              if (p && (String(p.category || "").toLowerCase() === "pokemon" || p.dexId)) out.push(p);
            });
          });
        });
      }, Promise.resolve())
      .then(function () { return out; });
  }

  function loadJaRoster(setId) {
    var key = "ja:" + setId;
    if (cardCache.has(key)) return Promise.resolve(cardCache.get(key));
    var done = function (cards) {
      var r = uniqueRoster(cards);
      cardCache.set(key, r);
      return r;
    };
    return fetch("/data/ja-cards/" + encodeURIComponent(setId) + ".json")
      .then(function (local) {
        var isJson = (local.headers.get("content-type") || "").indexOf("json") > -1;
        if (!local.ok || !isJson) throw new Error("no local snapshot");
        return local.json();
      })
      .then(function (data) {
        if (!Array.isArray(data) || !data.length) throw new Error("empty snapshot");
        if (data[0].dexId || data[0].nationalPokedexNumbers) return done(data);
        return hydrateJa(data.slice(0, 40)).then(done);
      })
      .catch(function () {
        return fetch("https://api.tcgdex.net/v2/ja/sets/" + encodeURIComponent(setId))
          .then(function (r) {
            if (!r.ok) throw new Error("ja set " + r.status);
            return r.json();
          })
          .then(function (setJson) { return hydrateJa((setJson.cards || []).slice(0, 48)); })
          .then(done);
      });
  }

  /* ------------------------------------------------------------- dom */

  function fxMarkup(side) {
    var p = "";
    for (var i = 0; i < 6; i++) p += '<span class="lp-vs-p"></span>';
    return (
      '<div class="lp-vs-fx lp-vs-fx--' + side + '" data-kind="normal">' +
      '<div class="lp-vs-fx-spin"><div class="lp-vs-fx-art">' +
      '<div class="lp-vs-fx-glow"></div><div class="lp-vs-fx-core"></div>' +
      '<i class="lp-vs-layer lp-vs-l1"></i><i class="lp-vs-layer lp-vs-l2"></i>' +
      '<i class="lp-vs-layer lp-vs-l3"></i><i class="lp-vs-layer lp-vs-l4"></i>' +
      p + "</div></div></div>"
    );
  }

  function flankMarkup(side) {
    return (
      '<div class="lp-vs-flank lp-vs-flank--' + side + '" data-side="' + side + '">' +
      '<div class="lp-vs-plate">' +
      '<span class="lp-vs-name"></span>' +
      '<span class="lp-vs-hp"><i></i></span>' +
      '<span class="lp-vs-hptext"></span>' +
      "</div>" +
      '<div class="lp-vs-sprite-wrap">' +
      '<img class="lp-vs-sprite" alt="" width="336" height="336" decoding="async" />' +
      '<span class="lp-vs-dmg"></span>' +
      "</div>" +
      "</div>"
    );
  }

  function ensureFilters() {
    if (document.getElementById("lp-vs-filters")) return;
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.id = "lp-vs-filters";
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("width", "0");
    svg.setAttribute("height", "0");
    svg.style.cssText = "position:absolute;width:0;height:0;overflow:hidden";
    svg.innerHTML =
      '<filter id="lp-flame-turb" x="-20%" y="-20%" width="140%" height="140%">' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.012 0.045" numOctaves="3" seed="3" result="n"/>' +
      '<feDisplacementMap in="SourceGraphic" in2="n" scale="26" xChannelSelector="R" yChannelSelector="G"/></filter>' +
      '<filter id="lp-water-turb" x="-15%" y="-30%" width="130%" height="160%">' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.008 0.05" numOctaves="2" seed="8" result="n"/>' +
      '<feDisplacementMap in="SourceGraphic" in2="n" scale="14" xChannelSelector="R" yChannelSelector="G"/></filter>' +
      '<filter id="lp-gas-turb" x="-25%" y="-25%" width="150%" height="150%">' +
      '<feTurbulence type="turbulence" baseFrequency="0.015 0.02" numOctaves="3" seed="5" result="n"/>' +
      '<feDisplacementMap in="SourceGraphic" in2="n" scale="30" xChannelSelector="R" yChannelSelector="G"/></filter>';
    document.body.appendChild(svg);
  }

  function ensureDom() {
    if (root) return;
    ensureFilters();
    root = document.createElement("div");
    root.id = "lp-vs-battle";
    root.className = "lp-vs-root lp-arena";
    root.setAttribute("aria-hidden", "true");
    root.hidden = true;
    root.innerHTML =
      flankMarkup("left") + flankMarkup("right") + fxMarkup("left") + fxMarkup("right") +
      '<div class="lp-vs-caption"><span></span></div>';
    ["left", "right"].forEach(function (side) {
      var flank = root.querySelector(".lp-vs-flank--" + side);
      el[side] = {
        flank: flank,
        img: flank.querySelector(".lp-vs-sprite"),
        name: flank.querySelector(".lp-vs-name"),
        bar: flank.querySelector(".lp-vs-hp i"),
        hp: flank.querySelector(".lp-vs-hp"),
        hpText: flank.querySelector(".lp-vs-hptext"),
        dmg: flank.querySelector(".lp-vs-dmg"),
        fx: root.querySelector(".lp-vs-fx--" + side),
      };
    });
    caption = root.querySelector(".lp-vs-caption span");
  }

  function host() {
    return document.querySelector(".set-page");
  }

  function placeRoot() {
    var h = host();
    if (!root || !h) return;
    if (root.parentElement !== h) h.appendChild(root);
  }

  /* ----------------------------------------------------------- layout */

  function mode() {
    return mqFlank && mqFlank.matches ? "flank" : "stage";
  }

  // In stage mode the band sits directly under the set header. The header's
  // height changes with the set and the screen, so measure it instead of guessing.
  function measureStage() {
    var h = host();
    if (!root || !h) return;
    var m = mode();
    root.dataset.mode = m;
    if (root.hidden) {
      h.removeAttribute("data-lp-arena");
      return;
    }
    h.setAttribute("data-lp-arena", m);
    if (m !== "stage") return;
    var hero = h.querySelector(".set-hero");
    var inner = h.querySelector(".set-inner");
    if (!hero || !inner) return;
    var pageBox = h.getBoundingClientRect();
    var heroBox = hero.getBoundingClientRect();
    var innerBox = inner.getBoundingClientRect();
    var cs = getComputedStyle(inner);
    var padL = parseFloat(cs.paddingLeft) || 0;
    var padR = parseFloat(cs.paddingRight) || 0;
    root.style.setProperty("--lp-arena-top", Math.round(heroBox.bottom - pageBox.top) + "px");
    root.style.setProperty("--lp-arena-left", Math.round(innerBox.left - pageBox.left + padL) + "px");
    root.style.setProperty("--lp-arena-width", Math.round(innerBox.width - padL - padR) + "px");
  }

  function watchLayout() {
    if (heroRO) heroRO.disconnect();
    var h = host();
    if (!h || typeof ResizeObserver === "undefined") return;
    heroRO = new ResizeObserver(function () { measureStage(); });
    var hero = h.querySelector(".set-hero");
    var inner = h.querySelector(".set-inner");
    if (hero) heroRO.observe(hero);
    if (inner) heroRO.observe(inner);

    if (stageIO) stageIO.disconnect();
    stageOnScreen = true;
    if (typeof IntersectionObserver !== "undefined") {
      stageIO = new IntersectionObserver(function (entries) {
        stageOnScreen = entries[entries.length - 1].isIntersecting;
      });
      stageIO.observe(root);
    }
  }

  /* ---------------------------------------------------------- fighters */

  function later(fn, ms) {
    var id = setTimeout(function () {
      timers = timers.filter(function (t) { return t !== id; });
      fn();
    }, ms);
    timers.push(id);
    return id;
  }

  function clearTimers() {
    timers.forEach(clearTimeout);
    timers = [];
  }

  function fresh(base) {
    var f = Object.assign({}, base);
    f.hp = f.maxHp;
    f.wins = 0;
    return f;
  }

  // Next challenger: prefer a Pokémon whose card is on screen right now.
  function nextFighter(avoidDex) {
    var pool = roster;
    if (visibleKeys.length) {
      var vis = roster.filter(function (r) {
        return visibleKeys.indexOf(r.cardId) > -1 || visibleKeys.indexOf(r.name.toLowerCase()) > -1;
      });
      if (vis.length >= 3) pool = vis;
    }
    for (var i = 0; i < pool.length; i++) {
      var pick = pool[(cursor + i) % pool.length];
      if (avoidDex.indexOf(pick.dex) === -1) {
        cursor = (cursor + i + 1) % 100000;
        return fresh(pick);
      }
    }
    return fresh(roster[cursor++ % roster.length]);
  }

  function paintHp(side, instant) {
    var f = fighters[side];
    var e = el[side];
    if (!f) return;
    var pct = Math.max(0, Math.min(1, f.hp / f.maxHp));
    e.hp.classList.toggle("is-instant", !!instant);
    e.bar.style.transform = "scaleX(" + pct + ")";
    e.hp.dataset.level = pct > 0.5 ? "ok" : pct > 0.2 ? "low" : "crit";
    e.hpText.textContent = Math.max(0, f.hp) + "/" + f.maxHp;
  }

  function seat(side, f) {
    var e = el[side];
    fighters[side] = f;
    var c1 = TYPE_COLOR[f.kind];
    var c2 = TYPE_LIGHT[f.kind];
    [e.flank, e.fx].forEach(function (n) {
      n.style.setProperty("--lp-atk", c1);
      n.style.setProperty("--lp-atk2", c2);
      n.dataset.kind = f.kind;
    });
    e.img.onerror = function () {
      e.img.onerror = null;
      e.img.src = SPRITE(f.dex, false);
    };
    e.img.src = SPRITE(f.dex, true);
    e.name.textContent = f.name;
    paintHp(side, true);
    e.flank.classList.remove("is-fainted", "is-attacking", "is-hit", "is-windup", "is-winner");
    e.flank.classList.remove("is-entering");
    void e.flank.offsetWidth;
    e.flank.classList.add("is-entering");
    later(function () { e.flank.classList.remove("is-entering"); }, 700);
  }

  // speaker: "left" | "right" | "both" — in the flank layout the line appears
  // beside whoever it is about.
  // "lead" is the part that can be dropped when the stage is narrow ("Machamp used ").
  function say(lead, text, speaker) {
    if (!caption) return;
    var box = caption.parentElement;
    root.dataset.speaker = speaker || "both";
    caption.textContent = "";
    if (lead) {
      var who = document.createElement("i");
      who.textContent = lead;
      caption.appendChild(who);
    }
    caption.appendChild(document.createTextNode(text));
    box.classList.remove("is-on");
    void box.offsetWidth;
    box.classList.add("is-on");
  }

  function pickMove(f) {
    var hits = f.moves.filter(function (m) { return m.damage > 0; });
    if (hits.length) return hits[Math.floor(Math.random() * hits.length)];
    if (f.moves.length) return { name: f.moves[0].name, damage: 20 };
    return { name: "Tackle", damage: 20 };
  }

  // Card rules, simplified: weakness and resistance are read off the defender's
  // card. A floor keeps a fight from dragging on when damage is tiny next to HP.
  function resolve(move, atk, def) {
    var dmg = move.damage;
    var note = "";
    var hit = function (list) {
      for (var i = 0; i < list.length; i++) {
        if (String(list[i].type || "").toLowerCase() === atk.type) return String(list[i].value || "");
      }
      return null;
    };
    var w = hit(def.weak);
    var r = hit(def.resist);
    if (w != null) {
      dmg = /[×x*]/i.test(w) ? dmg * (num(w) || 2) : dmg + num(w);
      note = "weak";
    } else if (r != null) {
      dmg = Math.max(0, dmg - (num(r) || 20));
      note = "resist";
    }
    var floor = Math.ceil((def.maxHp * 0.18) / 10) * 10;
    if (note !== "resist") dmg = Math.max(dmg, floor);
    else dmg = Math.max(dmg, 10);
    return { dmg: dmg, note: note };
  }

  function other(side) {
    return side === "left" ? "right" : "left";
  }

  function canPlay() {
    if (!root || root.hidden || reducedMotion || document.hidden) return false;
    if (document.querySelector(".modal-back")) return false;
    if (mode() === "stage" && !stageOnScreen) return false;
    return true;
  }

  function clearAttackClasses() {
    ["left", "right"].forEach(function (s) {
      el[s].flank.classList.remove("is-attacking", "is-hit", "is-windup");
    });
    root.classList.remove("is-firing-left", "is-firing-right");
  }

  function turn() {
    if (!running) return;
    if (!canPlay()) {
      later(turn, 900);
      return;
    }
    var side = nextSide;
    var foe = other(side);
    var atk = fighters[side];
    var def = fighters[foe];
    if (!atk || !def) return;
    var move = pickMove(atk);
    var out = resolve(move, atk, def);

    clearAttackClasses();
    void root.offsetWidth;
    say(isJa ? atk.name + "の " : atk.name + " used ", isJa ? move.name + "！" : move.name, side);
    root.dataset.atkKind = atk.kind;
    root.style.setProperty("--lp-atk", TYPE_COLOR[atk.kind]);
    root.style.setProperty("--lp-atk2", TYPE_LIGHT[atk.kind]);
    el[side].flank.classList.add("is-windup");

    later(function () {
      el[side].flank.classList.remove("is-windup");
      el[side].flank.classList.add("is-attacking");
      root.classList.add("is-firing-" + side);
    }, 380);

    later(function () {
      def.hp = Math.max(0, def.hp - out.dmg);
      el[foe].flank.classList.add("is-hit");
      paintHp(foe, false);
      var d = el[foe].dmg;
      d.textContent = "−" + out.dmg;
      d.dataset.note = out.note;
      d.classList.remove("is-on");
      void d.offsetWidth;
      d.classList.add("is-on");
    }, 380 + 430);

    later(function () {
      clearAttackClasses();
      if (def.hp <= 0) knockOut(side, foe);
      else {
        nextSide = foe;
        later(turn, TURN_MS - 1500);
      }
    }, 1500);
  }

  function knockOut(winnerSide, loserSide) {
    var winner = fighters[winnerSide];
    var loser = fighters[loserSide];
    el[loserSide].flank.classList.add("is-fainted");
    el[winnerSide].flank.classList.add("is-winner");
    say("", isJa ? loser.name + "は たおれた！" : loser.name + " fainted", loserSide);
    winner.wins += 1;

    later(function () {
      el[winnerSide].flank.classList.remove("is-winner");
      var avoid = [winner.dex, loser.dex];
      seat(loserSide, nextFighter(avoid));
      if (winner.wins >= MAX_WINS) {
        // Champion steps down so the same Pokémon doesn't hold the stage forever.
        seat(winnerSide, nextFighter([fighters[loserSide].dex, winner.dex]));
      } else {
        winner.hp = Math.min(winner.maxHp, winner.hp + Math.round(winner.maxHp * 0.5));
        paintHp(winnerSide, false);
      }
      say("", fighters.left.name + " vs " + fighters.right.name);
      nextSide = loserSide; // the newcomer gets the first move
      later(turn, 1500);
    }, KO_PAUSE_MS);
  }

  function startFight() {
    stopFight();
    if (reducedMotion || roster.length < 2) return;
    running = true;
    var a = nextFighter([]);
    var b = nextFighter([a.dex]);
    seat("left", a);
    seat("right", b);
    say("", a.name + " vs " + b.name);
    nextSide = Math.random() < 0.5 ? "left" : "right";
    later(turn, 1700);
  }

  function stopFight() {
    running = false;
    clearTimers();
    if (root) clearAttackClasses();
  }

  function hide() {
    stopFight();
    if (root) root.hidden = true;
    var h = host();
    if (h) h.removeAttribute("data-lp-arena");
    activeKey = null;
    loadingKey = null;
    roster = [];
    if (tileIO) { tileIO.disconnect(); tileIO = null; }
    if (heroRO) { heroRO.disconnect(); heroRO = null; }
    if (stageIO) { stageIO.disconnect(); stageIO = null; }
  }

  function watchVisibleCards() {
    if (tileIO) tileIO.disconnect();
    visibleKeys = [];
    var tiles = document.querySelectorAll(".card-tile");
    if (!tiles.length || typeof IntersectionObserver === "undefined") return;
    tileIO = new IntersectionObserver(
      function (entries) {
        var next = new Set(visibleKeys);
        entries.forEach(function (en) {
          var id = en.target.getAttribute("data-flip-id") || "";
          var nameEl = en.target.querySelector("strong");
          var key = id || (nameEl ? nameEl.textContent.trim().toLowerCase() : "");
          if (!key) return;
          if (en.isIntersecting) next.add(key);
          else next.delete(key);
        });
        visibleKeys = Array.from(next);
      },
      { threshold: 0.35 }
    );
    tiles.forEach(function (t) { tileIO.observe(t); });
  }

  function showForSet(info) {
    ensureDom();
    placeRoot();
    if (reducedMotion) { hide(); return; }
    var key = (info.isJa ? "ja:" : "en:") + info.id;
    if (activeKey === key && roster.length >= 2) {
      root.hidden = false;
      measureStage();
      return;
    }
    if (deadKeys.has(key) || loadingKey === key) return;
    activeKey = key;
    loadingKey = key;
    isJa = info.isJa;
    (info.isJa ? loadJaRoster(info.id) : loadEnCards(info.id))
      .then(function (list) {
        if (activeKey !== key) return; // navigated away while loading
        loadingKey = null;
        if (list.length < 2) { deadKeys.add(key); hide(); return; }
        // Stable shuffle per set: revisits feel familiar, but it isn't always #1 vs #2.
        var seed = 0;
        for (var i = 0; i < info.id.length; i++) seed = (seed * 31 + info.id.charCodeAt(i)) >>> 0;
        roster = list
          .map(function (r) { return { r: r, k: (seed ^ Math.imul(r.dex, 2654435761)) >>> 0 }; })
          .sort(function (a, b) { return a.k - b.k; })
          .map(function (x) { return x.r; });
        cursor = 0;
        placeRoot();
        root.hidden = false;
        measureStage();
        watchLayout();
        watchVisibleCards();
        later(watchVisibleCards, 600);
        later(watchVisibleCards, 1800);
        startFight();
      })
      .catch(function (e) {
        console.warn("[lp-battle] roster failed", e);
        deadKeys.add(key);
        hide();
      });
  }

  function sync() {
    var path = location.pathname;
    if (path === lastPath && root && !root.hidden) return;
    lastPath = path;
    var info = pathInfo(path);
    if (!info || !host()) { hide(); return; }
    showForSet(info);
  }

  function boot() {
    var mqReduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    reducedMotion = mqReduce.matches;
    mqReduce.addEventListener("change", function (e) {
      reducedMotion = e.matches;
      lastPath = "";
      sync();
    });
    mqFlank = window.matchMedia(FLANK_QUERY);
    mqFlank.addEventListener("change", measureStage);
    window.addEventListener("resize", measureStage);

    ensureDom();
    var wrap = function (fn) {
      return function () {
        var r = fn.apply(this, arguments);
        queueMicrotask(sync);
        return r;
      };
    };
    history.pushState = wrap(history.pushState);
    history.replaceState = wrap(history.replaceState);
    window.addEventListener("popstate", function () { queueMicrotask(sync); });

    new MutationObserver(function () {
      var onSet = !!host();
      if (onSet) placeRoot();
      var info = pathInfo(location.pathname);
      var key = info ? (info.isJa ? "ja:" : "en:") + info.id : null;
      if (info && onSet && (root.hidden || activeKey !== key)) sync();
      else if (!onSet && root && !root.hidden) hide();
    }).observe(document.documentElement, { childList: true, subtree: true });

    setTimeout(sync, 50);
    setTimeout(sync, 400);
    setTimeout(sync, 1200);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
