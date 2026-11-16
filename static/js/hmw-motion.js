/* Motion-graphics player for "How Models Work" walkthroughs.
 *
 * Each <div class="hmw-motion" data-spec="{json}"> holds a scene produced by
 * content/walkthroughs/hmw_motion.py: SVG primitives plus per-attribute
 * keyframes. This file only interpolates and draws - every number on screen
 * was computed in the notebook.
 *
 * Plays when scrolled into view, pauses when scrolled away, loops with a short
 * hold on the last frame, and does not autoplay under prefers-reduced-motion.
 */
(function () {
    'use strict';

    var NS = 'http://www.w3.org/2000/svg';
    var MONO = "'Cascadia Code', Consolas, 'SFMono-Regular', Menlo, monospace";
    var SANS = "Inter, 'Segoe UI', system-ui, -apple-system, sans-serif";
    var END_HOLD = 1.4;   // seconds the last frame stays up before looping

    var EASE = {
        lin:   function (t) { return t; },
        'in':  function (t) { return t * t * t; },
        out:   function (t) { var u = 1 - t; return 1 - u * u * u; },
        inout: function (t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; },
        back:  function (t) { var c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); }
    };

    function hexToRgb(h) {
        return [parseInt(h.substr(1, 2), 16), parseInt(h.substr(3, 2), 16), parseInt(h.substr(5, 2), 16)];
    }
    function isHex(v) { return typeof v === 'string' && v.length === 7 && v.charAt(0) === '#'; }

    function lerp(a, b, t) {
        if (typeof a === 'number' && typeof b === 'number') return a + (b - a) * t;
        if (isHex(a) && isHex(b)) {
            var ca = hexToRgb(a), cb = hexToRgb(b), out = '#';
            for (var i = 0; i < 3; i++) {
                var c = Math.round(ca[i] + (cb[i] - ca[i]) * t);
                out += (c < 16 ? '0' : '') + c.toString(16);
            }
            return out;
        }
        if (Array.isArray(a) && Array.isArray(b) && a.length === b.length) {
            var r = new Array(a.length);
            for (var j = 0; j < a.length; j++) r[j] = a[j] + (b[j] - a[j]) * t;
            return r;
        }
        return t < 1 ? a : b;
    }

    /* Per-attribute tracks: {attr: [[t, value, ease], ...]} sorted by time. */
    function buildTracks(el) {
        var tracks = {};
        (el.k || []).forEach(function (key) {
            var t = key[0], attrs = key[1], ease = key[2];
            Object.keys(attrs).forEach(function (p) {
                (tracks[p] = tracks[p] || []).push([t, attrs[p], ease]);
            });
        });
        Object.keys(tracks).forEach(function (p) {
            tracks[p].sort(function (x, y) { return x[0] - y[0]; });
        });
        return tracks;
    }

    function valueAt(base, track, T) {
        if (!track) return base;
        var i = -1;
        for (var n = 0; n < track.length; n++) {
            if (track[n][0] <= T) i = n; else break;
        }
        var prevT = i < 0 ? 0 : track[i][0];
        var prevV = i < 0 ? base : track[i][1];
        var next = track[i + 1];
        if (!next || next[2] === 'step' || prevV === undefined) {
            return prevV === undefined ? next && next[1] : prevV;
        }
        var span = next[0] - prevT;
        if (span <= 0) return next[1];
        var u = Math.min(1, Math.max(0, (T - prevT) / span));
        return lerp(prevV, next[1], (EASE[next[2]] || EASE.inout)(u));
    }

    function mk(tag, parent) {
        var n = document.createElementNS(NS, tag);
        parent.appendChild(n);
        return n;
    }

    function setPaint(node, a) {
        if (a.fill !== undefined) node.setAttribute('fill', a.fill);
        if (a.stroke !== undefined) node.setAttribute('stroke', a.stroke);
        if (a.sw !== undefined) node.setAttribute('stroke-width', a.sw);
        if (a.dash !== undefined) node.setAttribute('stroke-dasharray', a.dash);
        node.setAttribute('opacity', a.opacity === undefined ? 1 : Math.max(0, Math.min(1, a.opacity)));
    }

    function arrowGeom(x1, y1, x2, y2, head) {
        var dx = x2 - x1, dy = y2 - y1, L = Math.sqrt(dx * dx + dy * dy);
        if (L < 1e-6) return null;
        var ux = dx / L, uy = dy / L, h = Math.min(head, L * 0.6), w = h * 0.55;
        var bx = x2 - ux * h, by = y2 - uy * h;
        return {
            lx2: bx + ux * 0.5, ly2: by + uy * 0.5,
            pts: x2 + ',' + y2 + ' ' + (bx - uy * w) + ',' + (by + ux * w) + ' ' + (bx + uy * w) + ',' + (by - ux * w)
        };
    }

    /* Make the SVG node(s) for an element and return a draw(attrs) function. */
    function makeDrawer(kind, svg) {
        var node, ln, hd;
        switch (kind) {
        case 'circle':
            node = mk('circle', svg);
            return function (a) {
                node.setAttribute('cx', a.cx); node.setAttribute('cy', a.cy);
                node.setAttribute('r', Math.max(0, a.r)); setPaint(node, a);
            };
        case 'rect':
            node = mk('rect', svg);
            return function (a) {
                node.setAttribute('x', a.x); node.setAttribute('y', a.y);
                node.setAttribute('width', Math.max(0, a.w)); node.setAttribute('height', Math.max(0, a.h));
                node.setAttribute('rx', a.rx || 0); setPaint(node, a);
            };
        case 'line':
            node = mk('line', svg);
            node.setAttribute('stroke-linecap', 'round');
            return function (a) {
                node.setAttribute('x1', a.x1); node.setAttribute('y1', a.y1);
                node.setAttribute('x2', a.x2); node.setAttribute('y2', a.y2); setPaint(node, a);
            };
        case 'arrow':
        case 'polar':
            node = mk('g', svg); ln = mk('line', node); hd = mk('polygon', node);
            ln.setAttribute('stroke-linecap', 'round');
            return function (a) {
                var x1, y1, x2, y2;
                if (kind === 'polar') {
                    var r = a.ang * Math.PI / 180;
                    x1 = a.cx; y1 = a.cy; x2 = a.cx + a.len * Math.cos(r); y2 = a.cy - a.len * Math.sin(r);
                } else { x1 = a.x1; y1 = a.y1; x2 = a.x2; y2 = a.y2; }
                var g = arrowGeom(x1, y1, x2, y2, a.head || 10);
                node.setAttribute('opacity', a.opacity === undefined ? 1 : Math.max(0, Math.min(1, a.opacity)));
                if (!g) { node.setAttribute('visibility', 'hidden'); return; }
                node.setAttribute('visibility', 'visible');
                ln.setAttribute('x1', x1); ln.setAttribute('y1', y1);
                ln.setAttribute('x2', g.lx2); ln.setAttribute('y2', g.ly2);
                ln.setAttribute('stroke', a.stroke); ln.setAttribute('stroke-width', a.sw);
                if (a.dash !== undefined) ln.setAttribute('stroke-dasharray', a.dash);
                hd.setAttribute('points', g.pts); hd.setAttribute('fill', a.stroke);
            };
        case 'poly':
            node = mk('path', svg);
            node.setAttribute('stroke-linejoin', 'round'); node.setAttribute('stroke-linecap', 'round');
            return function (a) {
                var p = a.pts, d = '';
                for (var i = 0; i + 1 < p.length; i += 2) d += (i ? 'L' : 'M') + p[i].toFixed(1) + ' ' + p[i + 1].toFixed(1);
                if (a.closed) d += 'Z';
                node.setAttribute('d', d || 'M0 0'); setPaint(node, a);
            };
        case 'arc':
            node = mk('path', svg); node.setAttribute('fill', 'none');
            node.setAttribute('stroke-linecap', 'round');
            return function (a) {
                var r0 = a.a0 * Math.PI / 180, r1 = a.a1 * Math.PI / 180;
                var x0 = a.cx + a.r * Math.cos(r0), y0 = a.cy - a.r * Math.sin(r0);
                var x1 = a.cx + a.r * Math.cos(r1), y1 = a.cy - a.r * Math.sin(r1);
                var large = Math.abs(a.a1 - a.a0) > 180 ? 1 : 0, sweep = a.a1 > a.a0 ? 0 : 1;
                node.setAttribute('d', 'M' + x0 + ' ' + y0 + ' A' + a.r + ' ' + a.r + ' 0 ' + large + ' ' + sweep + ' ' + x1 + ' ' + y1);
                setPaint(node, { stroke: a.stroke, sw: a.sw, dash: a.dash, opacity: a.opacity });
            };
        case 'text':
        case 'num':
            node = mk('text', svg);
            node.setAttribute('dominant-baseline', 'middle');
            return function (a) {
                node.setAttribute('x', a.x); node.setAttribute('y', a.y);
                node.setAttribute('font-size', a.size); node.setAttribute('text-anchor', a.anchor || 'middle');
                node.setAttribute('font-weight', a.weight || 400);
                node.setAttribute('font-family', a.mono ? MONO : SANS);
                if (a.rot) node.setAttribute('transform', 'rotate(' + (-a.rot) + ' ' + a.x + ' ' + a.y + ')');
                setPaint(node, { fill: a.fill, opacity: a.opacity });
                var s = a.s;
                if (kind === 'num') {
                    var body = a.sep
                        ? Number(a.v).toLocaleString('en-US', { minimumFractionDigits: a.dec, maximumFractionDigits: a.dec })
                        : Number(a.v).toFixed(a.dec);
                    s = (a.pre || '') + body + (a.post || '');
                }
                if (s === '-0.00' || s === '-0.0' || s === '-0') s = s.substr(1);
                if (node.textContent !== s) node.textContent = s;
            };
        }
        return function () {};
    }

    function fmtTime(t) { return t.toFixed(1) + 's'; }

    function Player(root) {
        var spec;
        try { spec = JSON.parse(root.getAttribute('data-spec')); } catch (e) { return; }
        root.removeAttribute('data-spec');

        var stage = document.createElement('div'); stage.className = 'hmw-motion-stage';
        var svg = document.createElementNS(NS, 'svg');
        svg.setAttribute('viewBox', '0 0 ' + spec.w + ' ' + spec.h);
        svg.setAttribute('role', 'img');
        if (spec.caption) svg.setAttribute('aria-label', spec.caption);
        var bg = mk('rect', svg);
        bg.setAttribute('width', spec.w); bg.setAttribute('height', spec.h); bg.setAttribute('fill', '#0f1226');
        stage.appendChild(svg);

        var beat = document.createElement('div'); beat.className = 'hmw-motion-beat';
        var bar = document.createElement('div'); bar.className = 'hmw-motion-bar';
        var btn = document.createElement('button'); btn.type = 'button'; btn.className = 'hmw-motion-btn';
        var range = document.createElement('input'); range.type = 'range'; range.min = 0; range.max = 1000; range.value = 0;
        range.className = 'hmw-motion-range'; range.setAttribute('aria-label', 'Animation position');
        var clock = document.createElement('span'); clock.className = 'hmw-motion-clock';
        bar.appendChild(btn); bar.appendChild(range); bar.appendChild(clock);

        root.appendChild(stage); root.appendChild(beat); root.appendChild(bar);
        if (spec.caption) {
            var cap = document.createElement('div'); cap.className = 'hmw-motion-caption';
            cap.textContent = spec.caption; root.appendChild(cap);
        }

        var items = spec.els.map(function (el) {
            return { base: el.a, tracks: buildTracks(el), draw: makeDrawer(el.t, svg) };
        });
        var beats = spec.beats || [];
        var dur = spec.dur;

        var T = 0, playing = false, last = null, hold = 0, inView = false, userPaused = false;

        function render(t) {
            items.forEach(function (it) {
                var a = {};
                Object.keys(it.base).forEach(function (p) { a[p] = valueAt(it.base[p], it.tracks[p], t); });
                Object.keys(it.tracks).forEach(function (p) {
                    if (!(p in a)) a[p] = valueAt(undefined, it.tracks[p], t);
                });
                it.draw(a);
            });
            var b = '';
            for (var i = 0; i < beats.length; i++) { if (beats[i][0] <= t + 1e-6) b = beats[i][1]; }
            if (beat.textContent !== b) beat.textContent = b;
            beat.style.visibility = b ? 'visible' : 'hidden';
            range.value = Math.round(1000 * t / dur);
            clock.textContent = fmtTime(t) + ' / ' + fmtTime(dur);
        }

        function setBtn() {
            btn.textContent = playing ? '❚❚' : '▶';
            btn.setAttribute('aria-label', playing ? 'Pause' : 'Play');
        }

        function frame(now) {
            if (!playing) { last = null; return; }
            if (last === null) last = now;
            var dt = Math.min(0.1, (now - last) / 1000);
            last = now;
            if (T >= dur) {
                hold += dt;
                if (hold >= END_HOLD) {
                    if (spec.loop) { T = 0; hold = 0; } else { playing = false; setBtn(); return; }
                }
            } else {
                T = Math.min(dur, T + dt);
            }
            render(T);
            requestAnimationFrame(frame);
        }

        function play() {
            if (playing) return;
            if (T >= dur) { T = 0; hold = 0; }
            playing = true; last = null; setBtn(); requestAnimationFrame(frame);
        }
        function pause() { playing = false; setBtn(); }

        btn.addEventListener('click', function () {
            if (playing) { pause(); userPaused = true; } else { userPaused = false; play(); }
        });
        svg.addEventListener('click', function () { btn.click(); });
        range.addEventListener('input', function () {
            T = dur * range.value / 1000; hold = 0; render(T);
        });
        range.addEventListener('pointerdown', function () { if (playing) { pause(); userPaused = true; } });

        var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        T = reduce ? (spec.poster !== undefined ? spec.poster : dur) : 0;
        render(T); setBtn();

        if (!reduce && 'IntersectionObserver' in window) {
            new IntersectionObserver(function (entries) {
                entries.forEach(function (e) {
                    inView = e.isIntersecting;
                    if (inView && !userPaused) play();
                    else if (!inView) pause();
                });
            }, { threshold: 0.45 }).observe(root);
        }
    }

    function init() {
        var nodes = document.querySelectorAll('.hmw-motion[data-spec]');
        for (var i = 0; i < nodes.length; i++) Player(nodes[i]);
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
