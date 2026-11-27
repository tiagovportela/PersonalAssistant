// The wiki site's behaviour: search, the graph (a small force layout, no library) and the kind filters.
// Data comes from data/*.js, which set window.PWI_*. Text from the store only ever goes in through
// textContent and setAttribute, never innerHTML, so nothing in it can become markup.
(function () {
  "use strict";
  var body = document.body;
  var root = body.getAttribute("data-root") || "";
  var current = body.getAttribute("data-page") || "";
  var SVG = "http://www.w3.org/2000/svg";

  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function pageUrl(id, section) {
    return root + "pages/" + encodeURIComponent(id) + ".html" + (section ? "#" + encodeURIComponent(section) : "");
  }
  function fold(text) {
    return String(text || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  // Search: every word must appear; title and heading matches rank first.
  var box = document.getElementById("search");
  var results = document.getElementById("results");
  var index = (window.PWI_SEARCH || []).map(function (e) {
    return { entry: e, head: fold(e.title + " " + e.heading), all: fold(e.title + " " + e.heading + " " + e.text) };
  });
  function search() {
    var words = fold(box.value).split(/\s+/).filter(Boolean);
    while (results.firstChild) results.removeChild(results.firstChild);
    if (!words.length) { results.hidden = true; return; }
    var hits = index.filter(function (i) {
      return words.every(function (w) { return i.all.indexOf(w) >= 0; });
    }).map(function (i) {
      var score = words.reduce(function (s, w) { return s + (i.head.indexOf(w) >= 0 ? 3 : 1); }, 0);
      return { i: i, score: score };
    }).sort(function (a, b) { return b.score - a.score; }).slice(0, 20);
    if (!hits.length) results.appendChild(el("p", { "class": "empty" }, "Nothing found."));
    hits.forEach(function (h) {
      var e = h.i.entry;
      var link = el("a", { href: pageUrl(e.page, e.section) });
      link.appendChild(el("strong", {}, e.title));
      if (e.section) link.appendChild(el("span", { "class": "meta" }, " · " + e.heading));
      var at = fold(e.text).indexOf(words[0]);
      var snippet = at < 0 ? e.text.slice(0, 140) : (at > 40 ? "…" : "") + e.text.slice(Math.max(0, at - 40), at + 100) + "…";
      link.appendChild(el("span", { "class": "snippet" }, snippet));
      results.appendChild(link);
    });
    results.hidden = false;
  }
  if (box) {
    box.addEventListener("input", search);
    box.addEventListener("keydown", function (e) { if (e.key === "Escape") { box.value = ""; search(); } });
  }

  // The graph ----------------------------------------------------------------------------------------
  var svg = document.getElementById("graph");
  var data = window.PWI_GRAPH || { nodes: [], edges: [] };
  if (!svg || !data.nodes.length) return;
  var nodes = data.nodes, edges = data.edges;
  if (current) {  // a page's own graph: it and its neighbours
    var near = {};
    near[current] = true;
    edges.forEach(function (e) {
      if (e.from === current) near[e.to] = true;
      if (e.to === current) near[e.from] = true;
    });
    nodes = nodes.filter(function (n) { return near[n.id]; });
    edges = edges.filter(function (e) { return near[e.from] && near[e.to]; });
    if (nodes.length < 2) { svg.parentNode.hidden = true; return; }
  }
  var W = 900, H = current ? 360 : 620;
  svg.setAttribute("viewBox", "0 0 " + W + " " + H);
  var byId = {};
  // Start on a circle, in a fixed order, so the same data always gives the same picture.
  nodes.forEach(function (n, k) {
    var a = 2 * Math.PI * k / nodes.length;
    byId[n.id] = { n: n, x: W / 2 + Math.cos(a) * W / 4, y: H / 2 + Math.sin(a) * H / 4, vx: 0, vy: 0, links: [] };
  });
  edges = edges.filter(function (e) { return byId[e.from] && byId[e.to]; });
  edges.forEach(function (e) { byId[e.from].links.push(e.to); byId[e.to].links.push(e.from); });
  var all = Object.keys(byId).map(function (k) { return byId[k]; });
  // Fruchterman-Reingold: the ideal distance comes from the area each page gets, so the same rules suit three
  // pages or three hundred; a little gravity keeps unlinked pages from drifting to the edges.
  var k = Math.sqrt(W * H / all.length) * 0.75;
  // Gravity sized so the pages' combined push balances inside a circle that fits the frame.
  var R = Math.min(W, H) / 2.05, g = 0.36 * W * H / (0.64 * R * R);
  for (var step = 0; step < 300; step++) {
    var limit = (W / 8) * (1 - step / 300) + 1;
    all.forEach(function (p) { p.vx = 0; p.vy = 0; });
    for (var i = 0; i < all.length; i++) {
      for (var j = i + 1; j < all.length; j++) {
        var a = all[i], b = all[j], dx = a.x - b.x, dy = a.y - b.y, d = Math.sqrt(dx * dx + dy * dy) + 0.01;
        var f = k * k / d;
        a.vx += dx / d * f; a.vy += dy / d * f; b.vx -= dx / d * f; b.vy -= dy / d * f;
      }
    }
    edges.forEach(function (e) {
      var a = byId[e.from], b = byId[e.to], dx = a.x - b.x, dy = a.y - b.y, d = Math.sqrt(dx * dx + dy * dy) + 0.01;
      var f = d * d / k;
      a.vx -= dx / d * f; a.vy -= dy / d * f; b.vx += dx / d * f; b.vy += dy / d * f;
    });
    all.forEach(function (p) {
      p.vx += (W / 2 - p.x) * g; p.vy += (H / 2 - p.y) * g;
      var v = Math.sqrt(p.vx * p.vx + p.vy * p.vy) + 0.01, move = Math.min(v, limit);
      p.x = Math.min(W - 60, Math.max(20, p.x + p.vx / v * move));
      p.y = Math.min(H - 16, Math.max(16, p.y + p.vy / v * move));
    });
  }
  var lines = document.createElementNS(SVG, "g"), dots = document.createElementNS(SVG, "g");
  svg.appendChild(lines); svg.appendChild(dots);
  edges.forEach(function (e) {
    var line = document.createElementNS(SVG, "line");
    var a = byId[e.from], b = byId[e.to];
    line.setAttribute("x1", a.x.toFixed(1)); line.setAttribute("y1", a.y.toFixed(1));
    line.setAttribute("x2", b.x.toFixed(1)); line.setAttribute("y2", b.y.toFixed(1));
    line.setAttribute("data-from", e.from); line.setAttribute("data-to", e.to);
    lines.appendChild(line);
  });
  all.forEach(function (p) {
    var g = document.createElementNS(SVG, "a");
    g.setAttribute("href", pageUrl(p.n.id));
    g.setAttribute("class", "node " + p.n.kind + (p.n.id === current ? " here" : "") + (p.n.stale ? " stale" : "")
                   + (p.n.compiled ? "" : " unwritten"));
    g.setAttribute("data-node", p.n.id);
    g.setAttribute("data-kind", p.n.kind);
    var c = document.createElementNS(SVG, "circle");
    c.setAttribute("cx", p.x.toFixed(1)); c.setAttribute("cy", p.y.toFixed(1));
    c.setAttribute("r", String(Math.min(16, 6 + p.links.length * 1.5)));
    var t = document.createElementNS(SVG, "text");
    t.setAttribute("x", (p.x + 10).toFixed(1)); t.setAttribute("y", (p.y + 4).toFixed(1));
    t.textContent = p.n.title;
    var tip = document.createElementNS(SVG, "title");
    tip.textContent = p.n.title + " (" + p.n.kind + (p.n.stale ? ", stale" : "") + (p.n.compiled ? "" : ", not written yet") + ")";
    g.appendChild(tip); g.appendChild(c); g.appendChild(t);
    g.addEventListener("mouseenter", function () { focus(p.n.id); });
    g.addEventListener("mouseleave", function () { focus(null); });
    dots.appendChild(g);
  });
  function focus(id) {
    svg.classList.toggle("focused", !!id);
    var near = {};
    if (id) { near[id] = true; byId[id].links.forEach(function (k) { near[k] = true; }); }
    dots.querySelectorAll(".node").forEach(function (g) { g.classList.toggle("near", !!near[g.getAttribute("data-node")]); });
    lines.querySelectorAll("line").forEach(function (l) {
      l.classList.toggle("near", !!id && (l.getAttribute("data-from") === id || l.getAttribute("data-to") === id));
    });
  }
  document.querySelectorAll(".kind-filter").forEach(function (box) {
    box.addEventListener("change", function () {
      var kind = box.value, show = box.checked;
      dots.querySelectorAll('.node[data-kind="' + kind + '"]').forEach(function (g) { g.classList.toggle("hidden", !show); });
      document.querySelectorAll('.catalog li[data-kind="' + kind + '"]').forEach(function (li) { li.hidden = !show; });
      lines.querySelectorAll("line").forEach(function (l) {
        var from = byId[l.getAttribute("data-from")].n.kind, to = byId[l.getAttribute("data-to")].n.kind;
        var hidden = [from, to].some(function (k) {
          var f = document.querySelector('.kind-filter[value="' + k + '"]');
          return f && !f.checked;
        });
        l.classList.toggle("hidden", hidden);
      });
    });
  });
  svg.setAttribute("data-ready", String(all.length));
})();
