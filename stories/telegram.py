"""Announce new AI news digests on the Telegram channel — only after approval.

Flow:
1. A daily digest / weekly roundup is published (stories/digest.py) and
   queue_post() writes a short announcement (TelegramPost, status pending).
2. The bot sends that draft to the site owner's private chat with
   [Publish] [Skip] buttons, plus a link to edit it on the site
   (/stories/telegram/). Nothing reaches the channel before this.
3. Pressing Publish (in Telegram or on the site) posts it to the channel.

The owner's chat is linked once: the review page shows a t.me deep link with a
one-time code; opening it sends "/start <code>" to the bot, and the webhook
stores that chat as the only one allowed to approve.

Settings (environment variables on Render — never in code):
TELEGRAM_BOT_TOKEN (from @BotFather), TELEGRAM_CHANNEL_ID (@channelname or
numeric id), SITE_URL (https://hasanai.net).
"""
import hashlib
import hmac
import html
import json
import logging
import re
import secrets
import urllib.error
import urllib.request

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)
MAX_ITEMS = 6


class TelegramError(Exception):
    pass


def token() -> str:
    return (getattr(settings, 'TELEGRAM_BOT_TOKEN', '') or '').strip()


def channel() -> str:
    """'AIFrontiers', '@AIFrontiers' or 't.me/AIFrontiers' -> '@AIFrontiers'; numeric ids kept."""
    c = (getattr(settings, 'TELEGRAM_CHANNEL_ID', '') or '').strip()
    c = re.sub(r'^(https?://)?t\.me/', '', c).strip('/')
    if c and not c.startswith('@') and not re.fullmatch(r'-?\d+', c):
        c = '@' + c
    return c


def configured() -> bool:
    return bool(token() and channel())


def site_url() -> str:
    return (getattr(settings, 'SITE_URL', '') or 'https://hasanai.net').rstrip('/')


def api(method: str, **params):
    """Call the Bot API; raises TelegramError with Telegram's own description."""
    req = urllib.request.Request(
        f'https://api.telegram.org/bot{token()}/{method}', data=json.dumps(params).encode(),
        headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = json.load(r)
    except urllib.error.HTTPError as exc:
        try:
            body = json.load(exc)
        except Exception:
            raise TelegramError(f'HTTP {exc.code}') from None
    except Exception as exc:   # network; never include the URL (it holds the token)
        raise TelegramError(type(exc).__name__) from None
    if not body.get('ok'):
        raise TelegramError(body.get('description') or 'Telegram error')
    return body.get('result')


def webhook_secret() -> str:
    return hmac.new(settings.SECRET_KEY.encode(), token().encode(), hashlib.sha256).hexdigest()[:48]


# ── the announcement ─────────────────────────────────────────────────────────

_ITEM = re.compile(r'<h3><a href="([^"]+)"[^>]*>(.*?)</a></h3>\s*'
                   r'(?:<p class="digest-meta"><a class="digest-topic"[^>]*>(.*?)</a></p>)?', re.S)


def _plain(s: str) -> str:
    return html.unescape(re.sub(r'<[^>]+>', '', s or '')).strip()


def build_text(story, translate=True) -> str:
    """The channel post, in Persian: each item with a short Persian summary and its source.
    Items without a Persian version (translation unavailable) fall back to the English title."""
    from .digest import translate_fa
    from .models import DigestItem
    e = lambda s: html.escape(s or '', quote=True)
    url = site_url() + reverse('stories:story_detail', args=[story.slug])
    found = [(html.unescape(src), _plain(title), _plain(topic))
             for src, title, topic in _ITEM.findall(story.content or '')][:MAX_ITEMS]
    rows = {r.url: r for r in DigestItem.objects.filter(url__in=[f[0] for f in found])}
    if translate:
        try:
            translate_fa([rows[u] for u, _, _ in found if u in rows])
        except Exception as exc:
            logger.warning('Persian translation failed: %s', exc)
    head = ('🏆 <b>مهم‌ترین خبرهای هوش مصنوعی این هفته</b>' if story.is_weekly
            else '📰 <b>خلاصهٔ خبرهای هوش مصنوعی و یادگیری ماشین</b>')
    lines = [head, f'<i>{e(story.title)}</i>', '']
    tail = ['📖 خلاصهٔ کامل و همهٔ منابع (انگلیسی):', url]
    topics = []
    for src, title, topic in found:
        r = rows.get(src)
        source = (r.source if r else '').split(' (')[0] or 'منبع'
        if r and r.fa_summary:
            block = f'🔹 <b>{e(r.fa_title or title)}</b>\n{e(r.fa_summary)}\n🔗 منبع: <a href="{e(src)}">{e(source)}</a>'
        else:
            block = f'🔹 <b>{e(title)}</b>\n🔗 منبع: <a href="{e(src)}">{e(source)}</a>'
        if len('\n'.join(lines + [block] + tail)) > 3800:
            break
        lines += [block, '']
        if topic and topic not in topics:
            topics.append(topic)
    hashtags = ['#هوش_مصنوعی', '#یادگیری_ماشین', '#AI'] + ['#' + re.sub(r'[^A-Za-z0-9]', '', t) for t in topics[:3]]
    return '\n'.join(lines + tail + [' '.join(dict.fromkeys(h for h in hashtags if len(h) > 1))])[:4096]


def _story_url(post) -> str:
    return site_url() + reverse('stories:story_detail', args=[post.story.slug])


def review_url() -> str:
    return site_url() + reverse('stories:telegram_review')


# ── queue, review, publish ───────────────────────────────────────────────────

def queue_post(story):
    """Draft an announcement for a new digest and ask the owner to approve it."""
    from .models import TelegramPost
    if not configured():
        return None
    post = TelegramPost.objects.filter(story=story).first()
    if post and post.status != TelegramPost.PENDING:
        return post   # already sent or skipped
    if post:
        post.text = build_text(story)
        post.save(update_fields=['text'])
    else:
        post = TelegramPost.objects.create(story=story, text=build_text(story))
    try:
        notify_admin(post)
    except TelegramError as exc:
        logger.warning('Telegram review message failed: %s', exc)
    return post


def _buttons(post):
    return {'inline_keyboard': [
        [{'text': '✅ Publish', 'callback_data': f'tg:pub:{post.pk}'},
         {'text': '❌ Skip', 'callback_data': f'tg:skip:{post.pk}'}],
        [{'text': '✏️ Edit on the site', 'url': review_url()}],
    ]}


def notify_admin(post):
    """Send the draft to the owner's private chat with Publish / Skip buttons."""
    from .models import TelegramConfig
    cfg = TelegramConfig.get()
    if not cfg.admin_chat_id:
        return None   # not linked yet: the draft waits on the review page
    msg = api('sendMessage', chat_id=cfg.admin_chat_id, parse_mode='HTML',
              text=f'📝 <b>Waiting for your approval</b> (channel {html.escape(channel())}):\n\n{post.text}',
              link_preview_options={'is_disabled': True}, reply_markup=_buttons(post))
    post.review_message_id = msg.get('message_id')
    post.save(update_fields=['review_message_id'])
    return msg


def publish_post(post) -> bool:
    """Post to the channel once (a second press does nothing)."""
    from .models import TelegramPost
    claimed = TelegramPost.objects.filter(
        pk=post.pk, status__in=[TelegramPost.PENDING, TelegramPost.FAILED]).update(status=TelegramPost.SENDING)
    if not claimed:
        return False
    post.refresh_from_db()
    try:
        msg = api('sendMessage', chat_id=channel(), text=post.text, parse_mode='HTML',
                  link_preview_options={'url': _story_url(post)})
    except TelegramError as exc:
        post.status, post.error = TelegramPost.FAILED, str(exc)[:500]
        post.save(update_fields=['status', 'error'])
        return False
    post.status, post.error = TelegramPost.SENT, ''
    post.channel_message_id, post.sent_at = msg.get('message_id'), timezone.now()
    post.save(update_fields=['status', 'error', 'channel_message_id', 'sent_at'])
    return True


def skip_post(post) -> bool:
    from .models import TelegramPost
    return bool(TelegramPost.objects.filter(
        pk=post.pk, status__in=[TelegramPost.PENDING, TelegramPost.FAILED]).update(status=TelegramPost.SKIPPED))


def new_link_code() -> str:
    from .models import TelegramConfig
    cfg = TelegramConfig.get()
    cfg.link_code = secrets.token_urlsafe(18)[:24].replace('-', 'x').replace('_', 'y')
    if not cfg.bot_username:
        try:
            cfg.bot_username = api('getMe').get('username', '')
        except TelegramError:
            pass
    cfg.save()
    return cfg.link_code


# ── webhook ──────────────────────────────────────────────────────────────────

def handle_update(update: dict):
    from .models import TelegramConfig, TelegramPost
    cfg = TelegramConfig.get()
    msg = update.get('message') or {}
    text = (msg.get('text') or '').strip()
    if text.startswith('/start'):
        chat = msg.get('chat') or {}
        code = text[len('/start'):].strip()
        if chat.get('type') == 'private' and cfg.link_code and code and hmac.compare_digest(code, cfg.link_code):
            cfg.admin_chat_id = chat.get('id')
            cfg.admin_name = (chat.get('username') or chat.get('first_name') or '')[:100]
            cfg.link_code = ''
            cfg.save()
            api('sendMessage', chat_id=chat['id'],
                text='✅ Connected. New digest announcements will come here for your approval before they '
                     'go to the channel.')
        elif chat.get('id'):
            api('sendMessage', chat_id=chat['id'],
                text=f'This bot posts the HasanAI AI & ML news digest. Read it at {site_url()}/stories/')
        return
    cb = update.get('callback_query')
    if not cb:
        return
    who = (cb.get('from') or {}).get('id')
    data = cb.get('data') or ''
    radar = re.fullmatch(r'rr:add:(\d+)', data)
    if radar and cfg.admin_chat_id and who == cfg.admin_chat_id:
        # Repo Radar: add a repository to the next daily digest; the keyboard stays for the others.
        from .models import RadarRepo
        from .radar import add_to_digest
        repo = RadarRepo.objects.filter(pk=int(radar.group(1))).first()
        note = ('➕ Added to the next digest: ' + repo.full_name if repo and add_to_digest(repo)
                else 'Already added.' if repo else 'Not found.')
        api('answerCallbackQuery', callback_query_id=cb['id'], text=note[:190])
        return
    m = re.fullmatch(r'tg:(pub|skip):(\d+)', data)
    if not cfg.admin_chat_id or who != cfg.admin_chat_id or not m:
        api('answerCallbackQuery', callback_query_id=cb['id'], text='Not allowed.')
        return
    post = TelegramPost.objects.filter(pk=int(m.group(2))).first()
    if post is None:
        note = 'This draft no longer exists.'
    elif m.group(1) == 'pub':
        if publish_post(post):
            note = '✅ Published to the channel.'
        else:
            post.refresh_from_db()
            note = f'Not sent: {post.error}' if post.status == TelegramPost.FAILED else f'Already {post.status}.'
    else:
        note = '❌ Skipped.' if skip_post(post) else f'Already {post.status}.'
    api('answerCallbackQuery', callback_query_id=cb['id'], text=note[:190])
    chat_id = ((cb.get('message') or {}).get('chat') or {}).get('id')
    if chat_id:
        try:
            api('editMessageReplyMarkup', chat_id=chat_id, message_id=cb['message']['message_id'],
                reply_markup={'inline_keyboard': [[{'text': note[:60], 'url': review_url()}]]})
        except TelegramError:
            pass


_webhook_ok = False


def ensure_webhook(force=False) -> bool:
    """Point the bot at this site's webhook (once per process)."""
    global _webhook_ok
    if (_webhook_ok and not force) or not configured() or not site_url().startswith('https://'):
        return _webhook_ok
    from .models import TelegramConfig
    url = site_url() + reverse('stories:telegram_webhook')
    api('setWebhook', url=url, secret_token=webhook_secret(), allowed_updates=['message', 'callback_query'])
    cfg = TelegramConfig.get()
    if cfg.webhook_url != url:
        cfg.webhook_url = url
        cfg.save(update_fields=['webhook_url'])
    _webhook_ok = True
    return True
