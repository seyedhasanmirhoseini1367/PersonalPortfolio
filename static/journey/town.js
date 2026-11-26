/* LearningJourney town (prototype): a top-down Finnish town built from Kenney's CC0 Tiny Town tiles.
   Walk around, talk to people, answer in Finnish, earn coins and stars.
   Data: #town-data (journey/town.py). Art: tiny_town.png (places) and tiny_dungeon.png (people). */
(function () {
    'use strict';
    const CFG = JSON.parse(document.getElementById('town-data').textContent);
    const URLS = window.TOWN_URLS;
    const T = 16, W = 36, H = 26;
    const KEY = 'lj-town-' + URLS.user;
    const $ = id => document.getElementById(id);

    // ── saved progress (this browser) ────────────────────────────────────────
    let pushTimer;
    const save = (() => {
        let s = {};
        try { s = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { s = {}; }
        s.done = s.done || {};
        s.coins = s.coins || 0;
        return {
            get: () => s,
            put: () => {
                try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) { /* private mode */ }
                clearTimeout(pushTimer);
                pushTimer = setTimeout(() => fetch(URLS.state, {method: 'POST', body: JSON.stringify(s),
                    headers: {'X-CSRFToken': URLS.csrf, 'Content-Type': 'application/json'}}).catch(() => {}), 600);
            },
            merge: server => {   // the best of this browser and the server
                s.coins = Math.max(s.coins || 0, server.coins || 0);
                Object.entries(server.done || {}).forEach(([k, v]) => { s.done[k] = Math.max(s.done[k] || 0, v); });
                if (!s.sprite && server.sprite) s.sprite = server.sprite;
            },
        };
    })();

    // ── the map ──────────────────────────────────────────────────────────────
    const rnd = (() => { let x = 7; return () => (x = (x * 16807) % 2147483647) / 2147483647; })();
    const ground = [];
    for (let y = 0; y < H; y++) {
        ground.push([]);
        for (let x = 0; x < W; x++) {
            const r = rnd();
            ground[y].push(r < 0.08 ? 1 : r < 0.11 ? 2 : 0);
        }
    }
    const objects = [];          // {x, y, sheet, frame, depth}
    const blocked = new Set();   // "x,y" tiles nobody can walk through
    const put = (x, y, frame, opts = {}) => {
        objects.push({x, y, frame, sheet: opts.sheet || 'town', depth: opts.depth !== undefined ? opts.depth : (y + 1) * T});
        if (opts.block !== false) blocked.add(x + ',' + y);
    };
    const path = (x, y) => { ground[y][x] = 43; };

    // Streets: a main street, a cross street and a square in the middle.
    for (let x = 2; x <= 33; x++) path(x, 13);
    for (let y = 4; y <= 23; y++) path(17, y);
    for (let y = 11; y <= 15; y++) for (let x = 15; x <= 19; x++) path(x, y);

    // Forest around the edge.
    const trees = [16, 28, 4, 27, 16, 5];
    for (let x = 0; x < W; x++) for (const y of [0, 1, H - 2, H - 1]) put(x, y, trees[(x + y) % trees.length]);
    for (let y = 2; y < H - 2; y++) for (const x of [0, 1, W - 2, W - 1]) put(x, y, trees[(x * 3 + y) % trees.length]);

    // A building: roof rows, then a wall row with the door. Doors face the street (south).
    const doors = {};
    function building(key, x, y, rows, doorCol) {
        const bottom = y + rows.length - 1;
        rows.forEach((row, r) => row.forEach((f, c) => put(x + c, y + r, f, {depth: (bottom + 1) * T})));
        doors[key] = {x: x + doorCol, y: bottom + 1};
        for (let yy = bottom + 1; yy < 13; yy++) path(x + doorCol, yy);
    }
    building('cafe', 4, 6, [[52, 53, 53, 54], [64, 65, 67, 66], [72, 84, 74, 75]], 2);
    building('home', 10, 7, [[48, 49, 50], [60, 63, 62], [88, 89, 91]], 1);
    building('station', 24, 5, [[48, 49, 55, 49, 50], [60, 61, 61, 61, 62], [76, 88, 78, 90, 79]], 2);

    // Market: stalls with crates, barrels and baskets, fenced on the north side.
    for (let x = 4; x <= 11; x++) put(x, 16, [44, 45, 45, 45, 45, 45, 45, 46][x - 4]);
    [[5, 18, 63, 'people'], [6, 18, 75, 'people'], [9, 18, 82, 'people'], [10, 18, 63, 'people'],
     [5, 20, 107, 'town'], [10, 20, 131, 'town'], [7, 21, 130, 'town']].forEach(([x, y, f, s]) => put(x, y, f, {sheet: s}));
    put(4, 15, 83);  // market sign
    for (let y = 14; y <= 19; y++) path(8, y);
    doors.market = {x: 8, y: 19};

    // Park and square details.
    put(17, 12, 104);                                   // well in the square
    [[22, 18], [24, 21], [29, 19], [31, 16], [27, 22], [21, 21]].forEach(([x, y], i) => put(x, y, [16, 28, 5][i % 3]));
    [[25, 17], [28, 17], [23, 20], [30, 21], [26, 20]].forEach(([x, y]) => { ground[y][x] = 2; });
    [[13, 9], [14, 9]].forEach(([x, y]) => put(x, y, 94));   // beehives by the home
    put(16, 9, 83);   // signpost
    [[20, 6], [21, 9], [31, 9], [3, 10], [14, 4], [8, 4]].forEach(([x, y], i) => put(x, y, [28, 16, 4][i % 3]));

    // People: places first, then people around the square.
    const SQUARE_SPOTS = [[20, 15], [14, 11], [23, 12], [12, 15]];
    const npcs = CFG.places.map(p => ({...p, tile: {x: doors[p.key].x, y: doors[p.key].y + (p.key === 'market' ? 0 : 0)}}))
        .concat(CFG.square.map((p, i) => ({...p, tile: {x: SQUARE_SPOTS[i][0], y: SQUARE_SPOTS[i][1]}})));
    npcs.forEach(n => blocked.add(n.tile.x + ',' + n.tile.y));

    // ── UI helpers ───────────────────────────────────────────────────────────
    const sheetImages = {};
    function loadImage(name, url) {
        return new Promise(res => { const im = new Image(); im.onload = () => { sheetImages[name] = im; res(); }; im.src = url; });
    }
    function drawFrame(canvas, sheet, frame) {
        const ctx = canvas.getContext('2d');
        ctx.imageSmoothingEnabled = false;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        const sx = (frame % 12) * 16, sy = Math.floor(frame / 12) * 16;
        ctx.drawImage(sheetImages[sheet], sx, sy, 16, 16, 0, 0, canvas.width, canvas.height);
    }
    let toastTimer;
    function toast(html, ms = 2600) {
        const t = $('tw-toast');
        t.innerHTML = html;
        t.hidden = false;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => { t.hidden = true; }, ms);
    }
    let soundOn = false;
    function speak(text) {
        if (!soundOn || !('speechSynthesis' in window)) return;
        speechSynthesis.cancel();
        const u = new SpeechSynthesisUtterance(text);
        u.lang = 'fi-FI';
        u.rate = 0.9;
        const v = speechSynthesis.getVoices().find(v => (v.lang || '').toLowerCase().startsWith('fi'));
        if (v) u.voice = v;
        speechSynthesis.speak(u);
    }
    function setCoins(n) { save.get().coins = n; save.put(); $('tw-coins').textContent = n; }

    function questList() {
        const ul = $('tw-quest-list');
        ul.innerHTML = '';
        const target = nextTarget();
        npcs.forEach(n => {
            const li = document.createElement('li');
            const done = save.get().done[questKey(n)];
            li.className = (done ? 'done' : '') + (target === n ? ' target' : '');
            li.innerHTML = `<i>${done ? '✓' : '○'}</i><span><b></b> <small></small></span>`;
            li.querySelector('b').textContent = n.fi;
            li.querySelector('small').textContent = n.scene.title + (n.from_lesson ? ' · your lesson' : '');
            li.addEventListener('click', () => { chosenTarget = n; questList(); });
            ul.appendChild(li);
        });
    }
    const questKey = n => (n.scene.id ? 'scene' + n.scene.id : 'starter-' + n.key);
    let chosenTarget = null;
    function nextTarget() {
        if (chosenTarget && !save.get().done[questKey(chosenTarget)]) return chosenTarget;
        return npcs.find(n => !save.get().done[questKey(n)]) || null;
    }

    // ── dialogue ─────────────────────────────────────────────────────────────
    let talking = null;
    function openDialogue(npc) {
        talking = {npc, i: 0, points: 0, coins: 0, missed: [], tries: 0, shownAt: 0, streak: 0};
        $('tw-dialog').hidden = false;
        $('tw-talk').hidden = true;
        $('tw-npc-name').textContent = npc.scene.npc_name || npc.fi;
        $('tw-npc-role').textContent = npc.scene.npc_role || '';
        $('tw-dialog-meta').textContent = npc.scene.title;
        drawFrame($('tw-portrait'), 'people', npc.frame);
        step();
    }
    function closeDialogue() {
        $('tw-dialog').hidden = true;
        talking = null;
    }
    function lineHTML(fi, en, mine) {
        const box = $('tw-line');
        box.innerHTML = '';
        const t = document.createElement('span');
        t.lang = 'fi';
        t.textContent = (mine ? 'You: ' : '') + fi;
        box.appendChild(t);
        if (en) {
            const e = document.createElement('span');
            e.className = 'en';
            e.textContent = en;
            e.hidden = true;
            box.appendChild(e);
            return e;
        }
        return null;
    }
    function button(label, cls, onClick) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = cls;
        if (typeof label === 'string') b.textContent = label; else b.append(...label);
        b.addEventListener('click', onClick);
        return b;
    }
    function step() {
        const d = talking, steps = d.npc.scene.steps, acts = $('tw-actions');
        acts.innerHTML = '';
        if (d.i >= steps.length) return finishDialogue();
        const s = steps[d.i];
        if (s.who === 'npc') {
            const en = lineHTML(s.fi, s.en, false);
            speak(s.fi);
            const row = document.createElement('div');
            row.className = 'tw-row';
            if (en) row.appendChild(button('Show English', 'tw-link', e => { en.hidden = !en.hidden; e.target.textContent = en.hidden ? 'Show English' : 'Hide English'; }));
            row.appendChild(button('Continue ▸', 'tw-btn on tw-next', () => { d.i++; step(); }));
            acts.appendChild(row);
            acts.querySelector('.tw-next').focus({preventScroll: true});
            return;
        }
        // The learner's turn: three replies, one right.
        $('tw-line').innerHTML = '<span class="tw-small">Your reply:</span>';
        d.tries = 0;
        d.shownAt = performance.now();
        s.options.forEach((o, n) => {
            const k = document.createElement('kbd'); k.textContent = n + 1;
            const t = document.createElement('span'); t.textContent = o; t.lang = 'fi';
            acts.appendChild(button([k, t], 'tw-opt', e => answer(n, e.currentTarget, s)));
        });
    }
    function answer(n, btn, s) {
        const d = talking;
        if (!d || btn.disabled) return;
        d.tries++;
        if (n === s.answer) {
            const secs = (performance.now() - d.shownAt) / 1000;
            const first = d.tries === 1;
            const speed = first ? Math.max(0, Math.round(50 - Math.max(0, secs - 4) * 3.5)) : 0;
            d.points += (first ? 100 : d.tries === 2 ? 40 : 0) + speed;
            const coins = first ? 10 : d.tries === 2 ? 4 : 0;
            d.coins += coins;
            d.streak = first ? d.streak + 1 : 0;
            btn.classList.add('right');
            [...$('tw-actions').children].forEach(b => { b.disabled = true; });
            speak(s.fi);
            if (coins) toast(`+${coins} 🪙${d.streak >= 2 ? ` · ${d.streak} in a row` : ''}`, 1200);
            setTimeout(() => {
                const en = lineHTML(s.fi, s.en, true);
                if (en) en.hidden = false;
                const acts = $('tw-actions');
                acts.innerHTML = '';
                acts.appendChild(button('Continue ▸', 'tw-btn on tw-next', () => { d.i++; step(); }));
                acts.querySelector('.tw-next').focus({preventScroll: true});
            }, 450);
        } else {
            btn.classList.add('wrong');
            btn.disabled = true;
            if (!d.missed.includes(d.i)) d.missed.push(d.i);
            if (d.tries >= 2) [...$('tw-actions').children][s.answer].classList.add('right');
        }
    }
    async function finishDialogue() {
        const d = talking, scene = d.npc.scene;
        const turns = scene.steps.filter(s => s.who === 'you').length;
        const ratio = turns ? d.points / (turns * 150) : 0;
        let stars = ratio >= 0.85 ? 3 : ratio >= 0.55 ? 2 : ratio > 0 ? 1 : 0;
        let added = 0;
        if (scene.id) {   // a scene from the learner's own lesson: save the result, missed words go to review
            const body = new URLSearchParams({score: d.points});
            d.missed.forEach(m => body.append('missed', m));
            try {
                const r = await (await fetch(URLS.finish.replace('/0/', '/' + scene.id + '/'),
                    {method: 'POST', body, headers: {'X-CSRFToken': URLS.csrf}})).json();
                stars = r.stars; added = r.added || 0;
            } catch (e) { /* offline: keep the local result */ }
        }
        const firstTime = !save.get().done[questKey(d.npc)];
        const bonus = firstTime ? stars * 5 : 0;
        save.get().done[questKey(d.npc)] = Math.max(stars, save.get().done[questKey(d.npc)] || 0);
        setCoins(save.get().coins + d.coins + bonus);
        questList();
        const acts = $('tw-actions');
        $('tw-line').innerHTML = '';
        const st = document.createElement('div');
        st.className = 'tw-stars';
        for (let i = 1; i <= 3; i++) { const s = document.createElement('span'); s.textContent = '★'; if (i > stars) s.className = 'off'; st.appendChild(s); }
        $('tw-line').appendChild(st);
        acts.innerHTML = '';
        const msg = document.createElement('div');
        msg.className = 'tw-small';
        msg.textContent = `${d.points} points · +${d.coins + bonus} coins${bonus ? ' (incl. quest bonus)' : ''}` +
            (added ? ` · ${added} word${added === 1 ? '' : 's'} added to today’s review` : '') +
            (d.missed.length ? '' : ' · no mistakes, hienoa!');
        acts.appendChild(msg);
        const row = document.createElement('div');
        row.className = 'tw-row';
        row.appendChild(button('Talk again', 'tw-btn', () => openDialogue(d.npc)));
        row.appendChild(button('Done', 'tw-btn on tw-next', closeDialogue));
        acts.appendChild(row);
        acts.querySelector('.tw-next').focus({preventScroll: true});
        game.events.emit('quest-done', d.npc);
    }
    document.addEventListener('keydown', e => {
        if (!talking) return;
        const n = parseInt(e.key, 10);
        const opts = [...document.querySelectorAll('#tw-actions .tw-opt')];
        if (n >= 1 && n <= opts.length) { opts[n - 1].click(); e.preventDefault(); }
        if (e.key === 'Escape') closeDialogue();
    });

    // ── touch joystick (phones) ──────────────────────────────────────────────
    const stick = {active: false, id: null, ox: 0, oy: 0, dx: 0, dy: 0};
    const wrap = $('tw');
    wrap.addEventListener('pointerdown', e => {
        if (e.pointerType === 'mouse' || talking || e.target.closest('.tw-hud,.tw-dialog,.tw-modal,.tw-talk')) return;
        const r = wrap.getBoundingClientRect();
        Object.assign(stick, {active: true, id: e.pointerId, ox: e.clientX - r.left, oy: e.clientY - r.top, dx: 0, dy: 0});
        const s = $('tw-stick');
        s.style.left = stick.ox + 'px'; s.style.top = stick.oy + 'px'; s.hidden = false;
        $('tw-stick-knob').style.transform = '';
    });
    wrap.addEventListener('pointermove', e => {
        if (!stick.active || e.pointerId !== stick.id) return;
        const r = wrap.getBoundingClientRect();
        let dx = e.clientX - r.left - stick.ox, dy = e.clientY - r.top - stick.oy;
        const len = Math.hypot(dx, dy), max = 40;
        if (len > max) { dx = dx / len * max; dy = dy / len * max; }
        stick.dx = dx / max; stick.dy = dy / max;
        $('tw-stick-knob').style.transform = `translate(${dx}px, ${dy}px)`;
    });
    const endStick = e => { if (e.pointerId === stick.id) { stick.active = false; stick.dx = stick.dy = 0; $('tw-stick').hidden = true; } };
    wrap.addEventListener('pointerup', endStick);
    wrap.addEventListener('pointercancel', endStick);

    // ── the game scene ───────────────────────────────────────────────────────
    let nearest = null;
    const TOUCH = window.matchMedia('(pointer: coarse)').matches;
    class Town extends Phaser.Scene {
        constructor() { super('town'); }
        preload() {
            this.load.spritesheet('town', URLS.town, {frameWidth: 16, frameHeight: 16});
            this.load.spritesheet('people', URLS.people, {frameWidth: 16, frameHeight: 16});
        }
        create() {
            $('tw-loading').hidden = true;
            const rt = this.add.renderTexture(0, 0, W * T, H * T).setOrigin(0).setDepth(0);
            for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) rt.drawFrame('town', ground[y][x], x * T, y * T);
            objects.forEach(o => this.add.image(o.x * T, o.y * T, o.sheet, o.frame).setOrigin(0).setDepth(o.depth));

            this.walls = this.physics.add.staticGroup();
            blocked.forEach(k => {
                const [x, y] = k.split(',').map(Number);
                const z = this.add.zone(x * T + T / 2, y * T + T / 2 + 3, T, T - 6);
                this.physics.add.existing(z, true);
                this.walls.add(z);
            });
            this.physics.world.setBounds(0, 0, W * T, H * T);

            // Places: name boards above the doors.
            const label = (text, x, y) => this.add.text(x, y, text, {
                fontFamily: 'Inter, system-ui, sans-serif', fontSize: '7px', fontStyle: 'bold', color: '#ffffff',
                stroke: '#14202b', strokeThickness: 3, resolution: 6,
            }).setOrigin(0.5, 1).setDepth(5000);

            // People.
            this.people = npcs.map(n => {
                const x = n.tile.x * T + T / 2, y = n.tile.y * T + T;
                const spr = this.add.image(x, y, 'people', n.frame).setOrigin(0.5, 1).setDepth(y);
                label(n.scene.npc_name || n.fi, x, y - 17).setFontSize(6).setAlpha(0.9);
                const mark = this.add.text(x, y - 24, '!', {fontFamily: 'Inter, sans-serif', fontSize: '10px', fontStyle: 'bold',
                    color: '#f2c14e', stroke: '#14202b', strokeThickness: 3, resolution: 6}).setOrigin(0.5, 1).setDepth(5001);
                this.tweens.add({targets: mark, y: y - 27, duration: 600, yoyo: true, repeat: -1, ease: 'Sine.inOut'});
                const place = CFG.places.find(p => p.key === n.key);
                if (place) label(n.fi.toUpperCase(), x, (n.tile.y - 3) * T + 3);
                return {npc: n, spr, mark, x, y};
            });
            this.refreshMarks();
            game.events.on('quest-done', () => this.refreshMarks());

            // The player: an invisible physics body at the feet, and the sprite that follows it.
            const pick = save.get().sprite || CFG.player_choices[0];
            this.body = this.physics.add.image(17 * T + 8, 16 * T + 8, 'people', pick).setVisible(false);
            this.body.body.setSize(9, 6).setOffset(3.5, 10);
            this.body.setCollideWorldBounds(true);
            this.physics.add.collider(this.body, this.walls);
            this.hero = this.add.image(this.body.x, this.body.y, 'people', pick).setOrigin(0.5, 1);
            this.shadow = this.add.ellipse(this.body.x, this.body.y, 10, 3, 0x000000, 0.25);
            this.prompt = this.add.text(0, 0, 'E · Talk', {fontFamily: 'Inter, sans-serif', fontSize: '6px', fontStyle: 'bold',
                color: '#14202b', backgroundColor: '#f2c14e', padding: {x: 3, y: 1}, resolution: 6}).setOrigin(0.5, 1).setDepth(6000).setVisible(false);

            const cam = this.cameras.main;
            cam.setBounds(0, 0, W * T, H * T);
            cam.startFollow(this.hero, true, 0.12, 0.12);
            cam.setRoundPixels(true);
            this.fitZoom();
            this.scale.on('resize', () => this.fitZoom());

            this.keys = this.input.keyboard.addKeys('W,A,S,D,UP,DOWN,LEFT,RIGHT,E,SPACE,ENTER');
            this.input.keyboard.on('keydown', e => {
                if (talking || !$('tw-start').hidden) return;
                if (['e', 'E', ' ', 'Enter'].includes(e.key) && nearest) { e.preventDefault(); openDialogue(nearest.npc); }
            });
            this.walkTime = 0;
            this.peers = new Map();
            this.bubble = this.add.text(0, 0, '👋', {fontSize: '10px', resolution: 6}).setOrigin(0.5, 1).setDepth(7000).setVisible(false);
            this.input.keyboard.on('keydown-Q', () => { if (!talking) wave(); });
        }
        fitZoom() {
            const w = this.scale.width, h = this.scale.height;
            const z = Math.max(2, Math.min(4, Math.min(w / (20 * T), h / (13 * T))));
            this.cameras.main.setZoom(Math.round(z * 2) / 2);
        }
        refreshMarks() {
            this.people.forEach(p => {
                const done = save.get().done[questKey(p.npc)];
                p.mark.setText(done ? '✓' : '!').setColor(done ? '#5fd08a' : '#f2c14e');
            });
        }
        showPeers(list) {
            const seen = new Set();
            list.forEach(p => {
                seen.add(p.id);
                let v = this.peers.get(p.id);
                if (!v) {
                    const spr = this.add.image(p.x, p.y + 8, 'people', p.f).setOrigin(0.5, 1).setAlpha(0);
                    const tag = this.add.text(p.x, p.y - 10, p.name, {fontFamily: 'Inter, sans-serif', fontSize: '6px', fontStyle: 'bold',
                        color: '#ffffff', stroke: '#1f4d8f', strokeThickness: 3, resolution: 6}).setOrigin(0.5, 1).setDepth(5000);
                    const bubble = this.add.text(p.x, p.y - 18, '👋', {fontSize: '10px', resolution: 6}).setOrigin(0.5, 1).setDepth(7000).setVisible(false);
                    this.tweens.add({targets: spr, alpha: 1, duration: 300});
                    v = {spr, tag, bubble, x: p.x, y: p.y, walk: 0};
                    this.peers.set(p.id, v);
                    toast(`${p.name} is in town`, 1800);
                }
                Object.assign(v, {tx: p.x, ty: p.y, moving: p.moving, flip: p.flip, wave: p.emote_age !== null && p.emote_age < 2.5});
                v.spr.setFrame(p.f);
            });
            this.peers.forEach((v, id) => {
                if (!seen.has(id)) { v.spr.destroy(); v.tag.destroy(); v.bubble.destroy(); this.peers.delete(id); }
            });
            $('tw-online').textContent = this.peers.size ? `👥 ${this.peers.size} online` : '';
            $('tw-online').hidden = !this.peers.size;
        }
        movePeers(dt) {
            this.peers.forEach(v => {
                const k = Math.min(1, dt / 160);
                v.x += (v.tx - v.x) * k; v.y += (v.ty - v.y) * k;
                const moving = v.moving || Math.hypot(v.tx - v.x, v.ty - v.y) > 0.6;
                v.walk = moving ? v.walk + dt : 0;
                const bob = moving ? Math.abs(Math.sin(v.walk / 90)) * 1.6 : 0;
                v.spr.setPosition(Math.round(v.x), Math.round(v.y + 8 - bob)).setFlipX(v.flip).setDepth(v.y + 8)
                    .setAngle(moving ? Math.sin(v.walk / 90) * 4 : 0);
                v.tag.setPosition(Math.round(v.x), Math.round(v.y - 9));
                v.bubble.setPosition(Math.round(v.x), Math.round(v.y - 17)).setVisible(v.wave);
            });
        }
        update(_, dt) {
            this.movePeers(dt);
            this.bubble.setPosition(Math.round(this.body.x), Math.round(this.body.y - 17)).setVisible(performance.now() < waveUntil);
            const k = this.keys, b = this.body;
            let vx = 0, vy = 0;
            if (!talking && $('tw-start').hidden) {
                vx = (k.D.isDown || k.RIGHT.isDown ? 1 : 0) - (k.A.isDown || k.LEFT.isDown ? 1 : 0) + stick.dx;
                vy = (k.S.isDown || k.DOWN.isDown ? 1 : 0) - (k.W.isDown || k.UP.isDown ? 1 : 0) + stick.dy;
            }
            const len = Math.hypot(vx, vy);
            const speed = 78;
            if (len > 0.15) { vx = vx / Math.max(1, len) * speed; vy = vy / Math.max(1, len) * speed; } else { vx = vy = 0; }
            b.setVelocity(vx, vy);
            const moving = vx || vy;
            if (vx) this.hero.setFlipX(vx < 0);
            this.walkTime = moving ? this.walkTime + dt : 0;
            const bob = moving ? Math.abs(Math.sin(this.walkTime / 90)) * 1.6 : 0;
            this.hero.setPosition(Math.round(b.x), Math.round(b.y + 8 - bob));
            this.hero.setAngle(moving ? Math.sin(this.walkTime / 90) * 4 : 0);
            this.hero.setDepth(b.y + 8);
            this.shadow.setPosition(b.x, b.y + 8).setDepth(b.y + 7);

            // Who is close enough to talk to?
            let best = null, bestD = 22;
            this.people.forEach(p => {
                const d = Math.hypot(p.x - b.x, (p.y - 6) - b.y);
                if (d < bestD) { best = p; bestD = d; }
            });
            nearest = best;
            this.prompt.setVisible(!!best && !talking);
            if (best) this.prompt.setPosition(best.x, best.y - 30);
            const talk = $('tw-talk');
            talk.hidden = !TOUCH || !!talking || !$('tw-start').hidden;
            talk.classList.toggle('ready', !!best);
            talk.textContent = best ? 'Talk' : '·';

            // Arrow towards the next quest when it is off screen.
            const target = nextTarget(), arrow = $('tw-arrow');
            const cam = this.cameras.main, view = cam.worldView;
            if (target && !talking) {
                const p = this.people.find(q => q.npc === target);
                const onScreen = p.x > view.x && p.x < view.right && p.y - 16 > view.y && p.y < view.bottom;
                arrow.hidden = onScreen;
                if (!onScreen) {
                    const cx = (b.x - view.x) * cam.zoom, cy = (b.y - view.y) * cam.zoom;
                    const ang = Math.atan2(p.y - b.y, p.x - b.x);
                    const r = Math.min(this.scale.width, this.scale.height) / 2 - 40;
                    arrow.style.left = Math.max(30, Math.min(this.scale.width - 30, cx + Math.cos(ang) * r)) + 'px';
                    arrow.style.top = Math.max(90, Math.min(this.scale.height - 30, cy + Math.sin(ang) * r)) + 'px';
                    arrow.style.transform = `rotate(${ang}rad)`;
                }
            } else arrow.hidden = true;
        }
    }

    const game = new Phaser.Game({
        type: Phaser.AUTO,
        parent: 'tw',
        backgroundColor: '#7ec46b',
        pixelArt: true,
        physics: {default: 'arcade', arcade: {debug: false}},
        scale: {mode: Phaser.Scale.RESIZE, width: '100%', height: '100%'},
        scene: Town,
    });
    window.ljTown = game;   // handy when debugging in the console

    let waveUntil = 0, waveNext = false, lastSent = '', lastSentAt = 0;
    function wave() {
        waveUntil = performance.now() + 2500;
        waveNext = true;
    }
    async function presence() {
        const sc = game.scene.getScene('town');
        if (sc && sc.body && $('tw-start').hidden) {
            const b = sc.body, moving = !!(b.body.velocity.x || b.body.velocity.y);
            const msg = {x: Math.round(b.x * 10) / 10, y: Math.round(b.y * 10) / 10, f: save.get().sprite || CFG.player_choices[0],
                         flip: sc.hero.flipX, moving};
            const key = JSON.stringify(msg);
            const now = performance.now();
            if (key !== lastSent || waveNext || now - lastSentAt > 3000) {
                if (waveNext) msg.emote = 'wave';
                waveNext = false; lastSent = key; lastSentAt = now;
                try {
                    const r = await fetch(URLS.presence, {method: 'POST', body: JSON.stringify(msg),
                        headers: {'X-CSRFToken': URLS.csrf, 'Content-Type': 'application/json'}});
                    if (r.ok) sc.showPeers((await r.json()).peers || []);
                } catch (e) { /* offline for a moment */ }
            }
        }
        setTimeout(presence, document.hidden ? 4000 : 700);
    }
    presence();

    // ── start screen, buttons ────────────────────────────────────────────────
    const serverState = fetch(URLS.state).then(r => r.ok ? r.json() : {}).catch(() => ({}));
    Promise.all([loadImage('town', URLS.town), loadImage('people', URLS.people), serverState]).then(([, , server]) => {
        save.merge(server || {});
        save.put();
        drawFrame($('tw-coin-icon'), 'town', 93);
        setCoins(save.get().coins);
        questList();
        if (window.innerWidth < 700) $('tw-quests').open = false;   // small screens: fold the quest list
        const picks = $('tw-picks');
        let chosen = save.get().sprite || CFG.player_choices[0];
        CFG.player_choices.forEach(f => {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'tw-pick' + (f === chosen ? ' sel' : '');
            b.setAttribute('aria-label', 'Character ' + f);
            const c = document.createElement('canvas'); c.width = 48; c.height = 48;
            drawFrame(c, 'people', f);
            b.appendChild(c);
            b.addEventListener('click', () => {
                chosen = f;
                [...picks.children].forEach(x => x.classList.toggle('sel', x === b));
            });
            picks.appendChild(b);
        });
        $('tw-start').hidden = false;
        $('tw-go').addEventListener('click', () => {
            save.get().sprite = chosen; save.put();
            const sc = game.scene.getScene('town');
            if (sc && sc.hero) { sc.hero.setFrame(chosen); }
            $('tw-start').hidden = true;
        });
    });
    $('tw-talk').addEventListener('click', () => { if (nearest && !talking) openDialogue(nearest.npc); });
    $('tw-help').addEventListener('click', () => { $('tw-start').hidden = false; });
    $('tw-wave').addEventListener('click', () => { if (!talking) wave(); });
    $('tw-sound').addEventListener('click', e => {
        soundOn = !soundOn;
        e.currentTarget.textContent = soundOn ? '🔊' : '🔇';
        e.currentTarget.classList.toggle('on', soundOn);
        e.currentTarget.setAttribute('aria-pressed', String(soundOn));
        toast(soundOn ? 'Finnish lines are read aloud' : 'Sound off', 1400);
    });
})();
