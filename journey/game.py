"""The reward engine: XP, levels, coins, quests and achievements. No AI calls, ever.

Everything here is decided on the server from what the learner actually did (ReviewLog), and every reward
is a RewardEvent row with a unique key, so a repeated request, a refresh or a double click never pays twice.

What earns XP, and why
  * typed answer, checked by the server   10   (recall: the strongest practice)
  * one letter off ("almost")               6
  * multiple choice, checked by the server  5   (recognition)
  * self-graded flashcard                   3, 2 for "hard"
  * a due or new card answered wrongly      1   (showing up for the review still counts)
  * remembered after 7+ days               +5   (retention, the real goal of spaced repetition)
A card earns once per day at most: practising the same card again the same day keeps its best result and
adds nothing, so repeating material is never paid as if it were new learning. Answers stop paying after
DAILY_XP_CAP a day. Coins only come from milestones (lessons, quests, achievements, levels).
"""
import logging
import zlib
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from .answers import CLOSE, OK
from .models import Achievement, LessonPack, Progress, Quest, ReviewLog, RewardEvent, StudyItem

log = logging.getLogger(__name__)

DAILY_XP_CAP = getattr(settings, 'JOURNEY_DAILY_XP_CAP', 500)
RETAINED_DAYS = 7      # a correct review after this long counts as retention
MASTERED_DAYS = 21
LESSON_XP, LESSON_COINS = 50, 20
LEVEL_COINS = 25

# A self-graded or unverified answer counts as right from "hard" up; a checked one when the server said so.
GOOD = Q(verified=True, correct=True) | Q(verified=False, grade__gte=3)


# ── levels ────────────────────────────────────────────────────────────────

RANKS = [(1, 'Explorer'), (5, 'Apprentice'), (10, 'Practitioner'), (15, 'Scholar'), (20, 'Expert'), (30, 'Master')]


def xp_for_level(n):
    """Total XP needed to reach level n: 0, 100, 300, 600, 1000, ... (each level needs 100 more than the last)."""
    return 50 * (n - 1) * n


def level_for(xp):
    n = 1
    while xp >= xp_for_level(n + 1):
        n += 1
    return n


def rank_for(level):
    name = RANKS[0][1]
    for at, label in RANKS:
        if level >= at:
            name = label
    return name


def totals(user):
    t = RewardEvent.objects.filter(user=user).aggregate(xp=Sum('xp'), coins=Sum('coins'))
    return t['xp'] or 0, t['coins'] or 0


def active_days(user, since=None):
    """Days with practice: answered cards, or a conversation finished in town."""
    logs = ReviewLog.objects.filter(user=user)
    talks = RewardEvent.objects.filter(user=user, kind=RewardEvent.SCENE)
    if since:
        logs = logs.filter(at__gte=since)
        talks = talks.filter(day__gte=timezone.localtime(since).date())
    return {timezone.localtime(at).date() for at in logs.values_list('at', flat=True)} | set(talks.values_list('day', flat=True))


def streak(user, days=None):
    """Days in a row with practice. A day with no practice yet still counts up to yesterday."""
    days = days if days is not None else active_days(user, timezone.now() - timedelta(days=400))
    n, day = 0, timezone.localdate()
    if day not in days:
        day -= timedelta(days=1)
    while day in days:
        n += 1
        day -= timedelta(days=1)
    return n


def status(user):
    """What the learner sees in the header: level, the XP bar, coins and the streak."""
    xp, coins = totals(user)
    level = level_for(xp)
    lo, hi = xp_for_level(level), xp_for_level(level + 1)
    today = RewardEvent.objects.filter(user=user, day=timezone.localdate(), xp__gt=0).aggregate(s=Sum('xp'))['s'] or 0
    return {'xp': xp, 'coins': coins, 'level': level, 'rank': rank_for(level), 'into': xp - lo, 'span': hi - lo,
            'pct': round(100 * (xp - lo) / (hi - lo)), 'to_next': hi - xp, 'streak': streak(user), 'today_xp': today,
            'cap': DAILY_XP_CAP}


# ── granting ──────────────────────────────────────────────────────────────

def grant(user, kind, key, xp=0, coins=0, note='', group=None):
    """Record a reward once. Returns the new event, or None when this key was already paid."""
    try:
        with transaction.atomic():
            return RewardEvent.objects.create(user=user, kind=kind, key=key, xp=xp, coins=coins, note=note[:160],
                                               group=group, day=timezone.localdate())
    except IntegrityError:
        return None


def answer_xp(entry, verdict, prev_interval):
    """XP for one answer (see the module docstring)."""
    if entry.verified:
        good = verdict in (OK, CLOSE)
        if verdict == OK:
            xp = 10 if entry.mode == ReviewLog.TYPE else 5
        elif verdict == CLOSE:
            xp = 6
        else:
            xp = 1 if (entry.scheduled or entry.first) else 0
    else:
        good = entry.grade >= 3
        xp = {5: 3, 4: 3, 3: 2}.get(entry.grade, 1 if (entry.scheduled or entry.first) else 0)
    if good and entry.scheduled and prev_interval >= RETAINED_DAYS:
        xp += 5
    return xp


def _pay_answer(user, item, xp):
    """Keep the best result per card per day, within the daily cap. Returns the XP added now."""
    if xp <= 0:
        return 0
    day = timezone.localdate()
    key = f'answer:{item.pk}:{day.isoformat()}'
    with transaction.atomic():
        RewardEvent.objects.get_or_create(user=user, key=key, defaults={
            'kind': RewardEvent.ANSWER, 'xp': 0, 'day': day, 'group': item.pack.group, 'note': item.front[:160]})
        event = RewardEvent.objects.select_for_update().get(user=user, key=key)
        if xp <= event.xp:
            return 0
        others = (RewardEvent.objects.filter(user=user, kind=RewardEvent.ANSWER, day=day).exclude(pk=event.pk)
                  .aggregate(s=Sum('xp'))['s'] or 0)
        best = min(xp, event.xp + max(0, DAILY_XP_CAP - others - event.xp))
        added = best - event.xp
        if added > 0:
            event.xp = best
            event.save(update_fields=['xp'])
        return max(0, added)


def _lesson_done(user, item):
    """A lesson is complete once every one of its cards has been answered right at least once."""
    pack = item.pack
    cards = pack.items.filter(kind__in=StudyItem.REVIEWABLE)
    total = cards.count()
    if not total or pack.status != LessonPack.PUBLISHED:
        return None
    right = ReviewLog.objects.filter(GOOD, user=user, item__in=cards).values('item').distinct().count()
    if right < total:
        return None
    return grant(user, RewardEvent.LESSON, f'lesson:{pack.pk}', LESSON_XP, LESSON_COINS, pack.title, pack.group)


def on_answer(user, entry, verdict, prev_interval):
    """Everything an answer earns. Never raises: a reward problem must not break practice."""
    try:
        return _on_answer(user, entry, verdict, prev_interval)
    except Exception:   # noqa: BLE001 - logged, and practice goes on without the reward
        log.exception('LearningJourney reward failed for answer %s', entry.pk)
        return None


def _on_answer(user, entry, verdict, prev_interval):
    xp_before, _ = totals(user)
    out = {'xp': 0, 'coins': 0, 'quests': [], 'unlocked': [], 'lesson': None, 'level_up': None}
    out['xp'] += _pay_answer(user, entry.item, answer_xp(entry, verdict, prev_interval))
    good = (verdict in (OK, CLOSE)) if entry.verified else entry.grade >= 3
    if good:
        lesson = _lesson_done(user, entry.item)
        if lesson:
            out['lesson'] = entry.item.pack.title
            out['xp'] += lesson.xp
            out['coins'] += lesson.coins
    for q in check_quests(user):
        out['quests'].append(q.title)
        out['xp'] += q.xp
        out['coins'] += q.coins
    for a in check_achievements(user):
        out['unlocked'].append({'name': a['name'], 'icon': a['icon'], 'tier': a['tier']})
        out['xp'] += a['xp']
        out['coins'] += a['coins']
    out['coins'] += check_levels(user, xp_before)
    s = status(user)
    if s['level'] > level_for(xp_before):
        out['level_up'] = {'level': s['level'], 'rank': s['rank']}
    out.update(level=s['level'], pct=s['pct'], today_xp=s['today_xp'], total_coins=s['coins'], to_next=s['to_next'])
    return out


def on_scene(user, key, title, xp, coins, group=None):
    """A finished conversation in the town: paid once a day. Returns the same summary as on_answer."""
    try:
        xp_before, _ = totals(user)
        out = {'xp': 0, 'coins': 0, 'quests': [], 'unlocked': [], 'lesson': None, 'level_up': None, 'paid': False}
        event = grant(user, RewardEvent.SCENE, f'scene:{key}:{timezone.localdate().isoformat()}', xp, coins, title, group)
        if event:
            out.update(xp=xp, coins=coins, paid=True)
        for q in check_quests(user):
            out['quests'].append(q.title)
            out['xp'] += q.xp
            out['coins'] += q.coins
        for a in check_achievements(user):
            out['unlocked'].append({'name': a['name'], 'icon': a['icon'], 'tier': a['tier']})
            out['xp'] += a['xp']
            out['coins'] += a['coins']
        out['coins'] += check_levels(user, xp_before)
        s = status(user)
        if s['level'] > level_for(xp_before):
            out['level_up'] = {'level': s['level'], 'rank': s['rank']}
        out.update(level=s['level'], pct=s['pct'], today_xp=s['today_xp'], total_coins=s['coins'], to_next=s['to_next'])
        return out
    except Exception:   # noqa: BLE001 - logged; the conversation still ends normally
        log.exception('LearningJourney scene reward failed for %s', key)
        return None


def check_levels(user, xp_before):
    """Coins for each level reached since xp_before. Returns the coins paid."""
    xp, _ = totals(user)
    paid = 0
    for n in range(level_for(xp_before) + 1, level_for(xp) + 1):
        if grant(user, RewardEvent.LEVEL, f'level:{n}', 0, LEVEL_COINS, f'Reached level {n}'):
            paid += LEVEL_COINS
    return paid


# ── quests ────────────────────────────────────────────────────────────────

DAILY_XP, DAILY_COINS = 30, 10
WEEKLY_XP, WEEKLY_COINS = 120, 40

QUEST_TEXT = {
    'due': ('Review {t} due cards', 'Due cards are the ones you are about to forget. Reviewing them now keeps them.'),
    'new': ('Learn {t} new cards', 'New cards from your lessons, a few at a time, so they stick.'),
    'recall': ('Type {t} answers correctly', 'Writing the answer yourself is the strongest kind of practice.'),
    'weak': ('Get {t} weak cards right', 'Cards you have forgotten twice or more. The mistake notebook is the quickest way.'),
    'forms': ('Get {t} verb forms right', 'Conjugation drills from the verb tables in your lessons.'),
    'subject': ('Practise {t} cards in {name}', 'You have not practised it for a few days.'),
    'cards': ('Practise {t} cards', 'Any practice counts: a short session every day beats a long one now and then.'),
    'w_days': ('Practise on {t} different days', 'Spacing practice over the week is what makes memories last.'),
    'w_recall': ('Type {t} answers correctly this week', 'Recall practice, spread over the week.'),
    'w_lesson': ('Finish a lesson this week', 'Answer every card of one lesson correctly at least once.'),
    'talk': ('Have a conversation in town', 'The café, the bakery, the market or the bus stop: any one counts.'),
    'w_talks': ('Talk in {t} different places this week', 'Each place has its own words and phrases.'),
}


def _reviewable(user):
    return StudyItem.objects.filter(kind__in=StudyItem.REVIEWABLE, pack__status=LessonPack.PUBLISHED,
                                    pack__group__memberships__user=user)


def _week_start(day):
    return day - timedelta(days=day.weekday())


def town_user(user):
    """Someone who has been to the town (picked a character there) or learns a language the town speaks."""
    from . import scenes
    from .models import LearnerProfile, StudyGroup
    if not getattr(settings, 'JOURNEY_TOWN', False):   # no town, no town quests
        return False
    avatar = LearnerProfile.objects.filter(user=user).values_list('avatar', flat=True).first() or {}
    return ((isinstance(avatar, dict) and 'sprite' in avatar)
            or StudyGroup.objects.filter(memberships__user=user, subject__in=scenes.LANGUAGE_SUBJECTS).exists())


def _daily_candidates(user, day):
    items = _reviewable(user)
    now = timezone.now()
    due = Progress.objects.filter(user=user, due__lte=now, item__in=items).count()
    unseen = items.exclude(progress__user=user).count()
    new_per_day = getattr(settings, 'JOURNEY_NEW_PER_DAY', 20)
    weak = Progress.objects.filter(user=user, lapses__gte=2, item__in=items).count()
    seen = Progress.objects.filter(user=user, item__in=items)
    typable = seen.filter(item__kind__in=[StudyItem.WORD, StudyItem.PHRASE, StudyItem.SENTENCE,
                                          StudyItem.CONCEPT, StudyItem.TABLE]).count()
    tables = seen.filter(item__kind=StudyItem.TABLE).exists()
    first, rest = [], []
    if due >= 3:
        first.append(('due', min(15, due), None))
    if town_user(user):
        first.append(('talk', 1, None))
    if unseen >= 3:
        rest.append(('new', min(10, unseen, new_per_day), None))
    if typable >= 5:
        rest.append(('recall', 5, None))
    if weak:
        rest.append(('weak', min(3, weak), None))
    if tables:
        rest.append(('forms', 5, None))
    from .models import StudyGroup
    quiet = now - timedelta(days=3)
    for g in StudyGroup.objects.filter(memberships__user=user, packs__status=LessonPack.PUBLISHED).distinct():
        if (Progress.objects.filter(user=user, item__pack__group=g).exists()
                and not ReviewLog.objects.filter(user=user, item__pack__group=g, at__gte=quiet).exists()):
            rest.append(('subject', 5, g))
            break
    # The same learner gets a different mix on different days, but the same mix all day.
    rest.sort(key=lambda c: zlib.crc32(f'{c[0]}:{day.isoformat()}:{user.pk}'.encode()))
    picked = (first + rest)[:3]
    if len(picked) < 2 and items.exists():
        picked.append(('cards', 10, None))
    return picked


def _weekly_candidates(user):
    items = _reviewable(user)
    talks = [('w_talks', 3, None)] if town_user(user) else []
    if not items.exists():
        return talks
    picked = [('w_days', 5, None)] + talks[:1]
    done = set(RewardEvent.objects.filter(user=user, kind=RewardEvent.LESSON).values_list('key', flat=True))
    open_lessons = [p for p in LessonPack.objects.filter(group__memberships__user=user, status=LessonPack.PUBLISHED)
                    .values_list('pk', flat=True) if f'lesson:{p}' not in done]
    if len(picked) < 2:
        picked.append(('w_lesson', 1, None) if open_lessons else ('w_recall', 40, None))
    return picked


def _make(user, period, starts, candidates):
    xp, coins = (DAILY_XP, DAILY_COINS) if period == Quest.DAY else (WEEKLY_XP, WEEKLY_COINS)
    for code, target, group in candidates:
        title, detail = QUEST_TEXT[code]
        Quest.objects.get_or_create(user=user, period=period, starts=starts, code=code, defaults={
            'title': title.format(t=target, name=group.name if group else ''), 'detail': detail,
            'target': target, 'xp': xp, 'coins': coins, 'group': group})


def add_town_quests(user):
    """Someone who just arrived in town gets its quests today, even if today's quests were made before."""
    day = timezone.localdate()
    _make(user, Quest.DAY, day, [('talk', 1, None)])
    week = _week_start(day)
    if not Quest.objects.filter(user=user, period=Quest.WEEK, starts=week, code='w_talks').exists():
        _make(user, Quest.WEEK, week, [('w_talks', 3, None)])


def quests_for(user):
    """Today's quests and this week's, made the first time they are asked for. Each with live progress."""
    day = timezone.localdate()
    week = _week_start(day)
    if not Quest.objects.filter(user=user, period=Quest.DAY, starts=day).exists():
        _make(user, Quest.DAY, day, _daily_candidates(user, day))
    if not Quest.objects.filter(user=user, period=Quest.WEEK, starts=week).exists():
        _make(user, Quest.WEEK, week, _weekly_candidates(user))
    quests = list(Quest.objects.filter(user=user).filter(Q(period=Quest.DAY, starts=day) | Q(period=Quest.WEEK, starts=week))
                  .select_related('group'))
    for q in quests:
        q.progress = min(q.target, quest_progress(user, q))
        q.pct = round(100 * q.progress / q.target) if q.target else 0
    return quests


def _since(q):
    start = timezone.make_aware(datetime.combine(q.starts, time.min))
    return start, start + timedelta(days=1 if q.period == Quest.DAY else 7)


def quest_progress(user, q):
    start, end = _since(q)
    logs = ReviewLog.objects.filter(user=user, at__gte=start, at__lt=end)
    distinct = lambda qs: qs.values('item').distinct().count()   # noqa: E731
    if q.code == 'due':
        return distinct(logs.filter(scheduled=True))
    if q.code == 'new':
        return distinct(logs.filter(first=True))
    if q.code in ('recall', 'w_recall'):
        return distinct(logs.filter(mode=ReviewLog.TYPE, verified=True, correct=True))
    if q.code == 'weak':
        return distinct(logs.filter(GOOD, item__progress__user=user, item__progress__lapses__gte=2))
    if q.code == 'forms':
        return logs.filter(GOOD, item__kind=StudyItem.TABLE).count()
    if q.code == 'subject':
        return distinct(logs.filter(item__pack__group=q.group_id))
    if q.code == 'cards':
        return distinct(logs)
    if q.code == 'w_days':
        return len({timezone.localtime(at).date() for at in logs.values_list('at', flat=True)})
    if q.code in ('talk', 'w_talks'):
        keys = RewardEvent.objects.filter(user=user, kind=RewardEvent.SCENE, created_at__gte=start,
                                          created_at__lt=end).values_list('key', flat=True)
        return len({k.split(':')[1] for k in keys})
    if q.code == 'w_lesson':
        return RewardEvent.objects.filter(user=user, kind=RewardEvent.LESSON, created_at__gte=start, created_at__lt=end).count()
    return 0


def check_quests(user, quests=None):
    """Mark finished quests done and pay them, once. Returns the quests finished now.
    Pass the result of quests_for when you already have it, to save counting progress twice."""
    finished = []
    for q in quests if quests is not None else quests_for(user):
        if q.done_at or q.progress < q.target:
            continue
        if grant(user, RewardEvent.QUEST, f'quest:{q.pk}', q.xp, q.coins, q.title, q.group):
            q.done_at = timezone.now()
            Quest.objects.filter(pk=q.pk, done_at__isnull=True).update(done_at=q.done_at)
            finished.append(q)
    return finished


# ── achievements ──────────────────────────────────────────────────────────

def _flawless(user):
    """Conversations where every reply was right the first time: the reward shows it (see views.api_scene_answer)."""
    from . import scenes
    full = {key: scenes.XP_PER_TURN * len(sc['turns']) + 2 for (key, _), sc in scenes.SCENES.items()}
    return sum(1 for k, xp in RewardEvent.objects.filter(user=user, kind=RewardEvent.SCENE).values_list('key', 'xp')
               if xp >= full.get(k.split(':')[1], 10 ** 6))


def _good_distinct(user, **kw):
    return ReviewLog.objects.filter(GOOD, user=user, **kw).values('item').distinct().count()


METRICS = {
    'answers': lambda u: ReviewLog.objects.filter(user=u).count(),
    'lessons': lambda u: RewardEvent.objects.filter(user=u, kind=RewardEvent.LESSON).count(),
    'recalled': lambda u: ReviewLog.objects.filter(user=u, mode=ReviewLog.TYPE, verified=True, correct=True)
                                  .values('item').distinct().count(),
    'words': lambda u: _good_distinct(u, item__kind=StudyItem.WORD),
    'forms': lambda u: ReviewLog.objects.filter(GOOD, user=u, item__kind=StudyItem.TABLE).count(),
    'mastered': lambda u: Progress.objects.filter(user=u, interval__gte=MASTERED_DAYS).count(),
    'recovered': lambda u: Progress.objects.filter(user=u, lapses__gte=1, interval__gte=6).count(),
    'streak': lambda u: streak(u),
    'consistent': lambda u: len(active_days(u, timezone.now() - timedelta(days=30))),
    'subjects': lambda u: ReviewLog.objects.filter(user=u).values('item__pack__group').distinct().count(),
    'level': lambda u: level_for(totals(u)[0]),
    'talks': lambda u: RewardEvent.objects.filter(user=u, kind=RewardEvent.SCENE).count(),
    'places': lambda u: len({k.split(':')[1] for k in RewardEvent.objects.filter(user=u, kind=RewardEvent.SCENE)
                                                                     .values_list('key', flat=True)}),
    'flawless': lambda u: _flawless(u),
}

# code: (name, what it means, Font Awesome icon, tier, metric, threshold)
ACHIEVEMENTS = {
    'first_answer': ('First step', 'Answer your first card.', 'fa-shoe-prints', 'bronze', 'answers', 1),
    'lesson_1': ('Lesson complete', 'Get every card of a lesson right at least once.', 'fa-book-open', 'bronze', 'lessons', 1),
    'lesson_10': ('Ten lessons', 'Complete ten lessons.', 'fa-book-bookmark', 'silver', 'lessons', 10),
    'recall_25': ('Active recall', 'Type 25 different answers correctly.', 'fa-keyboard', 'bronze', 'recalled', 25),
    'recall_250': ('Strong recall', 'Type 250 different answers correctly.', 'fa-keyboard', 'silver', 'recalled', 250),
    'recall_1000': ('Total recall', 'Type 1,000 different answers correctly.', 'fa-keyboard', 'gold', 'recalled', 1000),
    'words_50': ('Vocabulary explorer', 'Know 50 words.', 'fa-spell-check', 'bronze', 'words', 50),
    'words_250': ('Vocabulary builder', 'Know 250 words.', 'fa-spell-check', 'silver', 'words', 250),
    'words_1000': ('Thousand words', 'Know 1,000 words.', 'fa-spell-check', 'gold', 'words', 1000),
    'forms_50': ('Conjugator', 'Get 50 verb forms right.', 'fa-table-cells', 'silver', 'forms', 50),
    'mastered_25': ('Long-term memory', 'Keep 25 cards for three weeks or more.', 'fa-brain', 'silver', 'mastered', 25),
    'mastered_250': ('Deep memory', 'Keep 250 cards for three weeks or more.', 'fa-brain', 'gold', 'mastered', 250),
    'recovered_10': ('Comeback', 'Rebuild 10 cards you had forgotten.', 'fa-rotate', 'silver', 'recovered', 10),
    'streak_3': ('Three days', 'Practise three days in a row.', 'fa-fire', 'bronze', 'streak', 3),
    'streak_7': ('One week', 'Practise seven days in a row.', 'fa-fire', 'silver', 'streak', 7),
    'streak_30': ('One month', 'Practise thirty days in a row.', 'fa-fire', 'gold', 'streak', 30),
    'consistent_20': ('Consistent learner', 'Practise on 20 of the last 30 days.', 'fa-calendar-check', 'silver', 'consistent', 20),
    'subjects_3': ('Polymath', 'Practise three different subjects.', 'fa-shapes', 'silver', 'subjects', 3),
    'level_10': ('Practitioner', 'Reach level 10.', 'fa-mountain', 'silver', 'level', 10),
    'level_20': ('Expert', 'Reach level 20.', 'fa-mountain-sun', 'gold', 'level', 20),
    'talk_1': ('First conversation', 'Finish a conversation in town.', 'fa-comments', 'bronze', 'talks', 1),
    'talk_places': ('Local', 'Finish a conversation in four different places in town.', 'fa-map-location-dot', 'silver', 'places', 4),
    'talk_flawless': ('Fluent moment', 'Get every reply of a conversation right the first time.', 'fa-star', 'silver', 'flawless', 1),
    'talk_30': ('Regular', 'Finish 30 conversations in town (one a day per place counts).', 'fa-mug-hot', 'gold', 'talks', 30),
}
ACHIEVEMENT_REWARD = {'bronze': (20, 15), 'silver': (50, 40), 'gold': (150, 100)}   # tier: (xp, coins)


def _info(code):
    name, desc, icon, tier, metric, at = ACHIEVEMENTS[code]
    xp, coins = ACHIEVEMENT_REWARD[tier]
    return {'code': code, 'name': name, 'desc': desc, 'icon': icon, 'tier': tier, 'metric': metric, 'at': at,
            'xp': xp, 'coins': coins}


def all_metrics(user):
    """Every achievement metric at once: five queries, whatever the number of achievements."""
    logs = ReviewLog.objects.filter(user=user).aggregate(
        answers=Count('pk'),
        recalled=Count('item', distinct=True, filter=Q(mode=ReviewLog.TYPE, verified=True, correct=True)),
        words=Count('item', distinct=True, filter=GOOD & Q(item__kind=StudyItem.WORD)),
        forms=Count('pk', filter=GOOD & Q(item__kind=StudyItem.TABLE)),
        subjects=Count('item__pack__group', distinct=True))
    prog = Progress.objects.filter(user=user).aggregate(
        mastered=Count('pk', filter=Q(interval__gte=MASTERED_DAYS)),
        recovered=Count('pk', filter=Q(lapses__gte=1, interval__gte=6)))
    events = list(RewardEvent.objects.filter(user=user).values_list('kind', 'key', 'xp'))
    days = active_days(user, timezone.now() - timedelta(days=400))
    from . import scenes
    full = {key: scenes.XP_PER_TURN * len(sc['turns']) + 2 for (key, _), sc in scenes.SCENES.items()}
    talks = [(k.split(':')[1], xp) for kind, k, xp in events if kind == RewardEvent.SCENE]
    month = timezone.localdate() - timedelta(days=30)
    return {**logs, **prog,
            'lessons': sum(1 for kind, _, _ in events if kind == RewardEvent.LESSON),
            'level': level_for(sum(xp for _, _, xp in events)),
            'streak': streak(user, days), 'consistent': sum(1 for d in days if d > month),
            'talks': len(talks), 'places': len({k for k, _ in talks}),
            'flawless': sum(1 for k, xp in talks if xp >= full.get(k, 10 ** 6))}


def check_achievements(user):
    """Unlock what the learner has earned. Only metrics of locked achievements are counted."""
    have = set(Achievement.objects.filter(user=user).values_list('code', flat=True))
    if have >= set(ACHIEVEMENTS):
        return []
    values, new = all_metrics(user), []
    for code in ACHIEVEMENTS:
        if code in have:
            continue
        a = _info(code)
        if values[a['metric']] < a['at']:
            continue
        try:
            with transaction.atomic():
                Achievement.objects.create(user=user, code=code)
        except IntegrityError:
            continue
        grant(user, RewardEvent.ACHIEVEMENT, f'achievement:{code}', a['xp'], a['coins'], a['name'])
        new.append(a)
    return new


def achievements(user):
    """Every achievement, unlocked or not, with progress towards it."""
    have = dict(Achievement.objects.filter(user=user).values_list('code', 'unlocked_at'))
    values, out = all_metrics(user), []
    for code in ACHIEVEMENTS:
        if code.startswith('talk_') and code not in have and not getattr(settings, 'JOURNEY_TOWN', False):
            continue   # town achievements are only listed while the town is open
        a = _info(code)
        a['value'] = min(values[a['metric']], a['at'])
        a['pct'] = round(100 * a['value'] / a['at'])
        a['unlocked_at'] = have.get(code)
        out.append(a)
    out.sort(key=lambda a: (a['unlocked_at'] is None, -(a['pct'])))
    return out


def unlocked(user):
    return set(Achievement.objects.filter(user=user).values_list('code', flat=True))


# ── how well things are known ─────────────────────────────────────────────

def knowledge(user, items):
    """Cards at each depth of knowing: seen, recognised (picked or self-graded right), recalled (typed right,
    checked by the server) and retained (still remembered three weeks on). Each stage is a subset of seeing."""
    seen = Progress.objects.filter(user=user, item__in=items).aggregate(
        seen=Count('pk'), retained=Count('pk', filter=Q(interval__gte=MASTERED_DAYS)))
    logs = ReviewLog.objects.filter(user=user, item__in=items).aggregate(
        recognised=Count('item', distinct=True, filter=GOOD),
        recalled=Count('item', distinct=True, filter=Q(mode=ReviewLog.TYPE, verified=True, correct=True)))
    return {'total': items.count(), **seen, **logs}


def history(user, n=12):
    return list(RewardEvent.objects.filter(user=user).exclude(xp=0, coins=0).select_related('group')[:n])
