/* LearningJourney cartoon characters, drawn as inline SVG from a few parts.
   spec: {skin, hair, hair_color, shirt, extra} (see journey.models.AVATAR_PARTS)
   mood: 'happy' | 'neutral' | 'sad' | 'talk' */
(function () {
    const esc = c => String(c || '').replace(/[^#0-9a-zA-Z]/g, '');

    function hair(style, color) {
        const c = esc(color);
        const top = `<path d="M27 44 Q26 17 50 16 Q74 17 73 44 Q68 30 50 29 Q32 30 27 44Z" fill="${c}"/>`;
        switch (style) {
            case 'long':
                return `<path d="M25 46 Q22 15 50 14 Q78 15 75 46 L77 74 Q70 70 70 52 Q68 30 50 29 Q32 30 30 52 Q30 70 23 74Z" fill="${c}"/>`;
            case 'curly':
                return [[32, 30, 9], [42, 22, 9], [54, 20, 10], [65, 26, 9], [71, 36, 7], [28, 38, 7]]
                    .map(([x, y, r]) => `<circle cx="${x}" cy="${y}" r="${r}" fill="${c}"/>`).join('');
            case 'bun':
                return `<circle cx="50" cy="13" r="8" fill="${c}"/>` + top;
            case 'bald':
                return '';
            case 'cap':
                return `<path d="M27 38 Q28 15 50 15 Q72 15 73 38Z" fill="${c}"/><rect x="48" y="34" width="34" height="5" rx="2.5" fill="${c}"/>`;
            default:
                return top;
        }
    }

    function mouth(mood) {
        if (mood === 'sad') return '<path d="M43 60 Q50 54 57 60" stroke="#5b2a2a" stroke-width="2.4" fill="none" stroke-linecap="round"/>';
        if (mood === 'neutral') return '<path d="M44 58 L56 58" stroke="#5b2a2a" stroke-width="2.4" stroke-linecap="round"/>';
        if (mood === 'talk') return '<ellipse cx="50" cy="58" rx="5" ry="3.6" fill="#7a2f35"/>';
        return '<path d="M42 55 Q50 64 58 55" stroke="#5b2a2a" stroke-width="2.4" fill="#fff" stroke-linecap="round"/>';
    }

    function extra(kind, s) {
        switch (kind) {
            case 'glasses':
                return '<g fill="none" stroke="#1f2933" stroke-width="2"><circle cx="41" cy="46" r="6"/><circle cx="59" cy="46" r="6"/><path d="M47 46 L53 46"/></g>';
            case 'scarf':
                return `<path d="M33 70 Q50 78 67 70 L66 76 Q50 84 34 76Z" fill="#e0a43a"/><rect x="56" y="74" width="7" height="13" rx="2" fill="#e0a43a"/>`;
            case 'earrings':
                return '<circle cx="27" cy="54" r="2.6" fill="#f2c14e"/><circle cx="73" cy="54" r="2.6" fill="#f2c14e"/>';
            case 'beard':
                return `<path d="M33 52 Q36 70 50 72 Q64 70 67 52 Q60 62 50 62 Q40 62 33 52Z" fill="${esc(s.hair_color)}"/>`;
            default:
                return '';
        }
    }

    window.ljAvatar = function (spec, mood, size) {
        const s = spec || {};
        const skin = esc(s.skin) || '#eac09a';
        const shirt = esc(s.shirt) || '#2f8fd8';
        const px = size || 64;
        return `<svg viewBox="0 0 100 100" width="${px}" height="${px}" role="img" aria-hidden="true" class="lj-avatar-svg">
<circle cx="50" cy="50" r="49" fill="${shirt}" opacity=".14"/>
<path d="M18 100 Q20 72 50 70 Q80 72 82 100Z" fill="${shirt}"/>
<rect x="44" y="60" width="12" height="12" rx="4" fill="${skin}"/>
${s.hair === 'long' ? hair('long', s.hair_color) : ''}
<circle cx="50" cy="44" r="23" fill="${skin}"/>
<ellipse cx="37" cy="53" rx="4" ry="2.4" fill="#e8737f" opacity=".35"/><ellipse cx="63" cy="53" rx="4" ry="2.4" fill="#e8737f" opacity=".35"/>
<circle cx="41" cy="46" r="2.7" fill="#1f2933"/><circle cx="59" cy="46" r="2.7" fill="#1f2933"/>
${s.hair === 'long' ? '' : hair(s.hair, s.hair_color)}
${s.hair === 'long' ? `<path d="M27 44 Q26 17 50 16 Q74 17 73 44 Q68 30 50 29 Q32 30 27 44Z" fill="${esc(s.hair_color)}"/>` : ''}
${mouth(mood)}
${extra(s.extra, s)}
</svg>`;
    };
})();
