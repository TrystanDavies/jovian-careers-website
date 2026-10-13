/* Colossal Cave: the windows.
 *
 * The game itself runs in Python; this script draws the panes and plays the
 * part of a VT-100 on the end of a serial line. Text arrives one character at
 * a time at the chosen baud rate (about baud / 10 characters a second).
 * Enter or Esc while text is arriving shows the rest at once.
 */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var screen = $("screen"), input = $("cmd"), crt = $("crt");

  var view = null;
  var words = [];
  var mapRegion = null;
  var lastRegion = null;
  var history = [], histPos = 0;
  var stick = true;
  var sending = Promise.resolve();

  // ------------------------------------------------------------ serial line

  var queue = [];          // [{text, cls, node, i}]
  var printing = false;
  var budget = 0, lastTick = 0;
  var baud = 2400;

  function enqueue(text, cls) {
    queue.push({ text: text, cls: cls || "", node: null, i: 0 });
    if (!printing) {
      printing = true;
      lastTick = performance.now();
      budget = 0;
      requestAnimationFrame(tick);
    }
  }

  function nodeFor(seg) {
    if (!seg.node) {
      var span = document.createElement("span");
      if (seg.cls) span.className = seg.cls;
      seg.node = document.createTextNode("");
      span.appendChild(seg.node);
      screen.appendChild(span);
    }
    return seg.node;
  }

  function tick(now) {
    var cps = baud > 0 ? baud / 10 : Infinity;
    budget += (now - lastTick) * cps / 1000;
    lastTick = now;
    while (queue.length && budget >= 1) {
      var seg = queue[0];
      var n = Math.min(seg.text.length - seg.i, Math.floor(budget));
      nodeFor(seg).appendData(seg.text.substr(seg.i, n));
      seg.i += n;
      budget -= n;
      if (seg.i >= seg.text.length) queue.shift();
    }
    if (budget > 4) budget = 4;
    scrollDown();
    if (queue.length) requestAnimationFrame(tick);
    else printing = false;
  }

  function flush() {
    while (queue.length) {
      var seg = queue.shift();
      nodeFor(seg).appendData(seg.text.substr(seg.i));
    }
    budget = 0;
    scrollDown();
  }

  function scrollDown() {
    if (stick) screen.scrollTop = screen.scrollHeight;
  }

  screen.addEventListener("scroll", function () {
    stick = screen.scrollHeight - screen.scrollTop - screen.clientHeight < 40;
  });

  function printLines(lines) {
    var roomName = view && view.lit ? view.room.name : null;
    lines.forEach(function (para) {
      if (roomName && para.indexOf(roomName + "\n") === 0) {
        enqueue(roomName + "\n", "bright");
        para = para.slice(roomName.length + 1);
      }
      enqueue(para + "\n\n");
    });
    // Keep the screen from growing without end.
    while (screen.childNodes.length > 1500) screen.removeChild(screen.firstChild);
  }

  // ------------------------------------------------------------ talking to Python

  function api(path, body) {
    var opts = body === undefined ? {} : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    };
    return fetch(path, opts).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  function send(text, echo) {
    sending = sending.then(function () {
      flush();
      stick = true;
      enqueue("> " + (echo || text) + "\n", "echo");
      flush();
      return api("/api/command", { text: text }).then(function (data) {
        render(data.view);
        printLines(data.lines);
        return data;
      }).catch(function () {
        enqueue("NO CARRIER\n\n(The game server isn't answering. Is play.py still running?)\n\n", "dim");
      });
    });
    return sending;
  }

  // ------------------------------------------------------------ the windows

  function render(v) {
    view = v;
    baud = v.baud;
    renderStatus(v);
    renderScene(v);
    renderMap(v);
    renderCompass(v);
    renderItinerary(v);
    renderInventory(v);
  }

  function pad(s, n) { s = String(s); while (s.length < n) s = " " + s; return s; }

  function renderStatus(v) {
    var lamp = !v.lamp.present ? "NO LAMP" : (v.lamp.on ? "LAMP ON " : "LAMP OFF") + pad(v.lamp.power, 5);
    var parts = [
      "SCORE " + pad(v.score, 3) + "/" + v.max_score,
      "TURNS " + pad(v.turns, 4),
      lamp,
      v.baud ? v.baud + " BAUD" : "LOCAL"
    ];
    $("status").innerHTML = parts.map(function (p) { return "<span>" + p + "</span>"; }).join("");
    $("baud-caption").textContent = v.baud ? v.baud + " baud" : "no delay";
    $("baud").value = String(v.baud);
  }

  function renderScene(v) {
    $("scene").innerHTML = v.scene;
    $("scene-caption").textContent = v.room.name;
  }

  function renderMap(v) {
    if (v.room.region !== lastRegion) {
      mapRegion = v.room.region;
      lastRegion = v.room.region;
    }
    if (!v.map.svg[mapRegion]) mapRegion = v.room.region;
    var tabs = $("map-tabs");
    tabs.innerHTML = "";
    v.map.regions.forEach(function (r) {
      var b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", r.id === mapRegion ? "true" : "false");
      b.textContent = r.name;
      b.addEventListener("click", function () { mapRegion = r.id; renderMap(view); });
      tabs.appendChild(b);
    });
    var box = $("map");
    box.innerHTML = v.map.svg[mapRegion] || "";
    var svg = box.querySelector("svg");
    if (svg) {
      // Never shrink the map below a readable size: scroll instead, centred on you.
      var vb = svg.viewBox.baseVal;
      var phone = window.matchMedia("(max-width: 900px)").matches;
      var fitW = (box.clientWidth - 12) / vb.width;
      var fit = phone ? fitW : Math.min(fitW, (box.clientHeight - 12) / vb.height);
      var minScale = phone ? 0.62 : 0.72;
      if (fit < minScale) {
        var scale = phone ? Math.max(fitW, minScale) : minScale;
        svg.style.width = (vb.width * scale) + "px";
        svg.style.height = (vb.height * scale) + "px";
        svg.style.flex = "none";
        var here = svg.querySelector('[data-room="' + v.room.id + '"] rect');
        if (here) {
          var bb = here.getBBox();
          box.scrollLeft = Math.max(0, (bb.x + bb.width / 2) * scale - box.clientWidth / 2);
          box.scrollTop = Math.max(0, (bb.y + bb.height / 2) * scale - box.clientHeight / 2);
        }
      }
    }
    var name = v.map.regions.filter(function (r) { return r.id === mapRegion; })[0];
    $("map-caption").textContent = (name ? name.name : "") + (mapRegion === v.room.region ? "" : " (you are elsewhere)");
  }

  $("map").addEventListener("click", function (e) {
    var room = e.target.closest("[data-room]");
    if (room) {
      if (view && room.getAttribute("data-room") === view.room.id) { send("look"); return; }
      send("go to " + room.getAttribute("data-room"), "go to " + room.getAttribute("data-label").toLowerCase());
      return;
    }
    var portal = e.target.closest("[data-region]");
    if (portal && view.map.svg[portal.getAttribute("data-region")]) {
      mapRegion = portal.getAttribute("data-region");
      renderMap(view);
    }
  });

  function renderCompass(v) {
    var open = {};
    v.exits.forEach(function (x) { open[x.dir] = x; });
    Array.prototype.forEach.call(document.querySelectorAll("#compass [data-dir]"), function (b) {
      var x = open[b.getAttribute("data-dir")];
      b.disabled = !x || v.game_over;
      b.title = x ? (x.name + (x.to ? " to " + x.to : "")) : "";
    });
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  var GLYPH = { unknown: "·", seen: "◇", carried: "◆", stored: "★", lost: "✕" };

  function renderItinerary(v) {
    $("itin-caption").textContent = "stored " + v.stored + " of 15";
    var known = v.treasures.filter(function (t) { return t.status !== "unknown"; });
    var unknown = v.treasures.length - known.length;
    $("treasures").innerHTML = known.map(function (t) {
      return '<span class="t ' + t.status + '" title="' + t.status + '"><span class="g">' +
        GLYPH[t.status] + "</span>" + esc(t.name) + "</span>";
    }).join("") + (unknown ? '<span class="t more"><span class="g">' + GLYPH.unknown + "</span>" +
      (known.length ? unknown + " more treasures to find" : "15 treasures to find. None seen yet.") + "</span>" : "");
    var log = $("log");
    log.innerHTML = v.log.map(function (e) {
      return '<li class="' + e.kind + '"><span class="when">T' + e.t + '</span><span class="what">' +
        esc(e.text) + "</span></li>";
    }).join("");
    log.scrollTop = log.scrollHeight;
  }

  function renderInventory(v) {
    var power = Math.max(0, Math.min(100, v.lamp.power / 12));
    var hearts = "";
    for (var i = 0; i < 3; i++) hearts += i < v.lives ? "♥" : "♡";
    $("meters").innerHTML =
      '<span class="m"><b>Score</b> ' + v.score + "/" + v.max_score + "</span>" +
      '<span class="m"><b>Turns</b> ' + v.turns + "</span>" +
      '<span class="m"><b>Lamp</b><span class="bar' + (v.lamp.power < 150 ? " low" : "") +
      '"><i style="width:' + power.toFixed(0) + '%"></i></span></span>' +
      '<span class="m"><b>Lives</b> <span class="lives">' + hearts + "</span></span>";
    $("inv-caption").textContent = v.inventory.length ? v.inventory.length + " of 10 carried" : "empty-handed";
    var items = $("items");
    if (!v.inventory.length) {
      items.innerHTML = '<li class="empty">You are carrying nothing.</li>';
      return;
    }
    items.innerHTML = v.inventory.map(function (it) {
      return '<li class="' + (it.treasure ? "treasure" : "") + '"><button type="button" data-noun="' +
        esc(it.noun) + '" title="Examine">' + (it.treasure ? "★ " : "") + esc(it.name) + "</button></li>";
    }).join("");
  }

  $("items").addEventListener("click", function (e) {
    var b = e.target.closest("[data-noun]");
    if (b) send("examine " + b.getAttribute("data-noun"));
  });

  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-cmd], [data-dir]");
    if (!b || b.closest("#map") || b.closest("#items")) return;
    send(b.getAttribute("data-cmd") || b.getAttribute("data-dir"));
  });

  Array.prototype.forEach.call(document.querySelectorAll(".titlebar .min"), function (b) {
    b.addEventListener("click", function () {
      var win = b.closest(".win");
      win.classList.toggle("collapsed");
      b.innerHTML = win.classList.contains("collapsed") ? "+" : "&ndash;";
    });
  });

  $("baud").addEventListener("change", function () { send("baud " + this.value); });

  $("new-game").addEventListener("click", function () {
    if (!window.confirm("Start a new game? Your current adventure will be lost (unless you've saved it).")) return;
    send("restart").then(function (data) {
      if (data && data.view && data.view.pending === "restart") {
        screen.innerHTML = "";
        send("yes");
      }
    });
  });

  // ------------------------------------------------------------ the keyboard

  function updateMirror() {
    var v = input.value, p = input.selectionStart == null ? v.length : input.selectionStart;
    $("m-before").textContent = v.slice(0, p);
    $("m-cursor").textContent = v.charAt(p) || " ";
    $("m-after").textContent = v.slice(p + 1);
  }

  var tabState = null;

  function complete() {
    var v = input.value;
    var m = /([a-z]*)$/i.exec(v);
    var stem = (tabState ? tabState.stem : m[1]).toLowerCase();
    if (!stem) return;
    var hits = words.filter(function (w) { return w.indexOf(stem) === 0; });
    if (!hits.length) return;
    if (!tabState) tabState = { stem: stem, i: -1, base: v.slice(0, v.length - m[1].length) };
    tabState.i = (tabState.i + 1) % hits.length;
    input.value = tabState.base + hits[tabState.i];
    input.setSelectionRange(input.value.length, input.value.length);
  }

  input.addEventListener("keydown", function (e) {
    if (e.key !== "Tab") tabState = null;
    if (e.key === "Enter") {
      e.preventDefault();
      var text = input.value.trim();
      if (printing) flush();
      if (!text) { updateMirror(); return; }
      history.push(text);
      if (history.length > 100) history.shift();
      histPos = history.length;
      input.value = "";
      updateMirror();
      send(text);
    } else if (e.key === "Escape") {
      flush();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (histPos > 0) { histPos--; input.value = history[histPos]; }
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (histPos < history.length) { histPos++; input.value = history[histPos] || ""; }
    } else if (e.key === "Tab") {
      e.preventDefault();
      complete();
    }
    requestAnimationFrame(updateMirror);
  });
  ["input", "click", "keyup", "select"].forEach(function (ev) { input.addEventListener(ev, updateMirror); });
  input.addEventListener("focus", function () { crt.classList.add("focused"); });
  input.addEventListener("blur", function () { crt.classList.remove("focused"); });

  crt.addEventListener("mouseup", function () {
    var sel = window.getSelection ? String(window.getSelection()) : "";
    if (!sel) input.focus();
  });

  // ------------------------------------------------------------ dialling in

  api("/api/state").then(function (data) {
    words = data.words || [];
    render(data.view);
    var rate = data.view.baud || 9600;
    ["ATZ", "OK", "ATDT 0161 555 1887", "CONNECT " + rate, ""].forEach(function (l, i) {
      enqueue(l + "\n", i < 4 ? "dim" : "");
    });
    printLines(data.lines);
    if (window.matchMedia("(min-width: 901px)").matches) input.focus();
    updateMirror();
  }).catch(function () {
    enqueue("NO CARRIER\n\nCan't reach the game. Start it with: python3 adventure/play.py\n", "dim");
  });
})();
