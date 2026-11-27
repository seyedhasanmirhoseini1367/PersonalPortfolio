/* LearningJourney town: a Phaser scene over a Tiled map, with the game interface in plain HTML on top.
 *
 * The game only draws and moves things. Everything that counts (answers, XP, coins, quests) is decided by the
 * server through the /learn/api/town/ endpoints, so nothing here can be used to earn rewards on its own.
 */
(() => {
    'use strict';
    const CFG = JSON.parse(document.getElementById('tw-config').textContent);
    const T = 16;                       // tile size in the map and the sprite sheet
    const SHEET_COLS = 27;
    // Each townsperson in the sheet: 4 columns (left, down, up, right) by 3 rows (stand, step, step).
    const PEOPLE = [23, 104, 185, 266, 347, 428];
    const DIR = {left: 0, down: 1, up: 2, right: 3};
    const SPEED = 64;                   // world pixels a second
    const $ = id => document.getElementById(id);
    const root = $('tw');
    const CALM = matchMedia('(prefers-reduced-motion: reduce)').matches;   // no typewriter, no fades

    // ── server ────────────────────────────────────────────────────────────
    async function post(url, data = {}) {
        const r = await fetch(url, {method: 'POST', headers: {'X-CSRFToken': CFG.csrf, 'Accept': 'application/json'},
                                    body: new URLSearchParams(data), credentials: 'same-origin'});
        const body = await r.json().catch(() => ({}));
        if (!r.ok) throw Object.assign(new Error(body.error || 'Request failed'), {status: r.status});
        return body;
    }
    const sceneUrl = (key, what) => CFG.scene.replace('KEY', key) + what + '/';
    let STATE = null;
    async function refresh() {
        STATE = await (await fetch(CFG.state, {headers: {'Accept': 'application/json'}, credentials: 'same-origin'})).json();
        drawHud();
        return STATE;
    }

    // ── sound: off until the learner turns it on ──────────────────────────
    const Sound = {
        on: (() => { try { return localStorage.getItem('tw-sound') === '1'; } catch (e) { return false; } })(),
        ctx: null,
        tone(freq, dur, type = 'square', vol = .05, when = 0) {
            if (!this.on) return;
            this.ctx = this.ctx || new (window.AudioContext || window.webkitAudioContext)();
            const t0 = this.ctx.currentTime + when, o = this.ctx.createOscillator(), g = this.ctx.createGain();
            o.type = type; o.frequency.value = freq;
            g.gain.setValueAtTime(vol, t0); g.gain.exponentialRampToValueAtTime(.0001, t0 + dur);
            o.connect(g).connect(this.ctx.destination); o.start(t0); o.stop(t0 + dur);
        },
        blip() { this.tone(660, .06); },
        open() { this.tone(523, .08); this.tone(784, .1, 'square', .05, .07); },
        right() { this.tone(659, .09, 'triangle', .08); this.tone(988, .14, 'triangle', .08, .08); },
        wrong() { this.tone(196, .18, 'sawtooth', .04); },
        done() { [523, 659, 784, 1047].forEach((f, i) => this.tone(f, .14, 'triangle', .07, i * .09)); },
    };
    function setSound(on) {
        Sound.on = on;
        try { localStorage.setItem('tw-sound', on ? '1' : '0'); } catch (e) { /* private mode */ }
        $('tw-sound').setAttribute('aria-pressed', String(on));
        $('tw-sound').setAttribute('aria-label', on ? 'Sound on' : 'Sound off');
        if (on) Sound.blip();
    }
    $('tw-sound').addEventListener('click', () => setSound(!Sound.on));
    setSound(Sound.on);

    // ── drawing people outside the canvas (HUD face, portraits, the picker) ──
    let SHEET = null;
    function drawPerson(canvas, who, dir = DIR.down) {
        if (!SHEET) return;
        const idx = PEOPLE[who] + dir, ctx = canvas.getContext('2d');
        ctx.imageSmoothingEnabled = false;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        const s = Math.floor(Math.min(canvas.width, canvas.height) / T);
        const off = (canvas.width - T * s) / 2;
        ctx.drawImage(SHEET, (idx % SHEET_COLS) * T, Math.floor(idx / SHEET_COLS) * T, T, T, off, off, T * s, T * s);
    }

    // ── heads-up display ──────────────────────────────────────────────────
    function drawHud() {
        if (!STATE) return;
        $('tw-name').textContent = STATE.name;
        $('tw-level').textContent = 'Level ' + STATE.me.level;
        $('tw-xp').style.width = STATE.me.pct + '%';
        $('tw-coins').textContent = STATE.me.coins;
        $('tw-streak').textContent = STATE.me.streak;
        $('tw-qdot').hidden = !STATE.quests.some(q => !q.done);
        if (STATE.sprite != null) drawPerson($('tw-me-face'), STATE.sprite);
    }
    let toastTimer = 0;
    function toast(text) {
        const t = $('tw-toast');
        t.textContent = text; t.hidden = false;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => { t.hidden = true; }, 2600);
    }

    // ── panels (only one open at a time; the game ignores input while one is open) ──
    let panel = null;
    function openPanel(el) {
        if (panel) panel.hidden = true;
        panel = el; el.hidden = false;
        $('tw-hint').classList.add('gone');
        Sound.open();
        const first = el.querySelector('button:not([disabled]), a');
        if (first) setTimeout(() => first.focus({preventScroll: true}), 30);
    }
    function closePanel() {
        if (!panel) return;
        panel.hidden = true; panel = null;
        root.focus({preventScroll: true});
    }
    root.addEventListener('click', e => { if (e.target.closest('[data-close]')) closePanel(); });
    document.addEventListener('keydown', e => {
        if (!panel) return;
        if (e.key === 'Escape' && panel !== $('tw-pick')) { closePanel(); return; }
        if (e.key === 'Tab') {   // keep keyboard focus inside the open panel
            const f = [...panel.querySelectorAll('button:not([disabled]), a[href]')].filter(el => el.offsetParent !== null);
            if (!f.length) return;
            const i = f.indexOf(document.activeElement);
            if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus(); }
            else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus(); }
        }
    });

    function showQuests() {
        const ul = $('tw-qlist');
        ul.innerHTML = '';
        if (!STATE.quests.length) {
            const li = document.createElement('li');
            li.textContent = 'Quests start once you have a published lesson to practise.';
            ul.append(li);
        }
        STATE.quests.forEach(q => {
            const li = document.createElement('li');
            if (q.done) li.className = 'done';
            const top = document.createElement('span'); top.className = 'top';
            const name = document.createElement('span'); name.textContent = q.title + (q.week ? ' (this week)' : '');
            const n = document.createElement('span'); n.textContent = q.done ? 'Done' : q.progress + ' / ' + q.target;
            top.append(name, n);
            const small = document.createElement('small'); small.textContent = q.detail + '  ·  +' + q.xp + ' XP, ' + q.coins + ' coins';
            const bar = document.createElement('span'); bar.className = 'tw-bar';
            const fill = document.createElement('i'); fill.style.width = Math.round(100 * q.progress / q.target) + '%';
            bar.append(fill);
            li.append(top, small, bar);
            ul.append(li);
        });
        openPanel($('tw-questpanel'));
    }
    $('tw-quests-btn').addEventListener('click', () => STATE && showQuests());

    const li = (cls, ...children) => { const el = document.createElement('li'); if (cls) el.className = cls; el.append(...children); return el; };
    const span = (cls, text) => { const el = document.createElement('span'); if (cls) el.className = cls; el.textContent = text; return el; };
    const link = (href, text) => { const a = document.createElement('a'); a.href = href; a.textContent = text; return a; };

    function showLessons() {
        const ul = $('tw-llist'); ul.innerHTML = '';
        if (!STATE.lessons.length) ul.append(li('', span('', 'No language lessons yet. Add your first one: photos, a PDF or typed text.')));
        STATE.lessons.forEach(l => {
            const top = span('top', ''); top.append(span('', l.title), span('', l.due ? l.due + ' due' : l.new ? l.new + ' new' : 'up to date'));
            const acts = span('acts', '');
            const here = document.createElement('button'); here.type = 'button'; here.textContent = 'Practise here';
            here.addEventListener('click', () => Drill.start(l));
            acts.append(here, link(l.practise, 'All practice modes'), link(l.open, 'Open'));
            ul.append(li('', top, span('', l.space + ' · ' + l.total + ' cards'), acts));
        });
        $('tw-l-review').href = STATE.links.review;
        $('tw-l-add').href = STATE.links.subjects;
        openPanel($('tw-lessons'));
    }

    function showHome() {
        drawPerson($('tw-home-face'), STATE.sprite ?? 0);
        const box = $('tw-hstats'); box.innerHTML = '';
        const card = (big, small) => { const d = document.createElement('div'); d.append(Object.assign(document.createElement('b'), {textContent: big}), span('', small)); box.append(d); };
        card('Lv ' + STATE.me.level, STATE.me.rank + ' · ' + STATE.me.into + ' / ' + STATE.me.span + ' XP');
        card(String(STATE.me.streak), 'days in a row');
        card(String(STATE.me.coins), 'coins');
        card(STATE.achievements.unlocked + '/' + STATE.achievements.total, 'achievements');
        $('tw-h-progress').href = STATE.links.progress;
        drawShop();
        openPanel($('tw-home'));
    }

    function drawShop() {
        const ul = $('tw-shop'); ul.innerHTML = '';
        STATE.shop.forEach(item => {
            const row = li(item.owned ? 'owned' : item.locked ? 'locked' : '');
            row.append(Object.assign(document.createElement('b'), {textContent: item.name}), Object.assign(document.createElement('small'), {textContent: item.desc}));
            if (item.owned) row.append(span('tag', 'In your town'));
            else {
                const b = document.createElement('button'); b.type = 'button';
                const coin = span('tw-coin', ''); coin.setAttribute('aria-hidden', 'true');
                b.append(coin, document.createTextNode(item.locked ? ' Level ' + item.level : ' ' + item.price));
                b.disabled = item.locked || !item.afford;
                b.setAttribute('aria-label', item.locked ? item.name + ': opens at level ' + item.level : 'Buy ' + item.name + ' for ' + item.price + ' coins');
                b.addEventListener('click', async () => {
                    b.disabled = true;
                    try {
                        const r = await post(CFG.buy, {item: item.code});
                        Sound.done(); toast(r.message);
                        await refresh();
                        GAME.scene.getScene('town').decorate(true);
                        drawShop();
                    } catch (e) { toast(e.message); b.disabled = false; }
                });
                row.append(b);
            }
            ul.append(row);
        });
    }
    $('tw-change').addEventListener('click', async () => {
        const who = await pickCharacter();
        const s = GAME && GAME.scene.getScene('town');
        if (s && s.player) { s.who = who; s.player.setFrame(PEOPLE[who] + DIR[s.facing]); }
    });

    function showPlaces() {
        const s = GAME.scene.getScene('town');
        const ul = $('tw-plist'); ul.innerHTML = '';
        s.places.forEach(p => {
            const info = (STATE.places || {})[p.key] || {};
            const b = document.createElement('button'); b.type = 'button';
            if (info.locked) b.className = 'locked';
            b.append(Object.assign(document.createElement('b'), {textContent: p.title}), Object.assign(document.createElement('small'), {textContent: p.subtitle}));
            if (info.locked) b.append(span('tag', 'Opens at level ' + info.level));
            else if (info.done_today) b.append(span('tag done', 'Rewarded today'));
            b.addEventListener('click', () => { closePanel(); s.walkTo(Math.floor(p.x / T), Math.floor(p.y / T)); });
            ul.append(li('', b));
        });
        openPanel($('tw-places'));
    }
    $('tw-map-btn').addEventListener('click', () => GAME && STATE && showPlaces());

    // ── a conversation ────────────────────────────────────────────────────
    const Talk = {
        key: null, data: null, turn: 0, busy: false, typing: 0,
        async start(key) {
            this.key = key;
            try { this.data = await post(sceneUrl(key, 'start')); }
            catch (e) { toast(e.status === 403 ? e.message : 'Could not open the conversation. Try again.'); return; }
            this.turn = 0;
            const npc = this.data.npc;
            $('tw-npc-name').textContent = npc.name;
            $('tw-npc-role').textContent = npc.role + ' · ' + this.data.title;
            $('tw-goal').textContent = 'Goal: ' + this.data.goal + (this.data.done_today ? ' (Already rewarded today: this round is practice.)' : '');
            drawPerson($('tw-portrait'), npc.sprite);
            $('tw-result').hidden = true;
            $('tw-options').hidden = false;
            const steps = $('tw-steps'); steps.innerHTML = '';
            this.data.turns.forEach(() => steps.append(document.createElement('li')));
            openPanel($('tw-dialog'));
            this.show();
        },
        show() {
            const t = this.data.turns[this.turn];
            [...$('tw-steps').children].forEach((li, i) => { li.className = i < this.turn ? 'done' : i === this.turn ? 'now' : ''; });
            const line = $('tw-line');
            line.lang = (this.data.speech || 'fi-FI').slice(0, 2);
            clearInterval(this.typing);
            line.textContent = '';
            let i = CALM ? t.say.length - 1 : 0;
            this.typing = setInterval(() => {      // the line appears letter by letter, like speech
                line.textContent = t.say.slice(0, ++i);
                if (i % 3 === 0) Sound.tone(880 + (i % 5) * 40, .025, 'square', .02);
                if (i >= t.say.length) clearInterval(this.typing);
            }, 28);
            $('tw-en').textContent = t.en;
            $('tw-en').hidden = true;
            $('tw-en-toggle').setAttribute('aria-expanded', 'false');
            $('tw-en-toggle').textContent = 'Show in English';
            $('tw-feedback').textContent = ''; $('tw-feedback').className = 'tw-feedback';
            const box = $('tw-options'); box.innerHTML = '';
            t.options.forEach((o, n) => {
                const b = document.createElement('button');
                b.type = 'button'; b.className = 'tw-opt'; b.lang = line.lang;
                const k = document.createElement('kbd'); k.textContent = n + 1;
                const s = document.createElement('span'); s.textContent = o;
                b.append(k, s);
                b.addEventListener('click', () => this.answer(n, b));
                box.append(b);
            });
            $('tw-portrait').classList.remove('bounce'); void $('tw-portrait').offsetWidth; $('tw-portrait').classList.add('bounce');
        },
        async answer(choice, button) {
            if (this.busy) return;
            this.busy = true;
            let r;
            try { r = await post(sceneUrl(this.key, 'answer'), {turn: this.turn, choice}); }
            catch (e) {
                this.busy = false;
                if (e.status === 409) { toast('The conversation restarted.'); this.start(this.key); }
                else toast('No connection. Try again.');
                return;
            }
            const fb = $('tw-feedback');
            if (!r.right) {
                Sound.wrong();
                button.classList.add('wrong'); button.disabled = true;
                fb.className = 'tw-feedback bad';
                fb.textContent = 'That means “' + r.meaning.replace(/[.!?]$/, '') + '”. Try another reply.';
                this.busy = false;
                return;
            }
            Sound.right();
            button.classList.add('right');
            $('tw-options').querySelectorAll('button').forEach(b => { b.disabled = true; });
            fb.className = 'tw-feedback ok';
            fb.textContent = ['Hyvä!', 'Selvä!', 'Täydellistä!', 'Juuri niin!'][this.turn % 4] + '  “' + r.meaning.replace(/[.!?]$/, '') + '”';
            setTimeout(() => {
                this.busy = false;
                if (r.done) this.finish(r); else { this.turn += 1; this.show(); }
            }, 900);
        },
        finish(r) {
            Sound.done();
            [...$('tw-steps').children].forEach(li => { li.className = 'done'; });
            clearInterval(this.typing);
            $('tw-line').textContent = this.data.turns[this.data.turns.length - 1].say;
            $('tw-options').hidden = true;
            $('tw-feedback').textContent = '';
            const box = $('tw-result'); box.innerHTML = '';
            const h = document.createElement('h3'); h.textContent = 'Conversation complete';
            const p = document.createElement('p');
            p.textContent = r.first_try + ' of ' + r.turns + ' replies right the first time.';
            const ul = document.createElement('ul');
            const rw = r.reward;
            const add = text => { const li = document.createElement('li'); li.textContent = text; ul.append(li); };
            if (rw && rw.paid) add('+' + rw.xp + ' XP and ' + rw.coins + ' coins');
            else add('Already rewarded today. Practice still helps you remember.');
            if (rw) {
                (rw.quests || []).forEach(q => add('Quest done: ' + q));
                (rw.unlocked || []).forEach(a => add('Achievement: ' + a.name));
                if (rw.level_up) add('Level ' + rw.level_up.level + ' reached');
            }
            const row = document.createElement('div'); row.className = 'row';
            const save = document.createElement('button'); save.type = 'button'; save.className = 'tw-btn';
            save.textContent = 'Save these phrases as cards';
            save.addEventListener('click', async () => {
                save.disabled = true;
                try {
                    const s = await post(sceneUrl(this.key, 'save'));
                    save.textContent = s.created ? 'Saved: ' + s.count + ' phrase cards' : 'Already in your cards';
                    const a = document.createElement('a'); a.className = 'tw-btn ghost'; a.href = s.url; a.textContent = 'Open the lesson';
                    row.append(a);
                } catch (e) { save.disabled = false; toast(e.message); }
            });
            const leave = document.createElement('button'); leave.type = 'button'; leave.className = 'tw-btn ghost'; leave.textContent = 'Leave';
            leave.setAttribute('data-close', '');
            row.append(save, leave);
            box.append(h, p, ul, row);
            box.hidden = false;
            setTimeout(() => save.focus({preventScroll: true}), 30);
            if (rw && rw.paid) GAME.events.emit('reward', rw.xp, rw.coins);
            refresh();
        },
    };
    // A short round of the learner's own cards, as multiple choice, graded by the same API as the practice page.
    const Drill = {
        cards: [], queue: [], cur: null, done: 0, xp: 0, extra: false, busy: false, lesson: null,
        ask: {word: 'What does it mean?', concept: 'What does it mean?', phrase: 'Which phrase means this?',
              sentence: 'Which word fills the gap?', question: 'Choose the answer.'},
        task(c) {
            const pool = field => [...new Set(this.cards.filter(o => o.id !== c.id && o[field] && (o.kind === c.kind || field === 'cloze' && o.kind === 'word')).map(o => field === 'cloze' && o.kind === 'word' ? o.front : o[field]))];
            if (c.kind === 'question') return {front: c.front, options: c.options, right: c.options[c.answer]};
            const field = {word: 'en', concept: 'en', phrase: 'front', sentence: 'cloze'}[c.kind];
            if (!field || !c[field]) return null;
            const others = pool(field).filter(x => x.toLowerCase() !== c[field].toLowerCase()).sort(() => Math.random() - .5).slice(0, 2);
            if (others.length < 2) return null;
            const options = [...others, c[field]].sort(() => Math.random() - .5);
            const front = c.kind === 'phrase' ? c.en : c.kind === 'sentence' ? c.front.replace(new RegExp(c.cloze.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'), '____') : c.front;
            return {front, options, right: c[field], hint: c.kind === 'sentence' ? c.en : ''};
        },
        async start(lesson) {
            this.lesson = lesson;
            let d;
            try { d = await (await fetch(CFG.due + '?lesson=' + lesson.id, {headers: {'Accept': 'application/json'}, credentials: 'same-origin'})).json(); }
            catch (e) { toast('Could not load your cards.'); return; }
            this.cards = d.cards || [];
            this.extra = !!d.extra;
            this.queue = this.cards.filter(c => this.task(c)).slice(0, 10);
            if (!this.queue.length) { toast('This lesson has no cards that work as multiple choice here. Use All practice modes.'); return; }
            this.done = 0; this.xp = 0;
            $('tw-pr-sub').textContent = lesson.title + (this.extra ? ' · extra round' : '');
            const steps = $('tw-pr-steps'); steps.innerHTML = '';
            this.queue.forEach(() => steps.append(document.createElement('li')));
            $('tw-pr-result').hidden = true; $('tw-pr-options').hidden = false;
            openPanel($('tw-practice'));
            this.next();
        },
        next() {
            [...$('tw-pr-steps').children].forEach((li, i) => { li.className = i < this.done ? 'done' : i === this.done ? 'now' : ''; });
            this.cur = this.queue[this.done];
            if (!this.cur) return this.finish();
            const t = this.cur.t = this.task(this.cur);
            $('tw-pr-ask').textContent = this.ask[this.cur.kind] || '';
            $('tw-pr-front').textContent = t.front;
            $('tw-pr-front').lang = this.cur.kind === 'phrase' ? 'en' : (this.cur.tl || 'fi');
            $('tw-pr-hint').textContent = t.hint || '';
            $('tw-pr-feedback').textContent = ''; $('tw-pr-feedback').className = 'tw-feedback';
            const box = $('tw-pr-options'); box.innerHTML = '';
            t.options.forEach((o, n) => {
                const b = document.createElement('button'); b.type = 'button'; b.className = 'tw-opt';
                b.append(Object.assign(document.createElement('kbd'), {textContent: n + 1}), span('', o));
                b.addEventListener('click', () => this.answer(o, b));
                box.append(b);
            });
        },
        async answer(given, button) {
            if (this.busy) return;
            this.busy = true;
            const right = given === this.cur.t.right;
            $('tw-pr-options').querySelectorAll('button').forEach(b => {
                b.disabled = true;
                if (b.textContent.slice(1) === this.cur.t.right) b.classList.add('right');
            });
            if (!right) button.classList.add('wrong');
            (right ? Sound.right : Sound.wrong).call(Sound);
            const fb = $('tw-pr-feedback');
            fb.className = 'tw-feedback ' + (right ? 'ok' : 'bad');
            fb.textContent = right ? 'Oikein!' : 'The answer is “' + this.cur.t.right + '”.';
            try {
                const r = await post(CFG.grade, {item: this.cur.id, grade: right ? 'good' : 'again', mode: 'choice', given,
                                                 ...(this.extra ? {extra: '1'} : {})});
                if (r.reward && r.reward.xp) {
                    this.xp += r.reward.xp;
                    GAME.scene.getScene('town').float('+' + r.reward.xp + ' XP', '#8de0a8');
                }
            } catch (e) { /* the round goes on; the answer is just not saved */ }
            setTimeout(() => { this.busy = false; this.done += 1; this.next(); }, right ? 700 : 1500);
        },
        finish() {
            Sound.done();
            $('tw-pr-options').hidden = true;
            $('tw-pr-front').textContent = 'Valmis!';
            $('tw-pr-ask').textContent = ''; $('tw-pr-hint').textContent = ''; $('tw-pr-feedback').textContent = '';
            const box = $('tw-pr-result'); box.innerHTML = '';
            const h = Object.assign(document.createElement('h3'), {textContent: 'Round complete'});
            const p = Object.assign(document.createElement('p'), {textContent: this.queue.length + ' cards practised' + (this.xp ? ', +' + this.xp + ' XP.' : '.') +
                                     (this.extra ? ' Extra rounds do not change your review schedule.' : ' Your next reviews are planned.')});
            const row = document.createElement('div'); row.className = 'tw-row';
            const again = document.createElement('button'); again.type = 'button'; again.className = 'tw-btn'; again.textContent = 'Another round';
            again.addEventListener('click', () => this.start(this.lesson));
            const leave = document.createElement('button'); leave.type = 'button'; leave.className = 'tw-btn ghost'; leave.textContent = 'Leave'; leave.setAttribute('data-close', '');
            row.append(again, leave);
            box.append(h, p, row); box.hidden = false;
            refresh();
        },
    };
    $('tw-pr-listen').addEventListener('click', () => {
        if (!Drill.cur || !('speechSynthesis' in window) || Drill.cur.kind === 'phrase') return;
        const u = new SpeechSynthesisUtterance(Drill.cur.kind === 'sentence' ? Drill.cur.front : Drill.cur.t.front);
        u.lang = Drill.cur.speech || 'fi-FI'; speechSynthesis.cancel(); speechSynthesis.speak(u);
    });

    $('tw-listen').addEventListener('click', () => {
        if (!Talk.data || !('speechSynthesis' in window)) return;
        const u = new SpeechSynthesisUtterance(Talk.data.turns[Talk.turn].say);
        u.lang = Talk.data.speech || 'fi-FI'; u.rate = .9;
        speechSynthesis.cancel(); speechSynthesis.speak(u);
    });
    $('tw-en-toggle').addEventListener('click', e => {
        const open = $('tw-en').hidden;
        $('tw-en').hidden = !open;
        e.currentTarget.setAttribute('aria-expanded', String(open));
        e.currentTarget.textContent = open ? 'Hide English' : 'Show in English';
    });
    document.addEventListener('keydown', e => {
        const box = panel === $('tw-dialog') ? $('tw-options') : panel === $('tw-practice') ? $('tw-pr-options') : null;
        if (!box || box.hidden) return;
        const n = {'1': 0, '2': 1, '3': 2, '4': 3}[e.key];
        const b = n !== undefined && box.children[n];
        if (b && !b.disabled) { e.preventDefault(); b.click(); }
    });

    // ── choosing a character ──────────────────────────────────────────────
    function pickCharacter() {
        return new Promise(resolve => {
            const row = $('tw-pick-row'); row.innerHTML = '';
            PEOPLE.forEach((_, i) => {
                const b = document.createElement('button'); b.type = 'button'; b.setAttribute('aria-label', 'Character ' + (i + 1));
                const c = document.createElement('canvas'); c.width = 64; c.height = 64; drawPerson(c, i);
                b.append(c);
                b.addEventListener('click', async () => {
                    try { await post(CFG.avatar, {sprite: i}); } catch (e) { /* keep the choice for this visit */ }
                    STATE.sprite = i; drawHud(); closePanel(); resolve(i);
                });
                row.append(b);
            });
            openPanel($('tw-pick'));
        });
    }

    // ── the game ──────────────────────────────────────────────────────────
    let GAME = null;

    class Town extends Phaser.Scene {
        constructor() { super('town'); }

        preload() {
            this.load.tilemapTiledJSON('map', CFG.map);
            this.load.image('tiles', CFG.tiles);
            this.load.spritesheet('sheet', CFG.tiles, {frameWidth: T, frameHeight: T});
        }

        create() {
            const map = this.make.tilemap({key: 'map'});
            const ts = map.addTilesetImage('urban', 'tiles');
            ['ground', 'marks', 'build', 'decor'].forEach((name, i) => map.createLayer(name, ts, 0, 0).setDepth(i));
            map.createLayer('above', ts, 0, 0).setDepth(100000);
            this.map = map;
            this.W = map.width; this.H = map.height;
            const prop = name => (map.properties || []).find(p => p.name === name);
            this.solid = new Set(JSON.parse(prop('solid').value).map(([x, y]) => y * this.W + x));
            this.decorate(false);
            this.physics.world.setBounds(0, 0, map.widthInPixels, map.heightInPixels);

            // Walls: one static body per run of solid tiles in a row.
            this.walls = this.physics.add.staticGroup();
            for (let y = 0; y < this.H; y++) {
                let x = 0;
                while (x < this.W) {
                    if (!this.solid.has(y * this.W + x)) { x++; continue; }
                    const x0 = x;
                    while (x < this.W && this.solid.has(y * this.W + x)) x++;
                    const z = this.add.zone(x0 * T + (x - x0) * T / 2, y * T + T / 2, (x - x0) * T, T);
                    this.walls.add(z);
                }
            }

            // Animations for every townsperson.
            PEOPLE.forEach((base, who) => Object.entries(DIR).forEach(([name, d]) => {
                const f = base + d;
                this.anims.create({key: `walk-${who}-${name}`, frameRate: 7, repeat: -1,
                                   frames: [f + SHEET_COLS, f, f + 2 * SHEET_COLS, f].map(frame => ({key: 'sheet', frame}))});
            }));

            const objects = map.getObjectLayer('objects').objects;
            const props = o => Object.fromEntries((o.properties || []).map(p => [p.name, p.value]));
            const spawn = objects.find(o => o.type === 'spawn');

            // The learner.
            this.who = STATE.sprite ?? 0;
            this.player = this.physics.add.sprite(spawn.x + T / 2, spawn.y + T / 2, 'sheet', PEOPLE[this.who] + DIR.down);
            this.player.body.setSize(10, 6).setOffset(3, 10);
            this.player.setCollideWorldBounds(true);
            this.facing = 'down';
            this.physics.add.collider(this.player, this.walls);
            this.shadow = this.add.ellipse(0, 0, 11, 4, 0x000000, .22).setDepth(3.5);

            // Places to visit, with signs over their doors.
            this.places = objects.filter(o => o.type === 'place').map(o => {
                const p = props(o);
                const place = {key: o.name, x: o.x + o.width / 2, y: o.y + o.height / 2, ...p,
                               doorX: +p.door_x, doorY: +p.door_y};
                this.sign(place);
                return place;
            });

            // Townspeople walking their rounds, and cars on the road.
            objects.filter(o => o.type === 'route').forEach(o => this.walker(props(o)));
            this.cars();
            this.lighting();

            // Camera: integer zoom keeps the pixels sharp.
            const cam = this.cameras.main;
            cam.setBounds(0, 0, map.widthInPixels, map.heightInPixels);
            cam.startFollow(this.player, true, .12, .12);
            cam.setRoundPixels(true);
            const fit = () => cam.setZoom(Math.max(2, Math.min(4, Math.round(this.scale.width / (T * 22)))));
            fit();
            this.scale.on('resize', fit);
            if (!CALM) cam.fadeIn(400, 43, 47, 69);

            // Controls.
            this.keys = this.input.keyboard.addKeys('UP,DOWN,LEFT,RIGHT,W,A,S,D,E,SPACE,ENTER');
            this.input.keyboard.on('keydown', e => {
                if (panel) return;
                if (['E', ' ', 'Enter'].includes(e.key === 'e' ? 'E' : e.key) && this.near) { e.preventDefault(); this.enter(this.near); }
                $('tw-hint').classList.add('gone');
            });
            // Typing somewhere else on the page (the site search, a form) must not walk the character or eat spaces.
            const typing = el => el && el.matches && el.matches('input, textarea, select, [contenteditable="true"]');
            const kb = this.input.keyboard;
            document.addEventListener('focusin', e => {
                if (typing(e.target)) { kb.enabled = false; kb.disableGlobalCapture(); kb.resetKeys(); }
            });
            document.addEventListener('focusout', e => {
                if (typing(e.target)) { kb.enabled = true; kb.enableGlobalCapture(); kb.resetKeys(); }
            });
            this.route = [];
            this.input.on('pointerdown', (ptr, over) => {
                if (panel || (over && over.length)) return;
                $('tw-hint').classList.add('gone');
                this.walkTo(Math.floor(ptr.worldX / T), Math.floor(ptr.worldY / T));
            });
            $('tw-prompt-go').addEventListener('click', () => this.near && this.enter(this.near));

            this.events.on('reward', (xp, coins) => this.float('+' + xp + ' XP   +' + coins, '#f2c14e'));
            this.near = null;
        }

        sign(place) {
            // Shop signs hang over the door; a free-standing board gets its name just above it.
            const x = place.doorX * T + T / 2, y = place.sign === 'low' ? (place.doorY - 1) * T + 3 : (place.doorY - 2) * T - 3;
            const text = this.add.text(x, y, place.title.toUpperCase(), {fontFamily: '"Press Start 2P", monospace', fontSize: '5px',
                                                                       color: this.locked(place) ? '#c9cfdc' : '#f4f1ea'})
                .setOrigin(.5).setResolution(8).setDepth(6);
            const w = text.width + 8;
            const g = this.add.graphics().setDepth(5);
            g.fillStyle(0x000000, .25).fillRoundedRect(x - w / 2 + 1, y - 4, w, 10, 2);
            g.fillStyle(this.locked(place) ? 0x4b5175 : 0x2b2f45, 1).fillRoundedRect(x - w / 2, y - 5, w, 10, 2);
            g.lineStyle(1, this.locked(place) ? 0x7f86a8 : 0xf2c14e, 1).strokeRoundedRect(x - w / 2, y - 5, w, 10, 2);
        }

        // Decorations the learner bought: tiles put into the map, plus lights and flags drawn on top.
        decorate(live) {
            const d = STATE.decor || {tiles: [], fx: []};
            this.fx = this.fx || new Set();
            d.tiles.forEach(t => {
                this.map.putTileAt(t.tile + 1, t.x, t.y, true, t.layer);
                const k = t.y * this.W + t.x;
                if (t.solid && !this.solid.has(k)) {
                    this.solid.add(k);
                    if (live) this.walls.add(this.add.zone(t.x * T + T / 2, t.y * T + T / 2, T, T));
                }
            });
            if (d.fx.includes('lights') && !this.fx.has('lights')) {
                this.fx.add('lights');
                const colours = [0xff6b6b, 0xffd166, 0x6be3a0, 0x6bb6ff];
                [[2, 11, 5], [12, 17, 6]].forEach(([x0, x1, y]) => {
                    for (let x = x0 * T + 4, i = 0; x < x1 * T - 2; x += 6, i++) {
                        const sag = Math.sin((x - x0 * T) / ((x1 - x0) * T) * Math.PI) * 3;
                        const dot = this.add.circle(x, y * T + 1 + sag, 1.3, colours[i % 4]).setDepth(150002);
                        this.tweens.add({targets: dot, alpha: .45, duration: 600 + (i % 5) * 180, yoyo: true, repeat: -1});
                    }
                });
            }
            if (d.fx.includes('flags') && !this.fx.has('flags')) {
                this.fx.add('flags');
                [27, 36].forEach(x => {
                    const px = x * T + 8, py = 2 * T + 10;
                    this.add.rectangle(px, py, 1.5, 22, 0xe9e3d3).setOrigin(.5, 1).setDepth(100001);
                    const flag = this.add.container(px + 1, py - 21).setDepth(100001);
                    flag.add([this.add.rectangle(0, 0, 13, 8, 0xffffff).setOrigin(0),
                              this.add.rectangle(3.5, 0, 2.2, 8, 0x1f4fa0).setOrigin(0),
                              this.add.rectangle(0, 3, 13, 2.2, 0x1f4fa0).setOrigin(0)]);
                    this.tweens.add({targets: flag, scaleX: .86, duration: 900 + x * 10, yoyo: true, repeat: -1, ease: 'Sine.easeInOut'});
                });
            }
            if (live) this.float('New in town!', '#f2c14e');
        }

        locked(place) { return !!(((STATE.places || {})[place.key] || {}).locked); }

        walker({npc, points}) {
            const pts = (typeof points === 'string' ? JSON.parse(points) : points).map(([x, y]) => ({x: x * T + T / 2, y: y * T + T / 2}));
            const who = +npc;
            const s = this.add.sprite(pts[0].x, pts[0].y, 'sheet', PEOPLE[who] + DIR.down).setInteractive({useHandCursor: true});
            const shadow = this.add.ellipse(0, 0, 11, 4, 0x000000, .2).setDepth(3.5);
            s.on('pointerdown', () => this.greet(s));
            let i = 0;
            const step = () => {
                if (Math.hypot(this.player.x - s.x, this.player.y - s.y) < 22) {   // someone is in the way: wait and look at them
                    const dx = this.player.x - s.x, dy = this.player.y - s.y;
                    s.setFrame(PEOPLE[who] + DIR[Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? 'right' : 'left') : (dy > 0 ? 'down' : 'up')]);
                    this.time.delayedCall(900, step);
                    return;
                }
                const a = pts[i], b = pts[(i + 1) % pts.length];
                i = (i + 1) % pts.length;
                const dx = b.x - a.x, dy = b.y - a.y;
                const dir = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? 'right' : 'left') : (dy > 0 ? 'down' : 'up');
                s.play(`walk-${who}-${dir}`, true);
                this.tweens.add({targets: s, x: b.x, y: b.y, duration: Math.hypot(dx, dy) / 26 * 1000,
                                 onComplete: () => {
                                     s.stop(); s.setFrame(PEOPLE[who] + DIR[dir]);
                                     this.time.delayedCall(600 + Math.random() * 1800, step);
                                 }});
            };
            this.time.delayedCall(Math.random() * 1500, step);
            this.events.on('update', () => { s.setDepth(10 + s.y); shadow.setPosition(s.x, s.y + 7); });
        }

        greet(s) {
            const lines = STATE.greetings || [];
            if (!lines.length || s.bubble) return;
            const [say, en] = lines[Math.floor(Math.random() * lines.length)];
            const t = this.add.text(s.x, s.y - 13, say, {fontFamily: 'system-ui, sans-serif', fontSize: '6px', color: '#2b2f45',
                                                          backgroundColor: '#f4f1ea', padding: {x: 3, y: 2}})
                .setOrigin(.5, 1).setResolution(10).setDepth(200000);
            s.bubble = t;
            const follow = () => t.setPosition(s.x, s.y - 13);
            this.events.on('update', follow);
            toast(say + '  ·  ' + en);
            Sound.tone(740, .05, 'triangle', .05); Sound.tone(988, .07, 'triangle', .05, .06);
            if ('speechSynthesis' in window && Sound.on) {
                const u = new SpeechSynthesisUtterance(say); u.lang = 'fi-FI'; speechSynthesis.cancel(); speechSynthesis.speak(u);
            }
            this.time.delayedCall(2600, () => { this.events.off('update', follow); t.destroy(); s.bubble = null; });
        }

        // Light by the hour: a warm dawn, plain day, a pink dusk and a blue night with lamps and windows lit.
        lighting() {
            const forced = new URLSearchParams(location.search).get('time');
            const h = new Date().getHours();
            const when = ['dawn', 'day', 'dusk', 'night'].includes(forced) ? forced
                : h >= 6 && h < 9 ? 'dawn' : h >= 9 && h < 16 ? 'day' : h >= 16 && h < 18 ? 'dusk' : 'night';
            const tint = {dawn: 0xf2d3bd, day: 0xffffff, dusk: 0xd8a3a0, night: 0x5866a8}[when];
            if (when === 'day') return;
            const cam = this.cameras.main;
            const shade = this.add.rectangle(0, 0, this.scale.width, this.scale.height, tint).setOrigin(0).setScrollFactor(0)
                .setBlendMode(Phaser.BlendModes.MULTIPLY).setDepth(150000);
            this.scale.on('resize', size => shade.setSize(size.width, size.height));
            if (when === 'dawn') return;
            if (!this.textures.exists('glow')) {   // a soft round light, drawn once
                const c = this.textures.createCanvas('glow', 64, 64), ctx = c.getContext();
                const grd = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
                grd.addColorStop(0, 'rgba(255,214,140,1)'); grd.addColorStop(.35, 'rgba(255,190,110,.45)'); grd.addColorStop(1, 'rgba(255,170,90,0)');
                ctx.fillStyle = grd; ctx.fillRect(0, 0, 64, 64); c.refresh();
            }
            const glow = (x, y, r, a) => this.add.image(x, y, 'glow').setScale(r / 32).setAlpha(a)
                .setBlendMode(Phaser.BlendModes.ADD).setDepth(150001);
            const strength = when === 'night' ? 1 : .5;
            this.map.getLayer('above').data.flat().forEach(tile => {
                if (tile.index === 165 || tile.index === 170) {   // lamp heads
                    const x = tile.pixelX + (tile.index === 165 ? 4 : 8), y = tile.pixelY + 6;
                    glow(x, y + 14, 30, .35 * strength); glow(x, y + 2, 9, .9 * strength);
                }
            });
            this.map.getLayer('decor').data.flat().forEach(tile => {
                if ([391, 445, 360, 361, 362, 387, 388, 389].includes(tile.index)) {   // windows and the café's shop window
                    this.add.rectangle(tile.pixelX + 8, tile.pixelY + 8, 12, 10, 0xffc36b, .35 * strength)
                        .setBlendMode(Phaser.BlendModes.ADD).setDepth(150001);
                }
            });
            cam.setBackgroundColor(when === 'night' ? '#2b2f45' : '#a9abc4');
        }

        cars() {
            // A car is four tiles drawn together; it drives down one lane and up the other, now and then.
            const tex = (key, tiles, w, h) => {
                const rt = this.make.renderTexture({width: w * T, height: h * T}, false);
                tiles.forEach((f, n) => rt.drawFrame('sheet', f, (n % w) * T, Math.floor(n / w) * T));
                rt.saveTexture(key);
            };
            tex('taxi-front', [422], 1, 1);
            tex('red-front', [449, 476], 1, 2);
            tex('taxi-back', [420, 421], 2, 1);
            tex('red-back', [447, 448, 474, 475], 2, 2);
            const lanes = [{x: 19 * T, down: true, cars: ['taxi-front', 'red-front']},
                           {x: 22 * T, down: false, cars: ['taxi-back', 'red-back']}];
            const drive = (lane, key, delay) => {
                const car = this.add.image(lane.x, 0, key).setDepth(9);
                const top = -2 * T, bottom = this.map.heightInPixels + 2 * T;
                const go = () => {
                    car.setTexture(lane.cars[Math.floor(Math.random() * lane.cars.length)]);
                    car.y = lane.down ? top : bottom;
                    this.tweens.add({targets: car, y: lane.down ? bottom : top, duration: 6500 + Math.random() * 2500,
                                     onComplete: () => this.time.delayedCall(3000 + Math.random() * 7000, go)});
                };
                this.time.delayedCall(delay, go);
            };
            drive(lanes[0], 'taxi-front', 800);
            drive(lanes[1], 'taxi-back', 4500);
        }

        float(text, color = '#f4f1ea') {
            const t = this.add.text(this.player.x, this.player.y - 14, text, {fontFamily: '"Press Start 2P", monospace', fontSize: '8px',
                                                                              color, stroke: '#2b2f45', strokeThickness: 3})
                .setOrigin(.5).setResolution(8).setDepth(200000);
            this.tweens.add({targets: t, y: t.y - 22, alpha: 0, duration: 1800, ease: 'Cubic.easeOut', onComplete: () => t.destroy()});
        }

        // ── walking by tap: shortest path over free tiles (breadth first; the town is small) ──
        free(x, y) { return x >= 0 && y >= 0 && x < this.W && y < this.H && !this.solid.has(y * this.W + x); }
        walkTo(tx, ty) {
            // Tapping a building walks to its door.
            if (!this.free(tx, ty)) {
                let best = null, bd = 7;
                this.places.forEach(p => {
                    const d = Math.abs(p.doorX - tx) + Math.abs(p.doorY - ty);
                    if (d < bd) { bd = d; best = p; }
                });
                if (best) { tx = Math.floor(best.x / T); ty = Math.floor(best.y / T); this.goal = best; }
                else return;
            } else {   // tapping a doorstep also goes in
                this.goal = this.places.find(p => Math.floor(p.x / T) === tx && Math.floor(p.y / T) === ty) || null;
            }
            const sx = Math.floor(this.player.x / T), sy = Math.floor((this.player.y + 4) / T);
            const prev = new Map([[sy * this.W + sx, -1]]);
            const queue = [[sx, sy]];
            while (queue.length) {
                const [x, y] = queue.shift();
                if (x === tx && y === ty) break;
                for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
                    const nx = x + dx, ny = y + dy, k = ny * this.W + nx;
                    if (this.free(nx, ny) && !prev.has(k)) { prev.set(k, y * this.W + x); queue.push([nx, ny]); }
                }
            }
            let k = ty * this.W + tx;
            if (!prev.has(k)) return;
            const path = [];
            while (k !== -1) { path.unshift({x: (k % this.W) * T + T / 2, y: Math.floor(k / this.W) * T + T / 2 - 4}); k = prev.get(k); }
            path.shift();
            this.route = path;
            this.marker && this.marker.destroy();
            this.marker = this.add.circle(tx * T + T / 2, ty * T + T / 2, 4, 0xf2c14e, .8).setDepth(4);
            this.tweens.add({targets: this.marker, scale: 1.6, alpha: 0, duration: 700, onComplete: () => this.marker && this.marker.destroy()});
        }

        enter(place) {
            this.route = [];
            this.player.setVelocity(0);
            if (place.panel === 'quests') { showQuests(); return; }
            if (place.panel === 'lessons') { showLessons(); return; }
            if (place.panel === 'home') { showHome(); return; }
            const info = (STATE.places || {})[place.key] || {};
            if (place.locked || info.locked) {
                Sound.wrong();
                toast(place.title + ': ' + (info.level ? 'opens at level ' + info.level : 'opens in a later version') + '.');
                return;
            }
            if (place.scene) Talk.start(place.scene);
        }

        update() {
            const p = this.player, k = this.keys;
            let vx = 0, vy = 0;
            if (!panel) {
                if (k.LEFT.isDown || k.A.isDown) vx = -1; else if (k.RIGHT.isDown || k.D.isDown) vx = 1;
                if (k.UP.isDown || k.W.isDown) vy = -1; else if (k.DOWN.isDown || k.S.isDown) vy = 1;
                if (vx || vy) this.route = [];
                else if (this.route.length) {
                    const n = this.route[0];
                    const dx = n.x - p.x, dy = n.y - p.y;
                    if (Math.hypot(dx, dy) < 2) {
                        this.route.shift();
                        if (!this.route.length && this.goal) { const g = this.goal; this.goal = null; this.enter(g); }
                    } else {
                        // One axis at a time, lining up on the short one first, so corners are never cut.
                        const ax = Math.abs(dx) > 1, ay = Math.abs(dy) > 1;
                        if (ax && ay) { if (Math.abs(dx) < Math.abs(dy)) vx = Math.sign(dx); else vy = Math.sign(dy); }
                        else { vx = ax ? Math.sign(dx) : 0; vy = ay ? Math.sign(dy) : 0; }
                        // Blocked for a while (another walker, a bad tap): give up on this route.
                        const moved = Math.hypot(p.x - (this.lastPos?.x ?? 0), p.y - (this.lastPos?.y ?? 0));
                        this.lastPos = {x: p.x, y: p.y};
                        this.stuck = moved < .2 ? (this.stuck || 0) + 1 : 0;
                        if (this.stuck > 40) { this.route = []; this.goal = null; this.stuck = 0; }
                    }
                }
            }
            const len = Math.hypot(vx, vy) || 1;
            p.setVelocity(vx / len * SPEED, vy / len * SPEED);
            if (vx || vy) {
                this.facing = Math.abs(vx) > Math.abs(vy) ? (vx > 0 ? 'right' : 'left') : (vy > 0 ? 'down' : 'up');
                p.play(`walk-${this.who}-${this.facing}`, true);
                if (Sound.on && this.time.now - (this.lastStep || 0) > 280) { this.lastStep = this.time.now; Sound.tone(120, .03, 'triangle', .02); }
            } else {
                p.stop(); p.setFrame(PEOPLE[this.who] + DIR[this.facing]);
            }
            p.setDepth(10 + p.y);
            this.shadow.setPosition(p.x, p.y + 7);

            // The nearest door within reach gets a prompt.
            let near = null, best = 20;
            this.places.forEach(pl => { const d = Math.hypot(pl.x - p.x, pl.y - (p.y + 4)); if (d < best) { best = d; near = pl; } });
            if (near !== this.near) { this.near = near; if (near) Sound.blip(); }
            const prompt = $('tw-prompt');
            if (near && !panel) {
                const cam = this.cameras.main;
                const sig = [near.key, Math.round(cam.worldView.x), Math.round(cam.worldView.y), cam.zoom, JSON.stringify((STATE.places || {})[near.key])].join();
                if (sig === this.promptSig && !prompt.hidden) return;
                this.promptSig = sig;
                const sx = (near.doorX * T + T / 2 - cam.worldView.x) * cam.zoom;
                const sy = ((near.doorY - (near.sign === 'low' ? 1.5 : 2.7)) * T - cam.worldView.y) * cam.zoom;
                const info = (STATE.places || {})[near.key] || {};
                const locked = near.locked || info.locked;
                prompt.hidden = false;
                prompt.classList.toggle('locked', !!locked);
                prompt.style.left = sx + 'px'; prompt.style.top = sy + 'px';
                $('tw-prompt-title').textContent = near.title;
                $('tw-prompt-sub').textContent = info.done_today ? near.subtitle + ' · rewarded today' : near.subtitle;
                $('tw-prompt-act').textContent = locked ? 'Locked' : near.panel ? 'Read' : 'Enter';
            } else if (!prompt.hidden) { prompt.hidden = true; this.promptSig = null; }
        }
    }

    // ── start ─────────────────────────────────────────────────────────────
    async function boot() {
        const img = new Image();
        img.src = CFG.tiles;
        await Promise.all([img.decode(), refresh(), document.fonts ? document.fonts.load('8px "Press Start 2P"') : null]);
        SHEET = img;
        drawHud();
        GAME = new Phaser.Game({
            type: Phaser.AUTO, parent: 'tw-stage', pixelArt: true, roundPixels: true, backgroundColor: '#a9abc4',
            scale: {mode: Phaser.Scale.RESIZE, width: root.clientWidth, height: root.clientHeight},
            physics: {default: 'arcade', arcade: {debug: false}},
            scene: Town,
        });
        $('tw-loading').hidden = true;
        if (CFG.debug) window.ljTown = GAME;   // local development only: lets tests drive the game
        root.tabIndex = -1;
        if (STATE.sprite == null) {
            const who = await pickCharacter();
            const s = GAME.scene.getScene('town');
            if (s && s.player) { s.who = who; s.player.setFrame(PEOPLE[who] + DIR.down); }
        }
        if (matchMedia('(pointer: coarse)').matches) $('tw-hint').textContent = 'Tap where to walk. Tap a door to go in.';
        setTimeout(() => $('tw-hint').classList.add('gone'), 9000);
    }
    boot().catch(() => { $('tw-loading').textContent = 'The town could not load. Reload the page to try again.'; });
})();
