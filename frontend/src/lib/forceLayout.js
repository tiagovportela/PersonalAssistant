// Places a graph's nodes in a W×H frame: Fruchterman–Reingold, deterministic, so the same pages always give the
// same picture. The ideal distance comes from the area each node gets, so the same rules suit three pages or three
// hundred; gravity sized so the nodes' combined push balances inside a circle that fits the frame.
export function forceLayout(nodes, edges, W, H) {
  const at = new Map();
  nodes.forEach((n, i) => {
    const a = (2 * Math.PI * i) / nodes.length;
    at.set(n.id, { id: n.id, x: W / 2 + (Math.cos(a) * W) / 4, y: H / 2 + (Math.sin(a) * H) / 4, vx: 0, vy: 0, degree: 0 });
  });
  const links = edges.filter((e) => at.has(e.from) && at.has(e.to) && e.from !== e.to);
  links.forEach((e) => { at.get(e.from).degree += 1; at.get(e.to).degree += 1; });
  const all = [...at.values()];
  if (all.length === 1) { all[0].x = W / 2; all[0].y = H / 2; }
  if (all.length < 2) return { points: at, links };
  const k = Math.sqrt((W * H) / all.length) * 0.75;
  const R = Math.min(W, H) / 2.05;
  const g = (0.36 * W * H) / (0.64 * R * R);
  for (let step = 0; step < 300; step++) {
    const limit = (W / 8) * (1 - step / 300) + 1;
    for (const p of all) { p.vx = 0; p.vy = 0; }
    for (let i = 0; i < all.length; i++) {
      for (let j = i + 1; j < all.length; j++) {
        const a = all[i], b = all[j], dx = a.x - b.x, dy = a.y - b.y, d = Math.hypot(dx, dy) + 0.01, f = (k * k) / d;
        a.vx += (dx / d) * f; a.vy += (dy / d) * f; b.vx -= (dx / d) * f; b.vy -= (dy / d) * f;
      }
    }
    for (const e of links) {
      const a = at.get(e.from), b = at.get(e.to), dx = a.x - b.x, dy = a.y - b.y, d = Math.hypot(dx, dy) + 0.01, f = (d * d) / k;
      a.vx -= (dx / d) * f; a.vy -= (dy / d) * f; b.vx += (dx / d) * f; b.vy += (dy / d) * f;
    }
    for (const p of all) {
      p.vx += (W / 2 - p.x) * g; p.vy += (H / 2 - p.y) * g;
      const v = Math.hypot(p.vx, p.vy) + 0.01, move = Math.min(v, limit);
      p.x = Math.min(W - 24, Math.max(24, p.x + (p.vx / v) * move));
      p.y = Math.min(H - 20, Math.max(20, p.y + (p.vy / v) * move));
    }
  }
  return { points: at, links };
}
