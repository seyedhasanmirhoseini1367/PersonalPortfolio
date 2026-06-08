"""
Core extraction logic — used by both the web UI and the management command.
"""
import json
import re
import threading
import requests
from django.utils import timezone
from django.utils.text import slugify


KAGGLE_BASE    = 'https://www.kaggle.com'
SCRAPE_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    )
}

TECHNIQUE_MAP = {
    'LightGBM':             ['lgbm', 'lightgbm', 'light gbm'],
    'XGBoost':              ['xgboost', ' xgb'],
    'CatBoost':             ['catboost'],
    'GBM':                  ['gradient boosting', ' gbm '],
    'Random Forest':        ['random forest'],
    'SVM':                  [' svm ', 'support vector'],
    'Neural Network':       ['neural network', 'deep learning', ' mlp '],
    'CNN':                  [' cnn ', 'convolutional neural'],
    'LSTM':                 [' lstm'],
    'GRU':                  [' gru '],
    'Transformer':          ['transformer'],
    'BERT':                 ['bert'],
    'RoBERTa':              ['roberta'],
    'DeBERTa':              ['deberta'],
    'GPT':                  [' gpt'],
    'T5':                   [' t5 ', 't5-'],
    'ResNet':               ['resnet'],
    'EfficientNet':         ['efficientnet'],
    'ViT':                  ['vision transformer', ' vit '],
    'YOLO':                 ['yolo'],
    'U-Net':                ['unet', 'u-net'],
    'ConvNeXt':             ['convnext'],
    'PyTorch':              ['pytorch'],
    'TensorFlow':           ['tensorflow'],
    'Keras':                ['keras'],
    'Scikit-learn':         ['sklearn', 'scikit'],
    'HuggingFace':          ['huggingface', 'hugging face'],
    'Ensemble':             ['ensemble'],
    'Stacking':             ['stacking'],
    'Blending':             ['blending'],
    'Pseudo Labeling':      ['pseudo label', 'pseudo-label'],
    'TTA':                  [' tta ', 'test-time augment', 'test time augment'],
    'Augmentation':         ['augmentation'],
    'Feature Engineering':  ['feature engineering', 'feature selection'],
    'Cross Validation':     ['cross.validation', 'cross-validation', 'k-fold', 'kfold'],
    'Hyperparameter Tuning':['optuna', 'hyperparameter', 'hyperparam'],
    'Word Embeddings':      ['word2vec', 'fasttext', 'glove'],
    'Object Detection':     ['object detection'],
    'Segmentation':         ['segmentation'],
}

TYPE_SIGNALS = {
    'cv':         ['image', 'vision', 'detection', 'segmentation', 'object-detection', 'photo', 'pixel', 'visual', 'medical-imaging'],
    'nlp':        ['nlp', 'text', 'language', 'bert', 'sentiment', 'translation', 'ner', 'named-entity', 'natural-language'],
    'timeseries': ['time-series', 'timeseries', 'forecasting', 'time-series-analysis'],
    'audio':      ['audio', 'speech', 'sound', 'acoustic'],
    'tabular':    ['tabular', 'structured-data', 'classification', 'regression', 'feature-engineering', 'binary-classification'],
    'rl':         ['reinforcement-learning', 'simulation', 'agent'],
    'multimodal': ['multimodal', 'multi-modal'],
}

DOMAIN_SIGNALS = {
    'healthcare':  ['health', 'medical', 'disease', 'cancer', 'clinical', 'patient', 'drug', 'pharma', 'diagnosis', 'covid', 'lung', 'brain'],
    'finance':     ['finance', 'financial', 'stock', 'trading', 'market', 'credit', 'fraud', 'price', 'currency', 'bank', 'loan'],
    'science':     ['science', 'physics', 'chemistry', 'biology', 'astronomy', 'particle', 'molecule', 'protein', 'dna', 'gene'],
    'retail':      ['retail', 'ecommerce', 'sales', 'product', 'customer', 'demand', 'inventory', 'recommend'],
    'environment': ['climate', 'environment', 'weather', 'satellite', 'land', 'ocean', 'pollution', 'wildfire', 'flood'],
    'autonomous':  ['autonomous', 'self-driving', 'vehicle', 'driving', 'lidar'],
    'government':  ['government', 'election', 'census', 'crime', 'safety', 'traffic'],
    'nlp_domain':  ['nlp', 'natural-language', 'text', 'language', 'sentiment'],
}


def rank_to_medal(rank):
    return {1: 'gold', 2: 'silver', 3: 'bronze'}.get(rank, 'other')


class KaggleExtractor:
    def __init__(self, url, top_n=10, log_fn=None):
        self.url   = url
        self.top_n = min(top_n, 50)
        self.log   = log_fn or (lambda msg: None)
        self.slug  = None
        self.api   = None

    def run(self):
        self.slug = self._parse_slug(self.url)
        self.log(f'Slug: {self.slug}')

        try:
            from kaggle import api as kaggle_api
            kaggle_api.authenticate()
            self.api = kaggle_api
            self.log('Kaggle API authenticated')
        except Exception as exc:
            raise RuntimeError(f'Kaggle auth failed: {exc}')

        self.log('Fetching competition metadata...')
        meta = self._fetch_meta()
        if not meta:
            raise RuntimeError(
                f'Competition "{self.slug}" not found. '
                'Check the URL and that you have accepted competition rules.'
            )
        self.log(f'Found: {meta["name"]}')
        self.log(f'Host: {meta["host"]} | Teams: {meta["num_teams"]} | Prize: {meta["prize_pool"]}')
        self.log(f'Type: {meta["competition_type"]} | Domain: {meta["domain"]}')

        comp = self._save_competition(meta)
        self.log('Competition saved to database')

        self.log(f'Fetching top {self.top_n} leaderboard entries...')
        leaderboard = self._fetch_leaderboard()
        if not leaderboard:
            raise RuntimeError('Could not fetch leaderboard. Have you accepted the competition rules?')
        self.log(f'Got {len(leaderboard)} leaderboard entries')

        self.log('Fetching official writeups...')
        writeups = self._list_writeups()
        self.log(f'Found {len(writeups)} writeups')

        self.log('Saving leaderboard solutions with writeup content...')
        saved = self._save_solutions(comp, leaderboard, writeups)
        self.log(f'Saved {saved} leaderboard entries')

        self.log('Done')
        return {'competition': comp, 'saved': saved}

    # ── Kaggle API helpers ────────────────────────────────────────────────────

    def _parse_slug(self, raw):
        raw = raw.strip().rstrip('/')
        m = re.search(r'kaggle\.com/competitions/([^/?#]+)', raw)
        if m:
            return m.group(1)
        m = re.search(r'kaggle\.com/c/([^/?#]+)', raw)
        if m:
            return m.group(1)
        return raw

    def _fetch_meta(self):
        try:
            resp  = self.api.competitions_list(search=self.slug)
            comps = resp.competitions if resp else []
            comp  = next((c for c in comps if c.ref.rstrip('/').endswith(f'/{self.slug}')), None)
            if not comp:
                comp = comps[0] if len(comps) == 1 else None
            if not comp:
                return None

            tags    = [t.get('ref', '') if isinstance(t, dict) else getattr(t, 'ref', '') for t in (comp.tags or [])]
            tag_str = ' '.join(tags).lower()
            title_l = (comp.title or '').lower()

            return {
                'name':             comp.title or self.slug,
                'host':             comp.organization_name or 'Kaggle',
                'num_teams':        comp.team_count or 0,
                'prize_pool':       comp.reward or '',
                'kaggle_url':       comp.url or f'{KAGGLE_BASE}/competitions/{self.slug}',
                'evaluation_metric':comp.evaluation_metric or '',
                'end_date':         self._parse_date(comp.deadline),
                'competition_type': self._detect_type(tag_str, title_l),
                'domain':           self._detect_domain(tag_str, title_l),
            }
        except Exception as exc:
            self.log(f'Meta error: {exc}')
            return None

    def _parse_date(self, deadline):
        if not deadline:
            return None
        try:
            if hasattr(deadline, 'date'):
                return deadline.date()
            from django.utils.dateparse import parse_date
            return parse_date(str(deadline)[:10])
        except Exception:
            return None

    def _detect_type(self, tags, title):
        combined = tags + ' ' + title
        scores = {t: sum(1 for kw in kws if kw in combined) for t, kws in TYPE_SIGNALS.items()}
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else 'other'

    def _detect_domain(self, tags, title):
        combined = tags + ' ' + title
        scores = {d: sum(1 for kw in kws if kw in combined) for d, kws in DOMAIN_SIGNALS.items()}
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else 'other'

    def _save_competition(self, meta):
        from .models import Competition
        comp, _ = Competition.objects.update_or_create(
            slug=self.slug,
            defaults={
                'name':             meta['name'],
                'host':             meta['host'],
                'num_teams':        meta['num_teams'],
                'prize_pool':       meta['prize_pool'],
                'kaggle_url':       meta['kaggle_url'],
                'evaluation_metric':meta['evaluation_metric'],
                'end_date':         meta['end_date'],
                'competition_type': meta['competition_type'],
                'domain':           meta['domain'],
            }
        )
        return comp

    def _fetch_leaderboard(self):
        try:
            entries = self.api.competition_leaderboard_view(self.slug, page_size=self.top_n)
            return (entries or [])[:self.top_n]
        except Exception as exc:
            self.log(f'Leaderboard error: {exc}')
            return []

    # ── Writeup scraper ───────────────────────────────────────────────────────

    def _get_next_data(self, html):
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(1))
        except Exception:
            return None

    def _list_writeups(self):
        """Return official writeups via Kaggle API topics filtered to /writeups/ URLs."""
        try:
            resp   = self.api.competition_list_topics(self.slug, sort_by='top', page=1)
            topics = resp.topics if resp else []
            result = []
            for topic in topics:
                raw_url = getattr(topic, 'topic_url', '') or ''
                if '/writeups/' not in raw_url:
                    continue
                url  = f'{KAGGLE_BASE}{raw_url}' if raw_url.startswith('/') else raw_url
                slug = url.rstrip('/').split('/')[-1]
                title  = topic.title or ''
                author = getattr(topic, 'author_name', '') or ''
                result.append({
                    'url':    url,
                    'slug':   slug,
                    'title':  title,
                    'author': author,
                    'rank':   self._parse_rank(title),
                    '_topic': topic,          # kept for API content fetch
                })
            return result
        except Exception as exc:
            self.log(f'  [warn] _list_writeups failed: {exc}')
            return []

    def _fetch_writeup(self, url, topic=None):
        """Fetch writeup content via competition_list_topic_messages (raw_markdown field)."""
        if topic is not None:
            try:
                msgs  = self.api.competition_list_topic_messages(
                    self.slug, topic.id, page_size=1
                )
                items = getattr(msgs, 'messages', None) or []
                if items:
                    md = getattr(items[0], 'raw_markdown', None) or ''
                    if md:
                        return {
                            'title':            topic.title or '',
                            'author':           getattr(topic, 'author_name', '') or '',
                            'content_markdown': md[:100_000],
                        }
            except Exception as exc:
                self.log(f'  [warn] topic_messages failed: {exc}')

        # Fallback: scrape the individual writeup page
        try:
            resp = requests.get(url, timeout=20, headers=SCRAPE_HEADERS)
            if resp.status_code != 200:
                self.log(f'  [warn] writeup page HTTP {resp.status_code}: {url}')
                return None
            data = self._get_next_data(resp.text)
            if data:
                page_props = data.get('props', {}).get('pageProps', {})
                content, title, author = self._extract_writeup_fields(page_props)
                if content:
                    return {
                        'title':            title,
                        'author':           author,
                        'content_markdown': self._clean_content(content)[:100_000],
                    }
            return self._html_fallback(resp.text)
        except Exception as exc:
            self.log(f'  [warn] _fetch_writeup failed for {url}: {exc}')
            return None

    def _find_list_in(self, obj, _depth=0):
        """DFS: return the first list in obj whose items look like writeup dicts."""
        if _depth > 8:
            return None
        if isinstance(obj, list) and obj and isinstance(obj[0], dict):
            if any(k in obj[0] for k in ('slug', 'urlSlug', 'title', 'name')):
                return obj
        if isinstance(obj, dict):
            for key in ('writeups', 'writeupList', 'posts', 'topics', 'items', 'results', 'data'):
                if key in obj:
                    found = self._find_list_in(obj[key], _depth + 1)
                    if found:
                        return found
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    found = self._find_list_in(v, _depth + 1)
                    if found:
                        return found
        elif isinstance(obj, list):
            for item in obj:
                found = self._find_list_in(item, _depth + 1)
                if found:
                    return found
        return None

    def _extract_writeup_fields(self, page_props):
        """Try multiple known paths for content / title / author."""
        content = title = author = ''

        paths = [
            ['writeup', 'markdown'],        ['writeup', 'body'],
            ['writeup', 'renderedMarkdown'],['writeup', 'content'],
            ['post', 'markdown'],           ['post', 'body'],
            ['topic', 'body'],              ['topic', 'markdown'],
            ['solution', 'body'],           ['solution', 'markdown'],
            ['pageData', 'markdown'],       ['pageData', 'body'],
        ]
        for path in paths:
            node = page_props
            try:
                for key in path:
                    node = node[key]
                if isinstance(node, str) and len(node) > 200:
                    content = node
                    break
            except (KeyError, TypeError):
                continue

        if not content:
            content = self._longest_string(page_props) or ''

        for wk in ('writeup', 'post', 'topic', 'solution', 'pageData'):
            if wk in page_props and isinstance(page_props[wk], dict):
                w      = page_props[wk]
                title  = title  or w.get('title') or w.get('name') or ''
                author = author or self._extract_author(w)
                break

        return content, title, author

    def _longest_string(self, obj, min_len=500, _depth=0):
        """Recursively find the longest string in a nested structure."""
        if _depth > 10:
            return None
        if isinstance(obj, str):
            return obj if len(obj) >= min_len else None
        best = ''
        items = obj.values() if isinstance(obj, dict) else (obj if isinstance(obj, list) else [])
        for v in items:
            c = self._longest_string(v, min_len, _depth + 1)
            if c and len(c) > len(best):
                best = c
        return best or None

    def _extract_author(self, obj):
        if not isinstance(obj, dict):
            return ''
        auth = (obj.get('author') or obj.get('authorDisplayName') or
                obj.get('authorName') or obj.get('userName') or '')
        if isinstance(auth, dict):
            return (auth.get('displayName') or auth.get('name') or
                    auth.get('username') or '')
        return str(auth)

    def _clean_content(self, text):
        if not text or '<' not in text:
            return text
        try:
            from bs4 import BeautifulSoup
            return BeautifulSoup(text, 'html.parser').get_text(separator='\n')
        except ImportError:
            return re.sub(r'<[^>]+>', '', text)

    def _html_fallback(self, html):
        try:
            from bs4 import BeautifulSoup
            soup  = BeautifulSoup(html, 'html.parser')
            title = soup.title.get_text() if soup.title else ''
            main  = soup.find('main') or soup.find('article') or soup.find('body')
            text  = main.get_text(separator='\n') if main else ''
            return {'title': title, 'author': '', 'content_markdown': text[:100_000]}
        except Exception as exc:
            self.log(f'  [warn] html_fallback failed: {exc}')
            return None

    @staticmethod
    def _parse_rank(title):
        m = re.search(r'(\d+)\s*(?:st|nd|rd|th)\s*place', title or '', re.IGNORECASE)
        return int(m.group(1)) if m else None

    # ── Save solutions ────────────────────────────────────────────────────────

    def _save_solutions(self, comp, leaderboard, writeups):
        from .models import Solution, Technique

        by_rank = {w['rank']: w for w in writeups if w['rank'] is not None}
        saved   = 0

        for idx, entry in enumerate(leaderboard[:self.top_n], 1):
            team_name = entry.team_name or f'Team #{idx}'
            score     = str(entry.score) if entry.score else ''
            medal     = rank_to_medal(idx)

            # Match writeup: by rank, then by team-name substring in title/author
            meta = by_rank.get(idx)
            if not meta:
                team_l = team_name.lower()
                for w in writeups:
                    if (team_l in (w['title'] or '').lower() or
                            team_l in (w['author'] or '').lower()):
                        meta = w
                        break

            writeup_url = writeup_title = writeup_author = writeup_content = ''
            writeup_fetched_at = None

            if meta:
                writeup_url    = meta['url']
                writeup_title  = meta['title']
                writeup_author = meta['author']
                detail = self._fetch_writeup(writeup_url, meta.get('_topic'))
                if detail:
                    writeup_content    = detail.get('content_markdown', '')
                    writeup_title      = detail.get('title') or writeup_title
                    writeup_author     = detail.get('author') or writeup_author
                    writeup_fetched_at = timezone.now()

            tech_names = self._extract_techniques(writeup_content)

            sol, _ = Solution.objects.update_or_create(
                competition=comp,
                rank=idx,
                defaults={
                    'team_name':          team_name,
                    'score':              score,
                    'medal':              medal,
                    'is_public':          True,
                    'writeup_url':        writeup_url,
                    'writeup_title':      writeup_title,
                    'writeup_author':     writeup_author,
                    'writeup_content':    writeup_content,
                    'writeup_fetched_at': writeup_fetched_at,
                }
            )

            tech_objs = []
            for name in tech_names:
                obj, _ = Technique.objects.get_or_create(name=name, defaults={'slug': slugify(name)})
                tech_objs.append(obj)
            sol.techniques.set(tech_objs)

            has  = 'yes' if writeup_content else ('url-only' if writeup_url else 'no')
            safe = team_name[:40].encode('ascii', 'replace').decode('ascii')
            sfx  = f' | techs: {", ".join(tech_names[:3])}' if tech_names else ''
            self.log(f'  #{idx} {safe} | score: {score} | writeup: {has}{sfx}')
            saved += 1

        return saved

    # ── Technique extraction ──────────────────────────────────────────────────

    def _extract_techniques(self, text):
        text_l = f' {text.lower()} '
        return [tech for tech, kws in TECHNIQUE_MAP.items() if any(kw in text_l for kw in kws)]


# ── Background thread runner ──────────────────────────────────────────────────

def run_job_in_background(job_id):
    thread = threading.Thread(target=_run_job, args=(job_id,), daemon=True)
    thread.start()


def _run_job(job_id):
    from django.db import connection
    connection.close()

    from .models import ExtractionJob

    job = ExtractionJob.objects.get(id=job_id)
    job.status = ExtractionJob.STATUS_RUNNING
    job.save(update_fields=['status'])

    lines = []

    def log_fn(msg):
        lines.append(msg)
        ExtractionJob.objects.filter(id=job_id).update(log='\n'.join(lines))

    try:
        extractor = KaggleExtractor(job.url, job.top_n, log_fn=log_fn)
        result    = extractor.run()
        job.refresh_from_db()
        job.status          = ExtractionJob.STATUS_DONE
        job.competition     = result['competition']
        job.solutions_saved = result['saved']
        job.finished_at     = timezone.now()
        job.log             = '\n'.join(lines)
        job.save()
    except Exception as exc:
        lines.append(f'ERROR: {exc}')
        ExtractionJob.objects.filter(id=job_id).update(
            status=ExtractionJob.STATUS_FAILED,
            log='\n'.join(lines),
            finished_at=timezone.now(),
        )
