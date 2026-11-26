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
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import extract, pipeline, srs, subjects, translate
from .models import (HELPER_LANGUAGES, HELPER_NAMES, LEVELS, RTL_LANGUAGES, LearnerProfile, LessonPack, Membership,
                     Progress, ReviewLog, StudyGroup, StudyItem)

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
        tips.append({'icon': 'fa-pen-to-square', 'text': _n(drafts, 'draft lesson waits', 'draft lessons wait') + ' for your check.',
                     'url': 'journey:library', 'cta': 'Check drafts'})
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

@login_required
def home(request):
    spaces = list(_spaces_of(request.user, True))
    for s in spaces:
        s.counts = due_counts(request.user, s)
        s.info = s.subject_info
    return render(request, 'journey/home.html', {
        'spaces': spaces, 'groups': _spaces_of(request.user, False),
        'recent': _visible_packs(request.user).select_related('group')[:6],
        'counts': due_counts(request.user),
        'mistakes': Progress.objects.filter(user=request.user, lapses__gt=0).count(),
        'tips': recommendations(request.user, spaces), 'progress': progress_summary(request.user),
        'helper_choices': HELPER_LANGUAGES, 'subject_choices': subjects.SUBJECTS.values(),
        'default_subject': subjects.DEFAULT, 'levels': LEVELS, 'nav': 'home',
        **_language(request),
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
    messages.success(request, f'“{space.name}” is ready. Add your first material.')
    return redirect('journey:pack_new', code=space.invite_code)


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
        'progress': progress_summary(request.user, group), 'levels': LEVELS, 'nav': 'home',
    })


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


# ── new lesson ──────────────────────────────────────────────────────────────

def _uploads_today(user):
    since = _start_of_today()
    packs = LessonPack.objects.filter(created_by=user, created_at__gte=since)
    return packs.count(), packs.aggregate(n=Sum('image_count'))['n'] or 0


@login_required
def lesson_add(request):
    """“Add a lesson” from anywhere: pick the space; a first-time learner gets a Finnish space made for them."""
    places = list(StudyGroup.objects.filter(memberships__user=request.user).order_by('-is_personal', 'name'))
    if not places:
        places = [_new_space(request.user, subjects.DEFAULT)]
    chosen = request.POST.get('space') or request.GET.get('space') or places[0].invite_code
    space = next((p for p in places if p.invite_code == chosen.upper()), places[0])
    return pack_new(request, space.invite_code, places=places)


@login_required
def pack_new(request, code, places=None):
    group = _group_for(request.user, code)
    if not subjects.is_supported(group.subject):
        messages.error(request, str(subjects.UnknownSubject(group.subject)))
        return redirect(group)
    n_packs, n_images = _uploads_today(request.user)
    ctx = {'group': group, 'images_left': max(0, DAILY_IMAGES - n_images), 'max_files': pipeline.MAX_FILES,
           'packs_left': max(0, DAILY_PACKS - n_packs), 'subject': group.subject_info, 'places': places,
           'file_types': extract.FILE_TYPES, 'max_pages': extract.MAX_PDF_PAGES, 'nav': 'add'}
    if request.method != 'POST':
        return render(request, 'journey/pack_new.html', ctx)

    title = request.POST.get('title', '').strip()[:120]
    text = request.POST.get('text', '').strip()
    focus = request.POST.get('focus', '').strip()[:200]
    uploads = request.FILES.getlist('files') + request.FILES.getlist('images')
    errors = []
    if not uploads and len(text) < 20:
        errors.append('Add a photo or a file, or paste the text (20 characters or more).')
    if len(uploads) > pipeline.MAX_FILES:
        errors.append(f'Send at most {pipeline.MAX_FILES} files at a time.')
    if n_packs >= DAILY_PACKS:
        errors.append(f'You have made {DAILY_PACKS} lessons today. More can be added tomorrow.')
    n_photos = sum(1 for f in uploads if extract.EXTRACTORS['image'].accepts(f.name, f.content_type))
    if n_images + n_photos > DAILY_IMAGES:
        errors.append(f'You can send {ctx["images_left"]} more photo(s) today (limit {DAILY_IMAGES} a day).')
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
    if not title:
        first = uploads[0].name.rsplit('.', 1)[0] if uploads else text.split('\n', 1)[0]
        title = first.strip()[:80].strip() or 'Untitled lesson'
    if errors:
        for e in errors:
            messages.error(request, e)
        ctx.update(title=request.POST.get('title', ''), text=text, focus=focus)
        return render(request, 'journey/pack_new.html', ctx, status=400)

    pack = LessonPack.objects.create(group=group, title=title, created_by=request.user, focus=focus,
                                     image_count=n_photos, progress_note='Waiting for its turn…')
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
    if pack.status in (LessonPack.PROCESSING, LessonPack.FAILED) or (pack.status == LessonPack.DRAFT and not can_edit):
        return render(request, 'journey/pack_wait.html', {'pack': pack, 'can_edit': can_edit})
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
    })


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
        messages.success(request, 'Published. It is in your daily practice now.' if pack.group.is_personal
                         else 'Published. Everyone in the group can now study this lesson.')
    else:
        messages.success(request, f'Saved.{f" Removed {removed} item(s)." if removed else ""}')
    return redirect(pack)


# ── practice ────────────────────────────────────────────────────────────────

@login_required
def review(request):
    code = request.GET.get('group', '')
    group = _group_for(request.user, code) if code else None
    return render(request, 'journey/review.html', {
        'group': group, 'counts': due_counts(request.user, group), 'mode': request.GET.get('mode', ''),
        'nav': 'mistakes' if request.GET.get('mode') == 'mistakes' else 'practice',
    })


@login_required
def api_due(request):
    code = request.GET.get('group', '')
    group = _group_for(request.user, code) if code else None
    items = _reviewable(request.user, group).select_related('pack__group')
    now = timezone.now()
    if request.GET.get('mode') == 'mistakes':
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
    return JsonResponse({'cards': [_card(i, lang) for i in cards], 'counts': due_counts(request.user, group),
                         'lang': lang, 'lang_dir': language['lang_dir']})


@login_required
@require_POST
def api_grade(request):
    try:
        item_id = int(request.POST.get('item'))
        grade = srs.GRADES[request.POST.get('grade', '')]
    except (TypeError, ValueError, KeyError):
        return JsonResponse({'error': 'Send item and grade (again, hard, good or easy).'}, status=400)
    item = get_object_or_404(_reviewable(request.user), pk=item_id)
    progress, _ = Progress.objects.get_or_create(user=request.user, item=item)
    srs.schedule(progress, grade)
    progress.save()
    mode = request.POST.get('mode', '')
    mode = mode if mode in dict(ReviewLog.MODES) else ReviewLog.FLASH
    correct = {'1': True, '0': False}.get(request.POST.get('correct', '')) if mode != ReviewLog.FLASH else None
    ReviewLog.objects.create(user=request.user, item=item, grade=grade, mode=mode, correct=correct)
    return JsonResponse({'due': progress.due.isoformat(), 'interval': progress.interval,
                         'again': grade < 3, 'lapses': progress.lapses})


@login_required
def mistakes(request):
    rows = (Progress.objects.filter(user=request.user, lapses__gt=0, item__pack__status=LessonPack.PUBLISHED,
                                    item__pack__group__memberships__user=request.user)
            .select_related('item__pack__group').order_by('-lapses', 'due').distinct())
    language = _language(request)
    rows = list(rows)
    _with_helper([p.item for p in rows], language['lang'])
    return render(request, 'journey/mistakes.html', {'rows': rows, 'nav': 'mistakes', **language})
