"""LearningJourney pages and the small JSON API used by the practice screen.

Lessons live in a StudyGroup. A personal one (is_personal) is a private learning space;
a shared one is a class group with an invite code. Everything else works the same for both.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Case, Count, Q, Sum, When
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import answers, extract, game, pipeline, scenes, srs, subjects, town_decor, translate
from .models import (HELPER_LANGUAGES, HELPER_NAMES, LEVELS, RTL_LANGUAGES, LearnerProfile, LessonPack, Membership,
                     Progress, Quest, ReviewLog, RewardEvent, StudyGroup, StudyItem)
from .models import Achievement

NEW_PER_DAY = getattr(settings, 'JOURNEY_NEW_PER_DAY', 20)
DAILY_IMAGES = getattr(settings, 'JOURNEY_DAILY_IMAGES', 30)
DAILY_PACKS = getattr(settings, 'JOURNEY_DAILY_PACKS', 10)
MAX_SPACES = 20
BATCH = 30
MASTERED_DAYS = 21   # "mastered": the next review is three weeks or more away
# New cards: words first, then sentences built from them, then the rest.
KIND_ORDER = Case(When(kind=StudyItem.WORD, then=0), When(kind=StudyItem.CONCEPT, then=0),
                  When(kind=StudyItem.SENTENCE, then=1), default=2)
LEVEL_NAMES = dict(LEVELS)


# ── helpers ──────────────────────────────────────────────────────────────────

def _group_for(user, code):
    group = get_object_or_404(StudyGroup, invite_code=code.upper())
    if not group.is_member(user):
        raise Http404('Not a member of this group')
    return group


def _pack_for(user, pk):
    pack = get_object_or_404(LessonPack.objects.select_related('group'), pk=pk)
    if not pack.group.is_member(user):
        raise Http404('Not a member of this group')
    return pack


def _start_of_today():
    return timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)


def _reviewable(user, group=None):
    qs = StudyItem.objects.filter(kind__in=StudyItem.REVIEWABLE, pack__status=LessonPack.PUBLISHED,
                                  pack__group__memberships__user=user)
    if group is not None:
        qs = qs.filter(pack__group=group)
    return qs


def _new_left_today(user):
    started = Progress.objects.filter(user=user, introduced_at__gte=_start_of_today()).count()
    return max(0, NEW_PER_DAY - started)


def due_counts(user, group=None):
    now = timezone.now()
    items = _reviewable(user, group)
    due = Progress.objects.filter(user=user, due__lte=now, item__in=items).count()
    unseen = items.exclude(progress__user=user).count()
    return {'due': due, 'new': min(unseen, _new_left_today(user)), 'unseen': unseen}


def _card(item, lang=''):
    data = item.data or {}
    return {
        'id': item.pk, 'kind': item.kind, 'front': item.front, 'form': item.form_in_text,
        'grammar': item.grammar, 'en': item.meaning_en, 'extra': item.helper(lang), 'example': item.example,
        'body': item.body, 'cloze': data.get('cloze', ''), 'options': data.get('options', []),
        'answer': data.get('answer', 0), 'quote': data.get('quote', ''), 'source': item.source_ref,
        'rows': data.get('rows', []),
        'pack': item.pack.title, 'speech': item.pack.group.subject_info.speech_lang,
        'tl': item.pack.group.subject_info.text_lang, 'confidence': item.confidence,
    }


def _language(request):
    lang = LearnerProfile.language_of(request.user)
    return {'lang': lang, 'lang_name': HELPER_NAMES.get(lang, ''), 'lang_dir': 'rtl' if lang in RTL_LANGUAGES else 'ltr'}


def _with_helper(items, lang):
    """Attach the second-language text for templates (empty when none chosen or not translated yet)."""
    for i in items:
        i.extra = i.helper(lang)
        i.extra_body = i.helper(lang, 'body')
    return items


def _visible_packs(user):
    return (LessonPack.objects.filter(group__memberships__user=user)
            .filter(Q(status=LessonPack.PUBLISHED) | Q(created_by=user) |
                    Q(group__memberships__user=user, group__memberships__role=Membership.OWNER))
            .distinct())


def progress_summary(user, group=None):
    """Transparent indicators, no guessing: counts that each have a one-line definition on the page."""
    items = _reviewable(user, group)
    rows = Progress.objects.filter(user=user, item__in=items)
    today = _start_of_today()
    logs = ReviewLog.objects.filter(user=user)
    if group is not None:
        logs = logs.filter(item__pack__group=group)
    per_day = {}
    for at in logs.filter(at__gte=today - timedelta(days=365)).values_list('at', flat=True):
        d = timezone.localtime(at).date()
        per_day[d] = per_day.get(d, 0) + 1
    week = [{'day': today - timedelta(days=d), 'n': per_day.get((today - timedelta(days=d)).date(), 0)}
            for d in range(6, -1, -1)]
    streak, day = 0, today.date()
    if not per_day.get(day):   # nothing yet today: the streak still counts up to yesterday
        day -= timedelta(days=1)
    while per_day.get(day):
        streak += 1
        day -= timedelta(days=1)
    top = max([w['n'] for w in week] + [1])
    for w in week:
        w['pct'] = round(100 * w['n'] / top)
    return {
        'total': items.count(), 'seen': rows.count(),
        'mastered': rows.filter(interval__gte=MASTERED_DAYS).count(),
        'weak': rows.filter(lapses__gte=2).count(),
        'produced': logs.filter(mode=ReviewLog.TYPE, correct=True, item__in=items).values('item').distinct().count(),
        'week': week, 'streak': streak, 'week_total': sum(w['n'] for w in week),
    }


def _n(n, one, many):
    return f'{n} {one if n == 1 else many}'


def recommendations(user, spaces):
    """What to do today, from simple rules a learner can see the reason for."""
    tips = []
    counts = due_counts(user)
    if counts['due']:
        tips.append({'icon': 'fa-layer-group', 'text': _n(counts['due'], 'card is', 'cards are') + ' due for review.',
                     'url': 'journey:review', 'cta': 'Review now'})
    weak = Progress.objects.filter(user=user, lapses__gte=2, item__pack__status=LessonPack.PUBLISHED,
                                   item__pack__group__memberships__user=user).count()
    if weak:
        tips.append({'icon': 'fa-book-medical', 'text': _n(weak, 'card', 'cards') + ' you have forgotten twice or more.',
                     'url': 'journey:mistakes', 'cta': 'Practise mistakes'})
    if counts['new'] and not counts['due']:
        tips.append({'icon': 'fa-seedling', 'text': _n(counts['new'], 'new card is', 'new cards are') + ' ready to learn.',
                     'url': 'journey:review', 'cta': 'Learn new cards'})
    week_ago = timezone.now() - timedelta(days=7)
    recent = set(ReviewLog.objects.filter(user=user, at__gte=week_ago, item__pack__group__in=spaces)
                 .values_list('item__pack__group', flat=True).distinct())
    for s in spaces:
        if s.n_packs and s.pk not in recent:
            tips.append({'icon': 'fa-clock-rotate-left', 'text': f'You have not practised {s.name} for a week.',
                         'href': s.get_absolute_url(), 'cta': 'Open'})
    drafts = LessonPack.objects.filter(created_by=user, status=LessonPack.DRAFT).count()
    if drafts:
        first = LessonPack.objects.filter(created_by=user, status=LessonPack.DRAFT).order_by('-created_at').first()
        tips.append({'icon': 'fa-pen-to-square', 'text': _n(drafts, 'lesson waits', 'lessons wait') + ' for your check.',
                     'href': first.get_absolute_url(), 'cta': 'Check'})
    return tips[:4]


def _spaces_of(user, personal):
    return (StudyGroup.objects.filter(memberships__user=user, is_personal=personal)
            .annotate(n_packs=Count('packs', filter=Q(packs__status=LessonPack.PUBLISHED), distinct=True),
                      n_members=Count('memberships', distinct=True)))


def _new_space(user, subject_key, name='', level=''):
    subject = subjects.get(subject_key)
    space = StudyGroup.objects.create(name=(name or subject.name)[:80], subject=subject.key, created_by=user,
                                      is_personal=True, level=level if level in LEVEL_NAMES else '')
    Membership.objects.create(group=space, user=user, role=Membership.OWNER)
    return space


# ── home, spaces and groups ──────────────────────────────────────────────────

def _subjects_of(user):
    """Every space and group the learner is in, as subject cards, personal ones first."""
    places = list(StudyGroup.objects.filter(memberships__user=user)
                  .annotate(n_packs=Count('packs', filter=Q(packs__status=LessonPack.PUBLISHED), distinct=True),
                            n_members=Count('memberships', distinct=True))
                  .order_by('-is_personal', 'name'))
    for s in places:
        s.counts = due_counts(user, s)
        s.info = s.subject_info
        s.todo = (s.packs.filter(Q(created_by=user) | Q(group__memberships__user=user, group__memberships__role=Membership.OWNER))
                  .filter(status__in=[LessonPack.DRAFT, LessonPack.EMPTY, LessonPack.FAILED]).distinct().count())
    return places


@login_required
def home(request):
    places = _subjects_of(request.user)
    return render(request, 'journey/home.html', {
        'places': places, 'counts': due_counts(request.user),
        'tips': recommendations(request.user, [p for p in places if p.is_personal]),
        'subject_choices': subjects.SUBJECTS.values(), 'default_subject': subjects.DEFAULT, 'levels': LEVELS,
        'nav': 'home', **_game_context(request.user),
    })


def _game_context(user, quests=True):
    status = game.status(user)
    out = {'me': status}
    if quests:
        out['quests'] = game.quests_for(user)
        if game.check_quests(user, out['quests']):   # pays any quest finished since the last answer
            out['me'] = game.status(user)
    return out


@login_required
def progress(request):
    places = _subjects_of(request.user)
    for s in places:
        s.progress = progress_summary(request.user, s)
    for s in places:
        s.knowledge = game.knowledge(request.user, _reviewable(request.user, s))
    return render(request, 'journey/progress.html', {
        'progress': progress_summary(request.user), 'places': places,
        'knowledge': game.knowledge(request.user, _reviewable(request.user)),
        'achievements': game.achievements(request.user), 'history': game.history(request.user),
        **_game_context(request.user, quests=False),
        'mistakes': Progress.objects.filter(user=request.user, lapses__gt=0).count(),
        'helper_choices': HELPER_LANGUAGES, 'nav': 'progress', **_language(request),
    })


@login_required
@require_POST
def set_language(request):
    lang = request.POST.get('helper_language', '')
    if lang and lang not in HELPER_NAMES:
        messages.error(request, 'Pick a language from the list.')
    else:
        LearnerProfile.objects.update_or_create(user=request.user, defaults={'helper_language': lang})
        messages.success(request, f'Second language: {HELPER_NAMES[lang]}. Lessons are translated the first time you open them.'
                         if lang else 'English only. No second language is shown.')
    nxt = request.POST.get('next', '')
    return redirect(nxt if nxt.startswith('/learn/') else 'journey:home')


@login_required
@require_POST
def space_create(request):
    subject = request.POST.get('subject', subjects.DEFAULT)
    if not subjects.is_supported(subject):
        messages.error(request, str(subjects.UnknownSubject(subject)))
        return redirect('journey:home')
    if StudyGroup.objects.filter(created_by=request.user, is_personal=True).count() >= MAX_SPACES:
        messages.error(request, f'You can have up to {MAX_SPACES} learning spaces.')
        return redirect('journey:home')
    space = _new_space(request.user, subject, request.POST.get('name', '').strip(), request.POST.get('level', ''))
    messages.success(request, f'“{space.name}” is ready. Create its first lesson.')
    return redirect(space)


@login_required
@require_POST
def group_create(request):
    name = request.POST.get('name', '').strip()[:80]
    if not name:
        messages.error(request, 'Give the group a name, for example “Suomi A1 – Tuesday class”.')
        return redirect('journey:home')
    subject = request.POST.get('subject', subjects.DEFAULT)
    if not subjects.is_supported(subject):
        messages.error(request, str(subjects.UnknownSubject(subject)))
        return redirect('journey:home')
    if StudyGroup.objects.filter(created_by=request.user, is_personal=False).count() >= 10:
        messages.error(request, 'You can create up to 10 groups.')
        return redirect('journey:home')
    level = request.POST.get('level', '')
    group = StudyGroup.objects.create(name=name, subject=subject, created_by=request.user,
                                      level=level if level in LEVEL_NAMES else '')
    Membership.objects.create(group=group, user=request.user, role=Membership.OWNER)
    messages.success(request, f'Group created. Share the code {group.invite_code} with your classmates.')
    return redirect(group)


@login_required
@require_POST
def group_join(request):
    code = request.POST.get('code', '').strip().upper()
    group = StudyGroup.objects.filter(invite_code=code, is_personal=False).first()
    if not group:
        messages.error(request, 'No group has that code. Check the six characters and try again.')
        return redirect('journey:home')
    Membership.objects.get_or_create(group=group, user=request.user)
    messages.success(request, f'You joined {group.name}.')
    return redirect(group)


@login_required
def group(request, code):
    group = _group_for(request.user, code)
    packs = group.packs.select_related('created_by').annotate(n_items=Count('items'))
    visible = [p for p in packs if p.status == LessonPack.PUBLISHED or p.can_edit(request.user)]
    return render(request, 'journey/group.html', {
        'group': group, 'subject': group.subject_info, 'packs': visible, 'members': group.memberships.select_related('user'),
        'is_owner': group.is_owner(request.user), 'counts': due_counts(request.user, group),
        'levels': LEVELS, 'nav': 'home', 'supported': subjects.is_supported(group.subject),
    })


@login_required
@require_POST
def lesson_create(request, code):
    """Step 0: name the lesson. Its own page then asks for the material."""
    group = _group_for(request.user, code)
    if not subjects.is_supported(group.subject):
        messages.error(request, str(subjects.UnknownSubject(group.subject)))
        return redirect(group)
    title = request.POST.get('title', '').strip()[:120]
    if not title:
        messages.error(request, 'Give the lesson a name, for example “Kappale 3 – Asunto”.')
        return redirect(group)
    pack = LessonPack.objects.create(group=group, title=title, created_by=request.user, status=LessonPack.EMPTY)
    return redirect(pack)


@login_required
@require_POST
def group_settings(request, code):
    group = _group_for(request.user, code)
    if not group.is_owner(request.user):
        raise Http404('Only the owner can change this')
    action = request.POST.get('action', 'save')
    if action == 'delete':
        if not group.is_personal and group.memberships.count() > 1:
            messages.error(request, 'Other members are still in this group. It can be deleted once they have left.')
            return redirect(group)
        name = group.name
        group.delete()
        messages.success(request, f'“{name}” and its lessons were deleted.')
        return redirect('journey:home')
    name = request.POST.get('name', '').strip()[:80]
    level = request.POST.get('level', group.level)
    if name:
        group.name = name
    group.level = level if level in LEVEL_NAMES else group.level
    group.save(update_fields=['name', 'level'])
    messages.success(request, 'Saved.')
    return redirect(group)


@login_required
@require_POST
def group_leave(request, code):
    group = _group_for(request.user, code)
    if group.is_owner(request.user) and group.memberships.count() > 1:
        messages.error(request, 'You own this group. It can be left once the other members have left.')
        return redirect(group)
    group.memberships.filter(user=request.user).delete()
    if not group.memberships.exists():
        group.delete()
    messages.success(request, 'You left the group.')
    return redirect('journey:home')


# ── material ────────────────────────────────────────────────────────────────

def _builds_today(user):
    """Builds started today, and photos sent today, for the daily limits."""
    since = _start_of_today()
    packs = LessonPack.objects.filter(created_by=user).filter(Q(started_at__gte=since) | Q(created_at__gte=since) |
                                                              Q(status=LessonPack.PROCESSING))
    return packs.count(), packs.aggregate(n=Sum('image_count'))['n'] or 0


def _limits(user):
    n_builds, n_images = _builds_today(user)
    return {'images_left': max(0, DAILY_IMAGES - n_images), 'packs_left': max(0, DAILY_PACKS - n_builds),
            'max_files': pipeline.MAX_FILES, 'file_types': extract.FILE_TYPES, 'max_pages': extract.MAX_PDF_PAGES,
            'n_builds': n_builds, 'n_images': n_images}


def _take_material(request, limits):
    """Check the uploaded files and text. Returns (files, text, n_photos, errors); nothing is stored yet."""
    text = request.POST.get('text', '').strip()
    uploads = request.FILES.getlist('files') + request.FILES.getlist('images')
    errors = []
    if not uploads and len(text) < 20:
        errors.append('Add a photo or a file, or paste the text (20 characters or more).')
    if len(uploads) > pipeline.MAX_FILES:
        errors.append(f'Send at most {pipeline.MAX_FILES} files at a time.')
    if limits['n_builds'] >= DAILY_PACKS:
        errors.append(f'You have built {DAILY_PACKS} lessons today. More can be added tomorrow.')
    n_photos = sum(1 for f in uploads if extract.EXTRACTORS['image'].accepts(f.name, f.content_type))
    if limits['n_images'] + n_photos > DAILY_IMAGES:
        errors.append(f'You can send {limits["images_left"]} more photo(s) today (limit {DAILY_IMAGES} a day).')
    files = []
    if not errors:
        for f in uploads:
            ex = extract.for_file(f.name, f.content_type)
            if ex is None:
                errors.append(f'“{f.name}” is not a supported file. Send photos, PDF or Word (.docx) files.')
                continue
            try:
                files.append((ex.kind, f.name, ex.prepare(f)))
            except ValueError as exc:
                errors.append(str(exc))
    return files, text, n_photos, errors, uploads


@login_required
def lesson_add(request):
    """Old “Add a lesson” address: lessons now start inside a subject."""
    return redirect('journey:home')


@login_required
def pack_new(request, code):
    """One step: a new lesson with its material (the subject page's form names it first instead)."""
    group = _group_for(request.user, code)
    if not subjects.is_supported(group.subject):
        messages.error(request, str(subjects.UnknownSubject(group.subject)))
        return redirect(group)
    if request.method != 'POST':
        return redirect(group.get_absolute_url() + '#new-lesson')
    files, text, n_photos, errors, uploads = _take_material(request, _limits(request.user))
    title = request.POST.get('title', '').strip()[:120]
    if not title:
        first = uploads[0].name.rsplit('.', 1)[0] if uploads else text.split('\n', 1)[0]
        title = first.strip()[:80].strip() or 'Untitled lesson'
    if errors:
        for e in errors:
            messages.error(request, e)
        return render(request, 'journey/group.html', {
            'group': group, 'subject': group.subject_info, 'packs': [], 'counts': due_counts(request.user, group),
            'levels': LEVELS, 'nav': 'home', 'supported': True}, status=400)
    pack = LessonPack.objects.create(group=group, title=title, created_by=request.user,
                                     focus=request.POST.get('focus', '').strip()[:200], image_count=n_photos)
    pipeline.queue(pack, files, text)
    return redirect(pack)


@login_required
@require_POST
def lesson_material(request, pk):
    """Step 1: add material to this lesson (its first, or more later). The worker builds it."""
    pack = _pack_for(request.user, pk)
    if not pack.can_edit(request.user):
        raise Http404('Only the person who added this lesson, or the group owner, can add to it')
    if pack.status == LessonPack.PROCESSING:
        messages.info(request, 'This lesson is still being built. Add more when it is done.')
        return redirect(pack)
    files, text, n_photos, errors, _ = _take_material(request, _limits(request.user))
    if errors:
        for e in errors:
            messages.error(request, e)
        return redirect(pack)
    focus = request.POST.get('focus', '').strip()[:200]
    if focus:
        pack.focus = focus
    pack.image_count += n_photos
    pack.save(update_fields=['focus', 'image_count'])
    pipeline.queue(pack, files, text)
    return redirect(pack)


# ── library ─────────────────────────────────────────────────────────────────

@login_required
def library(request):
    q = request.GET.get('q', '').strip()[:80]
    space = request.GET.get('space', '').upper()
    status = request.GET.get('status', '')
    packs = _visible_packs(request.user).select_related('group', 'created_by').annotate(n_items=Count('items', distinct=True))
    if q:
        packs = packs.filter(Q(title__icontains=q) | Q(summary__icontains=q) | Q(source_text__icontains=q))
    if space:
        packs = packs.filter(group__invite_code=space)
    if status in dict(LessonPack.STATUSES):
        packs = packs.filter(status=status)
    packs = list(packs[:200])
    for p in packs:
        p.editable = p.can_edit(request.user)
    return render(request, 'journey/library.html', {
        'packs': packs, 'q': q, 'space': space, 'status': status, 'statuses': LessonPack.STATUSES,
        'places': StudyGroup.objects.filter(memberships__user=request.user).order_by('-is_personal', 'name'),
        'nav': 'library',
    })


# ── one pack: processing, draft review, lesson ─────────────────────────────

@login_required
def pack(request, pk):
    pack = _pack_for(request.user, pk)
    can_edit = pack.can_edit(request.user)
    base = {'pack': pack, 'group': pack.group, 'can_edit': can_edit, 'subject': pack.group.subject_info, 'nav': 'home'}
    if pack.status in (LessonPack.EMPTY, LessonPack.FAILED) and can_edit:
        return render(request, 'journey/lesson_add.html', {**base, **_limits(request.user)})
    if pack.status in (LessonPack.PROCESSING, LessonPack.FAILED, LessonPack.EMPTY) or \
            (pack.status == LessonPack.DRAFT and not can_edit):
        return render(request, 'journey/pack_wait.html', base)
    language = _language(request)
    lang = language['lang']
    translating = translate.ensure(pack, lang) if pack.status == LessonPack.PUBLISHED else False
    if translating:
        pack.refresh_from_db()
    items = _with_helper(list(pack.items.all()), lang)
    by_kind = {k: [i for i in items if i.kind == k] for k, _ in StudyItem.KINDS}
    subject = pack.group.subject_info
    template = 'journey/pack_review.html' if pack.status == LessonPack.DRAFT else 'journey/pack.html'
    questions = [{'q': i.front, 'en': i.meaning_en, 'extra': i.extra, 'options': i.data.get('options', []),
                  'answer': i.data.get('answer', 0), 'why': i.body, 'why_extra': i.extra_body, 'source': i.source_ref}
                 for i in by_kind[StudyItem.QUESTION]]
    return render(request, template, {
        'pack': pack, 'group': pack.group, 'can_edit': can_edit, 'by_kind': by_kind, 'questions': questions,
        'n_low': sum(1 for i in items if i.confidence == StudyItem.LOW),
        'n_unchecked': sum(1 for i in items if i.confidence == StudyItem.MEDIUM and i.kind in StudyItem.REVIEWABLE),
        'summary_extra': (pack.translations or {}).get(lang, '') if lang else '',
        'translating': translating, 'speech_lang': subject.speech_lang, 'tl': subject.text_lang, 'subject': subject,
        'cut': len(pack.source_text) > subject.max_chars, 'add_kinds': _addable(subject), **language,
        **_limits(request.user), 'nav': 'home', 'practice_counts': _lesson_counts(request.user, pack),
    })


def _lesson_counts(user, pack):
    items = _reviewable(user).filter(pack=pack)
    return {'total': items.count(), 'due': Progress.objects.filter(user=user, item__in=items, due__lte=timezone.now()).count(),
            'new': items.exclude(progress__user=user).count()}


def _addable(subject):
    if subject.text_lang:
        return [(StudyItem.WORD, 'Word'), (StudyItem.PHRASE, 'Phrase')]
    return [(StudyItem.CONCEPT, 'Concept')]


@login_required
def pack_status(request, pk):
    pack = _pack_for(request.user, pk)
    return JsonResponse({'status': pack.status, 'note': pack.progress_note, 'error': pack.error})


EDITABLE = ('front', 'form_in_text', 'grammar', 'meaning_en', 'example', 'body')


def _back(request, pack):
    nxt = request.POST.get('next', '')
    return redirect(nxt) if nxt.startswith('/learn/') else redirect(pack)


@login_required
@require_POST
def pack_edit(request, pk):
    pack = _pack_for(request.user, pk)
    if not pack.can_edit(request.user):
        raise Http404('Only the person who added this lesson, or the group owner, can edit it')
    action = request.POST.get('action', 'save')

    if action == 'delete':
        group = pack.group
        pack.delete()
        messages.success(request, 'Lesson deleted.')
        nxt = request.POST.get('next', '')
        return redirect(nxt) if nxt.startswith('/learn/') else redirect(group)

    if action == 'rename':
        title = request.POST.get('title', '').strip()[:120]
        if title:
            pack.title = title
            pack.save(update_fields=['title'])
            messages.success(request, 'Renamed.')
        return _back(request, pack)

    if action == 'retry':
        if not pack.source_text:
            messages.error(request, 'The files are not kept, so add the lesson again.')
            return redirect(pack)
        pipeline.retry(pack)
        return redirect(pack)

    if action == 'add':
        kind = request.POST.get('new-kind', '')
        front = request.POST.get('new-front', '').strip()[:300]
        meaning = request.POST.get('new-meaning', '').strip()[:400]
        if kind in dict(_addable(pack.group.subject_info)) and front and meaning:
            StudyItem.objects.create(pack=pack, kind=kind, front=front, meaning_en=meaning, confidence=StudyItem.HIGH,
                                     order=pack.items.filter(kind=kind).count(), source_ref='Added by you')
            messages.success(request, 'Card added.')
        else:
            messages.error(request, 'Fill in both sides of the new card.')
        return redirect(pack)

    removed = 0
    if action == 'remove_low':
        removed, _ = pack.items.filter(confidence=StudyItem.LOW).delete()
        messages.success(request, f'Removed {removed} low-confidence item(s).')
        return redirect(pack)

    for item in pack.items.all():
        if request.POST.get(f'{item.pk}-delete'):
            item.delete()
            removed += 1
            continue
        changed = []
        for field in EDITABLE:
            key = f'{item.pk}-{field}'
            if key in request.POST:
                value = request.POST[key].strip()[:item._meta.get_field(field).max_length or 4000]
                if value != getattr(item, field):
                    setattr(item, field, value)
                    changed.append(field)
        if item.kind == StudyItem.SENTENCE and f'{item.pk}-cloze' in request.POST:
            cloze = request.POST[f'{item.pk}-cloze'].strip()[:60]
            if cloze != item.data.get('cloze'):
                item.data = {**item.data, 'cloze': cloze}
                changed.append('data')
        if item.kind == StudyItem.QUESTION and f'{item.pk}-opt0' in request.POST:
            options = [request.POST.get(f'{item.pk}-opt{n}', '').strip()[:160] for n in range(4)]
            try:
                answer = int(request.POST.get(f'{item.pk}-answer', item.data.get('answer', 0)))
            except ValueError:
                answer = item.data.get('answer', 0)
            if all(options) and len(set(options)) == 4 and 0 <= answer < 4 and \
                    (options != item.data.get('options') or answer != item.data.get('answer')):
                item.data = {**item.data, 'options': options, 'answer': answer}
                changed.append('data')
        if request.POST.get(f'{item.pk}-ok') and item.confidence != StudyItem.HIGH:
            item.confidence = StudyItem.HIGH
            changed.append('confidence')
        if changed:
            if 'confidence' not in changed and item.confidence != StudyItem.HIGH:
                item.confidence = StudyItem.HIGH   # a person checked and corrected it
                changed.append('confidence')
            item.save(update_fields=list(dict.fromkeys(changed)))

    if action == 'publish' and pack.status == LessonPack.DRAFT:
        pack.publish()
        messages.success(request, 'Published. Choose how to practise it.' if pack.group.is_personal
                         else 'Published. Everyone in the group can now study it. Choose how to practise it.')
        return redirect('journey:lesson_practice', pk=pack.pk)
    else:
        messages.success(request, f'Saved.{f" Removed {removed} item(s)." if removed else ""}')
    return redirect(pack)


# ── practice ────────────────────────────────────────────────────────────────

def _scope(request):
    """What a practice session covers: one lesson, one subject, or everything due today."""
    lesson = request.GET.get('lesson', '')
    code = request.GET.get('group', '')
    if lesson.isdigit():
        pack = _pack_for(request.user, int(lesson))
        if pack.status != LessonPack.PUBLISHED:
            raise Http404('This lesson is not published yet')
        return pack.group, pack
    return (_group_for(request.user, code) if code else None), None


def _picker(request, group, pack):
    items = _reviewable(request.user, group)
    if pack:
        items = items.filter(pack=pack)
    kinds = set(items.values_list('kind', flat=True))
    return render(request, 'journey/practice.html', {
        'group': group, 'pack': pack, 'nav': 'home' if (group or pack) else 'practice',
        'counts': _lesson_counts(request.user, pack) if pack else due_counts(request.user, group),
        'has_types': bool(kinds & {StudyItem.WORD, StudyItem.PHRASE, StudyItem.SENTENCE, StudyItem.CONCEPT, StudyItem.TABLE}),
        'has_tables': StudyItem.TABLE in kinds, 'total': items.count(),
    })


@login_required
def lesson_practice(request, pk):
    pack = _pack_for(request.user, pk)
    if pack.status != LessonPack.PUBLISHED:
        return redirect(pack)
    return _picker(request, pack.group, pack)


@login_required
def group_practice(request, code):
    return _picker(request, _group_for(request.user, code), None)


@login_required
def review(request):
    group, pack = _scope(request)
    return render(request, 'journey/review.html', {
        'group': group, 'pack': pack, 'counts': due_counts(request.user, group), 'mode': request.GET.get('mode', ''),
        'style': request.GET.get('style', ''), 'me': game.status(request.user),
        'nav': 'mistakes' if request.GET.get('mode') == 'mistakes' else ('home' if (group or pack) else 'practice'),
    })


@login_required
def api_due(request):
    group, pack = _scope(request)
    items = _reviewable(request.user, group).select_related('pack__group')
    now = timezone.now()
    extra = False
    if pack:
        # One lesson, chosen on purpose: its due and new cards (no daily limit on new ones); when none are
        # left, a round of extra practice that does not move the review schedule.
        items = items.filter(pack=pack)
        cards = [p.item for p in Progress.objects.filter(user=request.user, due__lte=now, item__in=items)
                 .select_related('item__pack__group').order_by('due')[:BATCH]]
        cards += list(items.exclude(progress__user=request.user).order_by(KIND_ORDER, 'order')[:BATCH - len(cards)])
        if not cards:
            extra = True
            cards = list(items.order_by('?')[:20])
    elif request.GET.get('mode') == 'mistakes':
        cards = [p.item for p in Progress.objects.filter(user=request.user, lapses__gt=0, item__in=items)
                 .select_related('item__pack__group').order_by('-lapses', 'due')[:BATCH]]
    else:
        due = [p.item for p in Progress.objects.filter(user=request.user, due__lte=now, item__in=items)
               .select_related('item__pack__group').order_by('due')[:BATCH]]
        room = min(BATCH - len(due), _new_left_today(request.user))
        new = list(items.exclude(progress__user=request.user)
                   .order_by('pack__published_at', KIND_ORDER, 'order')[:max(0, room)])
        cards = due + new
    language = _language(request)
    lang = language['lang']
    if lang:   # lessons not yet in the learner's language get translated for next time
        for p in {c.pack_id: c.pack for c in cards}.values():
            translate.ensure(p, lang)
    seen = set(Progress.objects.filter(user=request.user, item__in=[c.pk for c in cards]).values_list('item_id', flat=True))
    out = [_card(i, lang) for i in cards]
    for c in out:
        c['seen'] = c['id'] in seen   # "Mixed" shows new cards as flashcards first
    return JsonResponse({'cards': out, 'counts': due_counts(request.user, group),
                         'lang': lang, 'lang_dir': language['lang_dir'], 'extra': extra})


@login_required
@require_POST
def api_grade(request):
    try:
        item_id = int(request.POST.get('item'))
        grade = srs.GRADES[request.POST.get('grade', '')]
    except (TypeError, ValueError, KeyError):
        return JsonResponse({'error': 'Send item and grade (again, hard, good or easy).'}, status=400)
    item = get_object_or_404(_reviewable(request.user).select_related('pack__group'), pk=item_id)
    progress, created = Progress.objects.get_or_create(user=request.user, item=item)
    extra = request.POST.get('extra') == '1'
    scheduled = not created and not extra and progress.due <= timezone.now()
    prev_interval = progress.interval
    if not extra or progress.reps == 0:   # extra practice does not move the schedule
        srs.schedule(progress, grade)
        progress.save()
    mode = request.POST.get('mode', '')
    mode = mode if mode in dict(ReviewLog.MODES) else ReviewLog.FLASH
    # The server checks typed and chosen answers itself; the browser's own verdict is only kept for old pages.
    verdict = answers.verify(item, mode, request.POST.get('given', ''), request.POST.get('row'))         if mode != ReviewLog.FLASH and 'given' in request.POST else None
    if verdict is not None:
        correct = verdict != answers.WRONG
    else:
        correct = {'1': True, '0': False}.get(request.POST.get('correct', '')) if mode != ReviewLog.FLASH else None
    entry = ReviewLog.objects.create(user=request.user, item=item, grade=grade, mode=mode, correct=correct,
                                     verified=verdict is not None, scheduled=scheduled, first=created)
    return JsonResponse({'due': progress.due.isoformat(), 'interval': progress.interval,
                         'again': grade < 3, 'lapses': progress.lapses, 'verdict': verdict,
                         'reward': game.on_answer(request.user, entry, verdict, prev_interval)})


@login_required
def mistakes(request):
    rows = (Progress.objects.filter(user=request.user, lapses__gt=0, item__pack__status=LessonPack.PUBLISHED,
                                    item__pack__group__memberships__user=request.user)
            .select_related('item__pack__group').order_by('-lapses', 'due').distinct())
    language = _language(request)
    rows = list(rows)
    _with_helper([p.item for p in rows], language['lang'])
    return render(request, 'journey/mistakes.html', {'rows': rows, 'nav': 'mistakes', **language})


# ── the town: a small game world for language subjects ───────────────────

TOWN_SPRITES = 6
PLACE_LEVELS = {'bus': 2, 'bakery': 3, 'market': 4}   # the café, academy, home and quest board are open


def _town_language(user):
    """The language the town speaks. Only Finnish has scenes so far."""
    return 'finnish'


@login_required
def town(request):
    from django.middleware.csrf import get_token
    config = {
        'models': settings.STATIC_URL + 'journey/town3d/', 'state': reverse('journey:api_town'), 'avatar': reverse('journey:api_town_avatar'), 'buy': reverse('journey:api_town_buy'),
        'due': reverse('journey:api_due'), 'grade': reverse('journey:api_grade'),
        'scene': reverse('journey:api_scene_start', args=['KEY']).replace('start/', ''),
        'csrf': get_token(request), 'debug': settings.DEBUG,
    }
    return render(request, 'journey/town3d.html', {'nav': 'town', 'town_config': config})


def _today_key(key):
    return f'scene:{key}:{timezone.localdate().isoformat()}'


@login_required
def api_town(request):
    """Everything the town needs to draw the learner's state. Read-only."""
    user = request.user
    status = game.status(user)
    profile = LearnerProfile.for_user(user)
    avatar = profile.avatar if isinstance(profile.avatar, dict) else {}
    sprite = avatar.get('sprite')
    done = {k.split(':')[1] for k in RewardEvent.objects.filter(user=user, kind=RewardEvent.SCENE,
                                                                 day=timezone.localdate()).values_list('key', flat=True)}
    places = {key: {'locked': status['level'] < level, 'level': level, 'done_today': key in done}
              for key, level in PLACE_LEVELS.items()}
    places['cafe'] = {'locked': False, 'done_today': 'cafe' in done}
    language = _town_language(user)
    lessons = []
    # The academy holds every subject: the town is one world for all of a learner's learning.
    for pack in (LessonPack.objects.filter(group__memberships__user=user, status=LessonPack.PUBLISHED)
                 .select_related('group').distinct().order_by('-published_at')[:12]):
        c = _lesson_counts(user, pack)
        info = pack.group.subject_info
        lessons.append({'id': pack.pk, 'title': pack.title, 'space': pack.group.name, 'subject': info.name, 'icon': info.icon,
                        'due': c['due'], 'new': c['new'], 'total': c['total'],
                        'practise': reverse('journey:lesson_practice', args=[pack.pk]), 'open': pack.get_absolute_url()})
    have = list(Achievement.objects.filter(user=user).order_by('-unlocked_at').values_list('code', flat=True))
    # Every subject the learner studies shows in the same town: how much of it is learned and kept.
    studied = []
    for g in StudyGroup.objects.filter(memberships__user=user).distinct().order_by('name')[:8]:
        k = game.knowledge(user, _reviewable(user, g))
        info = g.subject_info
        studied.append({'name': g.name, 'subject': info.name, 'icon': info.icon, 'total': k['total'],
                        'learned': k['recognised'], 'kept': k['retained'], 'url': g.get_absolute_url()})
    return JsonResponse({
        'lessons': lessons, 'subjects': studied, 'due': due_counts(user),
        'links': {'subjects': reverse('journey:home'), 'review': reverse('journey:review'),
                  'progress': reverse('journey:progress'), 'library': reverse('journey:library')},
        'achievements': {'unlocked': len(have), 'total': len(game.ACHIEVEMENTS),
                         'recent': [{'name': game.ACHIEVEMENTS[c][0], 'icon': game.ACHIEVEMENTS[c][2], 'tier': game.ACHIEVEMENTS[c][3]}
                                    for c in have if c in game.ACHIEVEMENTS][:8]},
        'shop': town_decor.shop(user, status),
        'greetings': [list(g) for g in scenes.GREETINGS.get(language, [])],
        'me': {k: status[k] for k in ('level', 'rank', 'xp', 'coins', 'pct', 'into', 'span', 'streak', 'today_xp')},
        'name': user.get_full_name() or user.get_username(),
        'sprite': sprite if isinstance(sprite, int) and 0 <= sprite < TOWN_SPRITES else None,
        'quests': [{'title': q.title, 'detail': q.detail, 'progress': q.progress, 'target': q.target, 'done': bool(q.done_at),
                    'week': q.period == Quest.WEEK, 'xp': q.xp, 'coins': q.coins} for q in game.quests_for(user)],
        'places': places,
    })


@login_required
@require_POST
def api_town_buy(request):
    ok, message = town_decor.buy(request.user, request.POST.get('item', ''))
    return JsonResponse({'ok': ok, 'message': message}, status=200 if ok else 409)


@login_required
@require_POST
def api_town_avatar(request):
    try:
        sprite = int(request.POST.get('sprite', ''))
    except ValueError:
        sprite = -1
    if not 0 <= sprite < TOWN_SPRITES:
        return JsonResponse({'error': 'Pick one of the characters.'}, status=400)
    profile = LearnerProfile.for_user(request.user)
    avatar = profile.avatar if isinstance(profile.avatar, dict) else {}
    first_visit = 'sprite' not in avatar
    profile.avatar = {**avatar, 'sprite': sprite}
    profile.save(update_fields=['avatar'])
    if first_visit:
        game.add_town_quests(request.user)
    return JsonResponse({'sprite': sprite})


def _scene_or_404(user, key):
    scene = scenes.get(key, _town_language(user))
    if scene is None:
        raise Http404('No such place')
    return scene


@login_required
@require_POST
def api_scene_start(request, key):
    scene = _scene_or_404(request.user, key)
    level = PLACE_LEVELS.get(key)
    if level and game.status(request.user)['level'] < level:
        return JsonResponse({'error': f'This place opens at level {level}.'}, status=403)
    order = scenes.shuffle(scene)
    request.session['town_scene'] = {'key': key, 'turn': 0, 'missed': [], 'order': order}
    done = RewardEvent.objects.filter(user=request.user, key=_today_key(key)).exists()
    return JsonResponse({**scenes.public(scene, order), 'done_today': done})


@login_required
@require_POST
def api_scene_answer(request, key):
    """One reply in a conversation. The server keeps the place in the conversation, so turns cannot be skipped."""
    scene = _scene_or_404(request.user, key)
    state = request.session.get('town_scene') or {}
    try:
        turn, choice = int(request.POST.get('turn', '')), int(request.POST.get('choice', ''))
    except ValueError:
        return JsonResponse({'error': 'Send turn and choice.'}, status=400)
    if (state.get('key') != key or state.get('turn') != turn or turn >= len(scene['turns'])
            or not 0 <= choice < len(scene['turns'][turn]['options'])):
        return JsonResponse({'error': 'Start the conversation again.'}, status=409)
    right, meaning = scenes.check(scene, turn, choice, state.get('order'))
    out = {'right': right, 'meaning': meaning, 'done': False}
    if not right:
        state['missed'] = sorted(set(state['missed']) | {turn})
    else:
        state['turn'] = turn + 1
        if state['turn'] == len(scene['turns']):
            first_try = len(scene['turns']) - len(state['missed'])
            out.update(done=True, first_try=first_try, turns=len(scene['turns']),
                       reward=game.on_scene(request.user, key, scene['title'], scenes.XP_PER_TURN * first_try + 2,
                                            scenes.COINS))
            state = {}
    request.session['town_scene'] = state
    return JsonResponse(out)


@login_required
@require_POST
def api_scene_save(request, key):
    """Keep the replies from a finished conversation as phrase cards in the learner's own language space."""
    scene = _scene_or_404(request.user, key)
    if not RewardEvent.objects.filter(user=request.user, kind=RewardEvent.SCENE, key__startswith=f'scene:{key}:').exists():
        return JsonResponse({'error': 'Finish the conversation first.'}, status=409)
    language = _town_language(request.user)
    space = (StudyGroup.objects.filter(is_personal=True, subject=language, memberships__user=request.user,
                                       memberships__role=Membership.OWNER).order_by('pk').first()
             or _new_space(request.user, language))
    title = f'{scene["title"]} · town phrases'
    pack, created = LessonPack.objects.get_or_create(group=space, title=title, defaults={
        'created_by': request.user, 'summary': scene['goal'], 'source_kind': 'text'})
    if created:
        StudyItem.objects.bulk_create([
            StudyItem(pack=pack, kind=StudyItem.PHRASE, order=i, front=fi, meaning_en=en, example=say,
                      confidence=StudyItem.HIGH, source_ref=f'Town: {scene["title"]}')
            for i, (fi, en, say) in enumerate(scenes.phrases(scene))])
        pack.publish()
    return JsonResponse({'url': pack.get_absolute_url(), 'created': created, 'count': pack.items.count()})
