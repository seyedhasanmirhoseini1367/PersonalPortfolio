"""News inbox: find fresh AI news on demand and publish the ones you pick.

- find(): search the news sources now (same sources and filters as the daily
  digest: no finance, no repeats, duplicates merged) and keep the best ~12
  fresh items as NewsCandidates.
- send_to_owner(): the list goes to the owner's private Telegram chat with a
  ➕ button per item and a 🚀 "Publish picks now" button.
- pick(): ➕ adds an item to the editor's links (SuggestedLink).
- publish_now(): summarises the picked links into today's digest right away and
  refreshes the channel draft (sent to the channel only after approval).

Triggered from the News desk page or by sending /news to the bot.
"""
import html
import logging
import threading
from datetime import timedelta

from django.db import close_old_connections
from django.utils import timezone

logger = logging.getLogger(__name__)
PER_SECTION = {'papers': 4, 'news': 6, 'hn': 3}
SECTION_ICON = {'papers': '📄', 'news': '📰', 'hn': '💬'}
_lock = threading.Lock()


def find(log=print) -> list:
    """Fresh candidates, best first (also stored as NewsCandidate rows)."""
    from .digest import collect, merge_duplicates, same_story
    from .models import DigestItem, NewsCandidate, SuggestedLink
    used = set(DigestItem.objects.values_list('url', flat=True)) | set(SuggestedLink.objects.values_list('url', flat=True))
    recent = list(DigestItem.objects.filter(digest_date__gte=timezone.now().date() - timedelta(days=4))
                  .values_list('title', flat=True))
    candidates = merge_duplicates(collect(log=log))
    NewsCandidate.objects.filter(status=NewsCandidate.NEW).delete()   # a fresh list each time
    out = []
    for section, limit in PER_SECTION.items():
        n = 0
        for it in candidates.get(section, []):
            if n >= limit:
                break
            if it['url'] in used or any(same_story(it['title'], t) for t in recent):
                continue
            c, _ = NewsCandidate.objects.update_or_create(url=it['url'][:500], defaults={
                'title': it['title'][:300], 'source': it['source'][:100].replace(' discussion', ''),
                'section': section, 'text': (it.get('text') or '')[:1500], 'status': NewsCandidate.NEW,
                'found_at': timezone.now()})
            out.append(c)
            n += 1
    log(f'news inbox: {len(out)} fresh item(s)')
    return out


def pick(cand) -> bool:
    """Add a candidate to the editor's links (goes into the next / today's digest)."""
    from .models import NewsCandidate, SuggestedLink
    if cand.status == NewsCandidate.PICKED or SuggestedLink.objects.filter(url=cand.url, status='pending').exists():
        return False
    note = f'{cand.title}. {cand.text}'.strip()[:300]
    SuggestedLink.objects.create(url=cand.url, note=note)
    cand.status = NewsCandidate.PICKED
    cand.save(update_fields=['status'])
    return True


def telegram_text(cands) -> str:
    e = lambda s: html.escape(s or '', quote=True)
    lines = ['📡 <b>News inbox</b> — fresh AI news right now', '<i>Tap ➕ to pick, then 🚀 to publish your picks.</i>', '']
    for i, c in enumerate(cands, 1):
        block = f'{i}. {SECTION_ICON.get(c.section, "•")} <a href="{e(c.url)}">{e(c.title)}</a> <i>({e(c.source.split(' (')[0])})</i>'
        if len('\n'.join(lines + [block])) > 3800:
            break
        lines.append(block)
    return '\n'.join(lines)


def send_to_owner(cands, chat_id=None):
    from . import telegram
    from .models import TelegramConfig
    chat_id = chat_id or TelegramConfig.get().admin_chat_id
    if not telegram.configured() or not chat_id:
        return False
    if not cands:
        telegram.api('sendMessage', chat_id=chat_id, text='📡 Nothing new right now: every fresh item is already in a digest.')
        return True
    buttons = [{'text': f'➕ {i}', 'callback_data': f'nc:add:{c.pk}'} for i, c in enumerate(cands, 1)]
    keyboard = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
    keyboard.append([{'text': '🚀 Publish picks now', 'callback_data': 'nc:pub'}])
    keyboard.append([{'text': '📋 Open the News desk', 'url': telegram.review_url()}])
    telegram.api('sendMessage', chat_id=chat_id, text=telegram_text(cands), parse_mode='HTML',
                 link_preview_options={'is_disabled': True}, reply_markup={'inline_keyboard': keyboard})
    return True


def publish_now(log=print):
    """Summarise the pending picks into today's digest; refresh the channel draft."""
    from .digest import add_picks_now
    story, n = add_picks_now(log=log)
    if story:
        try:
            from .telegram import configured, queue_post
            if configured():
                queue_post(story)
        except Exception as exc:
            log(f'telegram draft failed: {exc}')
    return story, n


def _background(fn):
    if not _lock.acquire(blocking=False):
        return False

    def work():
        try:
            fn()
        except Exception:
            logger.exception('News inbox task failed')
        finally:
            close_old_connections()
            _lock.release()

    threading.Thread(target=work, name='news-inbox', daemon=True).start()
    return True


def find_and_send_in_background(chat_id=None):
    return _background(lambda: send_to_owner(find(log=lambda m: None), chat_id))


def find_in_background():
    return _background(lambda: find(log=lambda m: None))


def publish_in_background(chat_id=None):
    def job():
        story, n = publish_now(log=lambda m: None)
        if chat_id:
            from . import telegram
            text = (f'🚀 Added {n} item(s) to “{story.title}”. The channel draft is waiting for your approval.'
                    if story else 'Nothing was published: no picked item could be summarised right now.')
            telegram.api('sendMessage', chat_id=chat_id, text=text)
    return _background(job)
