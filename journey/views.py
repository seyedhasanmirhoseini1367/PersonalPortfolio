"""LearningJourney pages and the small JSON API used by the review screen."""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Case, Count, Q, Sum, When
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import pipeline, srs
from .models import LessonPack, Membership, Progress, StudyGroup, StudyItem

MAX_IMAGE_BYTES = 12 * 1024 * 1024
NEW_PER_DAY = getattr(settings, 'JOURNEY_NEW_PER_DAY', 20)
DAILY_IMAGES = getattr(settings, 'JOURNEY_DAILY_IMAGES', 30)
DAILY_PACKS = getattr(settings, 'JOURNEY_DAILY_PACKS', 10)
BATCH = 30
# New cards: words first, then sentences built from them, then phrases.
KIND_ORDER = Case(When(kind=StudyItem.WORD, then=0), When(kind=StudyItem.SENTENCE, then=1), default=2)


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


def _card(item):
    return {
        'id': item.pk, 'kind': item.kind, 'front': item.front, 'form': item.form_in_text,
        'grammar': item.grammar, 'fa': item.meaning_fa, 'en': item.meaning_en, 'example': item.example,
        'cloze': (item.data or {}).get('cloze', ''), 'pack': item.pack.title,
        'confidence': item.confidence,
    }


# ── home and groups ─────────────────────────────────────────────────────────

@login_required
def home(request):
    groups = (StudyGroup.objects.filter(memberships__user=request.user)
              .annotate(n_packs=Count('packs', filter=Q(packs__status=LessonPack.PUBLISHED), distinct=True),
                        n_members=Count('memberships', distinct=True)))
    recent = (LessonPack.objects.filter(group__memberships__user=request.user)
              .filter(Q(status=LessonPack.PUBLISHED) | Q(created_by=request.user))
              .select_related('group')[:8])
    mistakes = Progress.objects.filter(user=request.user, lapses__gt=0).count()
    return render(request, 'journey/home.html', {
        'groups': groups, 'recent': recent, 'counts': due_counts(request.user), 'mistakes': mistakes,
    })


@login_required
@require_POST
def group_create(request):
    name = request.POST.get('name', '').strip()[:80]
    if not name:
        messages.error(request, 'Give the group a name, for example “Suomi A1 – Tuesday class”.')
        return redirect('journey:home')
    if StudyGroup.objects.filter(created_by=request.user).count() >= 10:
        messages.error(request, 'You can create up to 10 groups.')
        return redirect('journey:home')
    group = StudyGroup.objects.create(name=name, created_by=request.user)
    Membership.objects.create(group=group, user=request.user, role=Membership.OWNER)
    messages.success(request, f'Group created. Share the code {group.invite_code} with your classmates.')
    return redirect(group)


@login_required
@require_POST
def group_join(request):
    code = request.POST.get('code', '').strip().upper()
    group = StudyGroup.objects.filter(invite_code=code).first()
    if not group:
        messages.error(request, 'No group has that code. Check the six characters and try again.')
        return redirect('journey:home')
    Membership.objects.get_or_create(group=group, user=request.user)
    messages.success(request, f'You joined {group.name}.')
    return redirect(group)


@login_required
def group(request, code):
    group = _group_for(request.user, code)
    packs = group.packs.select_related('created_by')
    visible = [p for p in packs if p.status == LessonPack.PUBLISHED or p.can_edit(request.user)]
    return render(request, 'journey/group.html', {
        'group': group, 'packs': visible, 'members': group.memberships.select_related('user'),
        'is_owner': group.is_owner(request.user), 'counts': due_counts(request.user, group),
    })


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


# ── new lesson pack ─────────────────────────────────────────────────────────

def _uploads_today(user):
    since = _start_of_today()
    packs = LessonPack.objects.filter(created_by=user, created_at__gte=since)
    return packs.count(), packs.aggregate(n=Sum('image_count'))['n'] or 0


@login_required
def pack_new(request, code):
    group = _group_for(request.user, code)
    n_packs, n_images = _uploads_today(request.user)
    ctx = {'group': group, 'images_left': max(0, DAILY_IMAGES - n_images), 'max_images': pipeline.MAX_IMAGES,
           'packs_left': max(0, DAILY_PACKS - n_packs)}
    if request.method != 'POST':
        return render(request, 'journey/pack_new.html', ctx)

    title = request.POST.get('title', '').strip()[:120]
    text = request.POST.get('text', '').strip()
    files = request.FILES.getlist('images')
    errors = []
    if not title:
        errors.append('Give the lesson a title, for example “Kappale 3 – Asunto”.')
    if not files and len(text) < 20:
        errors.append('Add at least one photo, or paste the lesson text (20 characters or more).')
    if len(files) > pipeline.MAX_IMAGES:
        errors.append(f'Send at most {pipeline.MAX_IMAGES} photos at a time.')
    if n_packs >= DAILY_PACKS:
        errors.append(f'You have made {DAILY_PACKS} lessons today. More can be added tomorrow.')
    if n_images + len(files) > DAILY_IMAGES:
        errors.append(f'You can send {ctx["images_left"]} more photo(s) today (limit {DAILY_IMAGES} a day).')
    images = []
    if not errors:
        for f in files:
            if f.size > MAX_IMAGE_BYTES or not (f.content_type or '').startswith('image/'):
                errors.append(f'“{f.name}” is not a photo under 12 MB.')
                continue
            try:
                images.append(pipeline.prepare_image(f.read()))
            except Exception:
                errors.append(f'“{f.name}” could not be opened as an image. Try a JPG or PNG.')
    if errors:
        for e in errors:
            messages.error(request, e)
        ctx.update(title=title, text=text)
        return render(request, 'journey/pack_new.html', ctx, status=400)

    pack = LessonPack.objects.create(group=group, title=title, created_by=request.user,
                                     image_count=len(images), progress_note='Starting…')
    pipeline.start(pack, images, text)
    return redirect(pack)


# ── one pack: processing, draft review, lesson ─────────────────────────────

@login_required
def pack(request, pk):
    pack = _pack_for(request.user, pk)
    can_edit = pack.can_edit(request.user)
    if pack.status in (LessonPack.PROCESSING, LessonPack.FAILED) or (pack.status == LessonPack.DRAFT and not can_edit):
        return render(request, 'journey/pack_wait.html', {'pack': pack, 'can_edit': can_edit})
    items = list(pack.items.all())
    by_kind = {k: [i for i in items if i.kind == k] for k, _ in StudyItem.KINDS}
    template = 'journey/pack_review.html' if pack.status == LessonPack.DRAFT else 'journey/pack.html'
    questions = [{'q': i.front, 'fa': i.meaning_fa, 'options': i.data.get('options', []),
                  'answer': i.data.get('answer', 0), 'why': i.body} for i in by_kind[StudyItem.QUESTION]]
    return render(request, template, {
        'pack': pack, 'group': pack.group, 'can_edit': can_edit, 'by_kind': by_kind, 'questions': questions,
        'n_low': sum(1 for i in items if i.confidence == StudyItem.LOW and i.kind == StudyItem.WORD),
    })


@login_required
def pack_status(request, pk):
    pack = _pack_for(request.user, pk)
    return JsonResponse({'status': pack.status, 'note': pack.progress_note, 'error': pack.error})


EDITABLE = ('front', 'form_in_text', 'grammar', 'meaning_fa', 'meaning_en', 'example', 'body')


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
        return redirect(group)

    if action == 'retry':
        if not pack.source_text:
            messages.error(request, 'The photos are not kept, so add the lesson again.')
            return redirect(pack)
        pack.status, pack.error, pack.progress_note = LessonPack.PROCESSING, '', 'Starting again…'
        pack.save(update_fields=['status', 'error', 'progress_note'])
        pipeline.start(pack, (), pack.source_text)
        return redirect(pack)

    removed = 0
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
            item.data = {**item.data, 'cloze': request.POST[f'{item.pk}-cloze'].strip()[:60]}
            changed.append('data')
        if changed:
            if item.kind == StudyItem.WORD and 'confidence' not in changed:
                item.confidence = StudyItem.HIGH   # a person checked and corrected it
                changed.append('confidence')
            item.save(update_fields=changed)

    if action == 'publish' and pack.status == LessonPack.DRAFT:
        pack.publish()
        messages.success(request, 'Published. Everyone in the group can now study this lesson.')
    else:
        messages.success(request, f'Saved.{f" Removed {removed} item(s)." if removed else ""}')
    return redirect(pack)


# ── daily review ─────────────────────────────────────────────────────────────

@login_required
def review(request):
    code = request.GET.get('group', '')
    group = _group_for(request.user, code) if code else None
    return render(request, 'journey/review.html', {
        'group': group, 'counts': due_counts(request.user, group), 'mode': request.GET.get('mode', ''),
    })


@login_required
def api_due(request):
    code = request.GET.get('group', '')
    group = _group_for(request.user, code) if code else None
    items = _reviewable(request.user, group).select_related('pack')
    now = timezone.now()
    if request.GET.get('mode') == 'mistakes':
        cards = [p.item for p in Progress.objects.filter(user=request.user, lapses__gt=0, item__in=items)
                 .select_related('item__pack').order_by('-lapses', 'due')[:BATCH]]
    else:
        due = [p.item for p in Progress.objects.filter(user=request.user, due__lte=now, item__in=items)
               .select_related('item__pack').order_by('due')[:BATCH]]
        room = min(BATCH - len(due), _new_left_today(request.user))
        new = list(items.exclude(progress__user=request.user)
                   .order_by('pack__published_at', KIND_ORDER, 'order')[:max(0, room)])
        cards = due + new
    return JsonResponse({'cards': [_card(i) for i in cards], 'counts': due_counts(request.user, group)})


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
    return JsonResponse({'due': progress.due.isoformat(), 'interval': progress.interval,
                         'again': grade < 3, 'lapses': progress.lapses})


@login_required
def mistakes(request):
    rows = (Progress.objects.filter(user=request.user, lapses__gt=0, item__pack__status=LessonPack.PUBLISHED,
                                    item__pack__group__memberships__user=request.user)
            .select_related('item__pack').order_by('-lapses', 'due').distinct())
    return render(request, 'journey/mistakes.html', {'rows': rows})
