"""Turn winners' writeups into structured, comparable learning cards.

- summarize_solution(): one writeup -> a card with fixed sections
  (validation, features, models, training, ensembling, what didn't work...).
- summarize_competition(): the cards of one competition -> what everyone
  did, what was distinctive, and the key lessons.

Grounding: the model may only use the writeup text. Any bullet containing a
number that does not appear in the writeup is dropped, so a card never shows
a made-up score, fold count or learning rate.
"""
import json
import re

from django.utils import timezone

# (key, label shown on the page, what to put there)
CARD_SECTIONS = [
    ('validation', 'Validation', 'how they split data / cross-validated, and how CV related to the leaderboard'),
    ('data', 'Data & preprocessing', 'data sources, cleaning, filtering, external data, pseudo-labels'),
    ('features', 'Features', 'feature engineering or input representation'),
    ('models', 'Models', 'architectures / algorithms and backbones'),
    ('training', 'Training tricks', 'losses, schedules, augmentations, stages, hyperparameters that mattered'),
    ('ensembling', 'Ensembling & post-processing', 'how models were combined, weights, post-processing, thresholds'),
    ('didnt_work', "What didn't work", 'things they tried that did not help'),
    ('compute', 'Compute', 'hardware and training time, if stated'),
]
_NUM = re.compile(r'\d+(?:[.,]\d+)*')


def _numbers(text: str) -> set:
    return {n.replace(',', '.').rstrip('.').lstrip('0') or '0' for n in _NUM.findall(text or '')}


def _grounded(bullets, known: set) -> list:
    """Keep short string bullets whose numbers all appear in the source."""
    out = []
    for b in bullets if isinstance(bullets, list) else []:
        if not isinstance(b, str) or not b.strip():
            continue
        if not _numbers(b) <= known:
            continue
        out.append(b.strip()[:300])
    return out[:6]


def _generate(prompt: str) -> dict:
    from content_generator.pipeline.agents.gemini_client import generate
    data = json.loads(generate(prompt))
    if isinstance(data, list):
        data = data[0] if data else {}
    return data if isinstance(data, dict) else {}


def summarize_solution(solution) -> dict | None:
    text = (solution.writeup_content or '').strip()
    if len(text) < 200:
        return None
    sections = '\n'.join(f'- "{k}": list of short bullets — {desc}' for k, _, desc in CARD_SECTIONS)
    prompt = f"""You are summarising a Kaggle competition solution writeup for someone learning ML.

COMPETITION: {solution.competition.name}
TEAM: {solution.team_name} (rank {solution.rank})

WRITEUP (the only source you may use):
{text[:11000]}

Return JSON with:
- "headline": ONE sentence: the single idea that most explains this result
{sections}

Rules:
- Use ONLY what the writeup says. If a section is not covered, return [] for it.
- Bullets: short (max ~20 words), specific (name the model, loss, fold scheme...).
- Copy numbers exactly as written; never estimate or add a number.
Return ONLY the JSON object."""
    data = _generate(prompt)
    known = _numbers(text)
    card = {key: _grounded(data.get(key), known) for key, _, _ in CARD_SECTIONS}
    headline = data.get('headline') if isinstance(data.get('headline'), str) else ''
    card['headline'] = headline.strip()[:300] if _numbers(headline) <= known else ''
    if not card['headline'] and not any(card[k] for k, _, _ in CARD_SECTIONS):
        return None
    return card


def summarize_competition(competition, solutions) -> dict | None:
    with_cards = [s for s in solutions if s.card]
    if not with_cards:
        return None
    teams = {s.team_name for s in with_cards}
    blocks = []
    for s in with_cards:
        lines = [f"#{s.rank} {s.team_name}: {s.card.get('headline', '')}"]
        for key, label, _ in CARD_SECTIONS:
            if s.card.get(key):
                lines.append(f"  {label}: " + '; '.join(s.card[key]))
        blocks.append('\n'.join(lines))
    prompt = f"""You compare the top solutions of one Kaggle competition for someone learning ML.

COMPETITION: {competition.name}
METRIC: {competition.evaluation_metric or 'not stated'}
DESCRIPTION: {(competition.description or '')[:800]}

SOLUTION SUMMARIES (the only source you may use):
{chr(10).join(blocks)}

Return JSON with:
- "challenge": 1-2 sentences: what made this competition hard
- "common": list of {{"idea": str, "teams": [team names]}} — approaches shared by 2+ teams (the baseline you need)
- "distinctive": list of {{"team": str, "idea": str}} — what one team did that others did not (the edge)
- "lessons": 3-5 short, transferable lessons for future competitions
Use only the summaries above. Team names must be copied exactly. Return ONLY the JSON object."""
    data = _generate(prompt)
    known = set()
    for b in blocks:
        known |= _numbers(b)

    def ok(text):
        return isinstance(text, str) and text.strip() and _numbers(text) <= known

    insights = {
        'challenge': data.get('challenge', '') if ok(data.get('challenge')) else '',
        'common': [
            {'idea': c['idea'].strip(), 'teams': [t for t in c.get('teams', []) if t in teams]}
            for c in data.get('common') or [] if isinstance(c, dict) and ok(c.get('idea'))
        ],
        'distinctive': [
            {'team': d['team'], 'idea': d['idea'].strip()}
            for d in data.get('distinctive') or []
            if isinstance(d, dict) and d.get('team') in teams and ok(d.get('idea'))
        ][:8],
        'lessons': [l.strip() for l in data.get('lessons') or [] if ok(l)][:5],
        'based_on': len(with_cards),
    }
    # "Common" means shared: keep ideas that at least two teams used.
    insights['common'] = [c for c in insights['common'] if len(set(c['teams'])) >= 2][:6]
    return insights


def summarize(competition, only_missing=True, log=print) -> tuple[int, bool]:
    """Fill cards for the competition's solutions, then its insights."""
    solutions = list(competition.solutions.order_by('rank'))
    made = 0
    for sol in solutions:
        if only_missing and sol.card:
            continue
        try:
            card = summarize_solution(sol)
        except Exception as exc:   # keep going; one bad writeup must not stop the rest
            log(f'  card failed for #{sol.rank} {sol.team_name}: {exc}')
            continue
        if card:
            sol.card, sol.card_generated_at = card, timezone.now()
            sol.save(update_fields=['card', 'card_generated_at'])
            made += 1
            log(f'  card: #{sol.rank} {sol.team_name}')
    refreshed = False
    if made or not competition.insights or not only_missing:
        try:
            insights = summarize_competition(competition, solutions)
        except Exception as exc:
            log(f'  insights failed: {exc}')
            insights = None
        if insights:
            competition.insights, competition.insights_generated_at = insights, timezone.now()
            competition.save(update_fields=['insights', 'insights_generated_at'])
            refreshed = True
    return made, refreshed
