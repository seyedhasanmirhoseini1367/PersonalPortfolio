"""Rebuild the "How Models Work" section from the notebooks in ml_training/.

The walkthrough content lives in the database and the plot images live in
MEDIA_ROOT, and neither is committed to git. This command regenerates both from
the notebooks, so a fresh deploy reproduces the section without any manual step.

Run on every startup with --if-empty. Each walkthrough stores the sha256 of the
notebook it came from, so an unchanged notebook is skipped but an edited one is
re-imported -- otherwise the content would be frozen at whatever the first
deploy happened to create.
"""
import hashlib

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from model_internals.models import Walkthrough, WalkthroughReference

# Order here is the order the cards appear in.
WALKTHROUGHS = [
    dict(
        notebook='transformer_autoregressive_enc_dec.ipynb',
        title='Autoregressive Transformer: Encoder + Decoder',
        tagline='Every matrix multiplication, formula, and manual calculation behind a '
                'from-scratch NumPy Transformer',
        summary='Follow one sentence through embeddings, positional encoding, multi-head '
                'attention, masked decoding, cross-attention, and the final softmax - with '
                'every shape and number worked out by hand.',
        category='transformer', difficulty='intermediate', icon='\U0001f9ee',
        references=[dict(
            title='Attention Is All You Need',
            authors='Vaswani et al., 2017 (NeurIPS)',
            url='https://arxiv.org/abs/1706.03762',
        )],
    ),
    dict(
        notebook='how_models_work_bert_eeg.ipynb',
        title='BERT on EEG',
        tagline='Bidirectional masked reconstruction - the same encoder, no causal mask, '
                'a signal instead of text',
        summary='Raw EEG cut into patches, projected, masked, and reconstructed. Every matrix '
                'printed, the bidirectional attention matrix contrasted with the causal one, '
                'and MSE computed on masked positions only.',
        category='transformer', difficulty='intermediate', icon='\U0001f9e0',
        references=[
            dict(title='BERT: Pre-training of Deep Bidirectional Transformers for Language '
                       'Understanding',
                 authors='Devlin et al., 2019 (NAACL)',
                 url='https://arxiv.org/abs/1810.04805'),
            dict(title='Masked Autoencoders Are Scalable Vision Learners',
                 authors='He et al., 2022 (CVPR)',
                 url='https://arxiv.org/abs/2111.06377'),
        ],
    ),
    dict(
        notebook='how_models_work_decision_tree.ipynb',
        title='Decision Tree',
        tagline='Greedy recursive partitioning, with every candidate split scored by hand',
        summary='Gini impurity, all 33 candidate splits ranked, the recursion that grows the '
                'tree, and a node-for-node check against scikit-learn.',
        category='classical', difficulty='beginner', icon='\U0001f333',
        references=[dict(
            title='Classification and Regression Trees',
            authors='Breiman, Friedman, Olshen & Stone, 1984',
            url='',
        )],
    ),
    dict(
        notebook='how_models_work_random_forest.ipynb',
        title='Random Forest',
        tagline='Bootstrap, feature subsampling, and why averaging decorrelated trees kills '
                'variance',
        summary='Every bootstrap draw and OOB set printed, votes counted by hand, the variance '
                'formula verified by simulation, and MDI importance matched against '
                'scikit-learn exactly.',
        category='classical', difficulty='beginner', icon='\U0001f332',
        references=[dict(
            title='Random Forests',
            authors='Breiman, 2001 (Machine Learning 45)',
            url='https://link.springer.com/article/10.1023/A:1010933404324',
        )],
    ),
    dict(
        notebook='how_models_work_xgboost.ipynb',
        title='XGBoost',
        tagline='Second-order Taylor expansion, similarity scores, and the closed-form gain',
        summary='Gradients and Hessians for all 12 rows, the leaf-weight derivation, every '
                'split gain ranked, and both trees matched leaf-for-leaf against the real '
                'xgboost library.',
        category='classical', difficulty='advanced', icon='⚡',
        references=[dict(
            title='XGBoost: A Scalable Tree Boosting System',
            authors='Chen & Guestrin, 2016 (KDD)',
            url='https://arxiv.org/abs/1603.02754',
        )],
    ),
    dict(
        notebook='how_models_work_lightgbm.ipynb',
        title='LightGBM',
        tagline='Histogram binning, leaf-wise growth, and GOSS - the same math, a faster search',
        summary='Feature binning and prefix-sum scans shown step by step, the histogram '
                'subtraction trick verified, leaf-wise vs level-wise compared, GOSS tested on '
                '5000 rows, and the tree matched against real lightgbm.',
        category='classical', difficulty='advanced', icon='\U0001f4a1',
        references=[dict(
            title='LightGBM: A Highly Efficient Gradient Boosting Decision Tree',
            authors='Ke et al., 2017 (NeurIPS)',
            url='https://papers.nips.cc/paper_files/paper/2017/hash/'
                '6449f44a102fde848669bdd9eb6b76fa-Abstract.html',
        )],
    ),
    dict(
        notebook='how_models_work_catboost.ipynb',
        title='CatBoost',
        tagline='Ordered target statistics, ordered boosting, and oblivious trees',
        summary='The target-encoding leak demonstrated and then closed row by row, ordered '
                'boosting contrasted with plain residuals, oblivious leaf indices computed as '
                'bits, and every leaf value matched against real catboost.',
        category='classical', difficulty='advanced', icon='\U0001f431',
        references=[dict(
            title='CatBoost: unbiased boosting with categorical features',
            authors='Prokhorenkova et al., 2018 (NeurIPS)',
            url='https://arxiv.org/abs/1706.09516',
        )],
    ),
]


class Command(BaseCommand):
    help = 'Import every "How Models Work" notebook from ml_training/.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--if-empty', action='store_true',
            help='Skip walkthroughs whose notebook is unchanged since the last import. '
                 'Safe to run on every startup, and still picks up edited notebooks.')

    def handle(self, *args, **options):
        nb_dir = settings.BASE_DIR / 'ml_training'
        done = skipped = missing = 0

        for order, spec in enumerate(WALKTHROUGHS, start=1):
            path = nb_dir / spec['notebook']
            if not path.exists():
                self.stdout.write(self.style.WARNING(f'missing notebook: {path} - skipping'))
                missing += 1
                continue

            fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
            before = Walkthrough.objects.filter(title=spec['title']).first()
            up_to_date = bool(before and before.blocks.exists()
                              and before.source_fingerprint == fingerprint)

            call_command(
                'import_walkthrough_notebook', str(path),
                title=spec['title'], tagline=spec['tagline'], summary=spec['summary'],
                category=spec['category'], difficulty=spec['difficulty'],
                icon=spec['icon'], order=order,
                if_empty=options['if_empty'],
            )

            if options['if_empty'] and up_to_date:
                skipped += 1
            else:
                done += 1

            w = Walkthrough.objects.filter(title=spec['title']).first()
            if w:
                # order is authoritative here even when the import was skipped
                if w.order != order:
                    w.order = order
                    w.save(update_fields=['order'])
                for i, ref in enumerate(spec.get('references', []), start=1):
                    WalkthroughReference.objects.get_or_create(
                        walkthrough=w, title=ref['title'],
                        defaults=dict(order=i, authors=ref['authors'], url=ref['url']),
                    )

        self.stdout.write(self.style.SUCCESS(
            f'walkthroughs: {done} imported/updated, {skipped} unchanged, {missing} missing'))
