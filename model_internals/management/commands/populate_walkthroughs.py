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

# Order here is the order the cards appear in, and it is meant to be read as a
# progression: linear models, then instance/probabilistic, trees and ensembles,
# margin methods, unsupervised, and finally neural networks and transformers.
WALKTHROUGHS = [
    dict(
        notebook='how_models_work_linear_regression.ipynb',
        title='Linear Regression',
        tagline='The normal equation solved by hand, and why least squares is a projection',
        summary='The design matrix, X^T X inverted entry by entry, the closed-form solution, '
                'the same answer reached again by gradient descent, and ridge vs lasso - all '
                'checked against scikit-learn.',
        category='linear', difficulty='beginner', icon='\U0001f4c8',
        references=[dict(
            title='The Elements of Statistical Learning, ch. 3',
            authors='Hastie, Tibshirani & Friedman, 2009',
            url='https://hastie.su.domains/ElemStatLearn/',
        )],
    ),
    dict(
        notebook='how_models_work_logistic_regression.ipynb',
        title='Logistic Regression',
        tagline='Why the sigmoid and log-loss belong together, and where the gradient comes from',
        summary='The p(1-p) cancellation derived term by term, gradient descent and Newton/IRLS '
                'run side by side, odds ratios, and what regularisation fixes on separable data.',
        category='linear', difficulty='beginner', icon='\U0001f4c9',
        references=[dict(
            title='Pattern Recognition and Machine Learning, ch. 4',
            authors='Bishop, 2006', url='',
        )],
    ),
    dict(
        notebook='how_models_work_knn.ipynb',
        title='K-Nearest Neighbours',
        tagline='Distance, the effect of k, and the curse of dimensionality demonstrated',
        summary='Every distance computed and ranked, the vote counted by hand, why unscaled '
                'features silently break it, and the collapse of distance contrast measured up '
                'to 1000 dimensions.',
        category='instance', difficulty='beginner', icon='\U0001f4cd',
        references=[dict(
            title='Nearest Neighbor Pattern Classification',
            authors='Cover & Hart, 1967 (IEEE Trans. Inf. Theory)',
            url='https://ieeexplore.ieee.org/document/1053964',
        )],
    ),
    dict(
        notebook='how_models_work_naive_bayes.ipynb',
        title='Naive Bayes',
        tagline='Bayes rule, conditional independence, and what the naive assumption really costs',
        summary='Priors and per-feature likelihoods fitted by hand, one point classified in log '
                'space step by step, Laplace smoothing, and a duplicated-feature experiment that '
                'exposes the over-confidence.',
        category='bayes', difficulty='beginner', icon='\U0001f3b2',
        references=[dict(
            title='On the Optimality of the Simple Bayesian Classifier under Zero-One Loss',
            authors='Domingos & Pazzani, 1997 (Machine Learning 29)',
            url='https://link.springer.com/article/10.1023/A:1007413511361',
        )],
    ),
    dict(
        notebook='how_models_work_decision_tree.ipynb',
        title='Decision Tree',
        tagline='Greedy recursive partitioning, with every candidate split scored by hand',
        summary='Gini impurity, all 33 candidate splits ranked, a gain curve per feature, the '
                'tree drawn stage by stage with its criteria inside each node, and a check '
                'against scikit-learn.',
        category='classical', difficulty='beginner', icon='\U0001f333',
        references=[dict(
            title='Classification and Regression Trees',
            authors='Breiman, Friedman, Olshen & Stone, 1984', url='',
        )],
    ),
    dict(
        notebook='how_models_work_random_forest.ipynb',
        title='Random Forest',
        tagline='Bootstrap, feature subsampling, and why averaging decorrelated trees kills variance',
        summary='Every bootstrap draw and OOB set printed, all five trees drawn, votes counted by '
                'hand, the variance formula verified by simulation, and MDI importance matched '
                'against scikit-learn exactly.',
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
        summary='Gradients and Hessians for all 12 rows, the leaf-weight derivation, every split '
                'gain ranked, the tree drawn with G/H/similarity/gain inside each node, and both '
                'trees matched leaf-for-leaf against the real xgboost.',
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
        summary='Feature binning and prefix-sum scans step by step, the histogram subtraction '
                'trick verified, leaf-wise vs level-wise drawn side by side, GOSS tested on 5000 '
                'rows, and the tree matched against real lightgbm.',
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
        summary='The target-encoding leak demonstrated then closed row by row, ordered boosting '
                'contrasted with plain residuals, the oblivious tree drawn, and every leaf value '
                'matched against real catboost.',
        category='classical', difficulty='advanced', icon='\U0001f431',
        references=[dict(
            title='CatBoost: unbiased boosting with categorical features',
            authors='Prokhorenkova et al., 2018 (NeurIPS)',
            url='https://arxiv.org/abs/1706.09516',
        )],
    ),
    dict(
        notebook='how_models_work_svm.ipynb',
        title='Support Vector Machine',
        tagline='Maximum margin, the dual, and where the kernel trick comes from',
        summary='The margin derived, non-support vectors deleted to prove they do not matter, w '
                'recovered from the dual by hand, and the polynomial kernel checked against its '
                'explicit feature map.',
        category='svm', difficulty='advanced', icon='\U0001f6e1',
        references=[dict(
            title='Support-Vector Networks',
            authors='Cortes & Vapnik, 1995 (Machine Learning 20)',
            url='https://link.springer.com/article/10.1007/BF00994018',
        )],
    ),
    dict(
        notebook='how_models_work_svr.ipynb',
        title='Support Vector Regression',
        tagline='The epsilon-insensitive tube: when small errors cost exactly nothing',
        summary='The three loss shapes compared, the tube drawn with its support vectors, an '
                'outlier experiment against OLS, and the KKT structure (alpha = 0 inside, alpha = '
                'C outside) shown in a table.',
        category='svm', difficulty='advanced', icon='\U0001f4cf',
        references=[dict(
            title='A Tutorial on Support Vector Regression',
            authors='Smola & Scholkopf, 2004 (Statistics and Computing 14)',
            url='https://link.springer.com/article/10.1023/B:STCO.0000035301.49549.88',
        )],
    ),
    dict(
        notebook='how_models_work_kmeans.ipynb',
        title='K-Means',
        tagline="Lloyd's algorithm, iteration by iteration, and why it always converges",
        summary='k-means++ initialisation sampled by hand, every assign/update step printed with '
                'the distances and means, the monotone decrease verified, local minima counted '
                'over 200 restarts, and the shapes it cannot find.',
        category='clustering', difficulty='beginner', icon='\U0001f3af',
        references=[dict(
            title='k-means++: The Advantages of Careful Seeding',
            authors='Arthur & Vassilvitskii, 2007 (SODA)',
            url='https://theory.stanford.edu/~sergei/papers/kMeansPP-soda.pdf',
        )],
    ),
    dict(
        notebook='how_models_work_pca.ipynb',
        title='Principal Component Analysis',
        tagline='Rotate the axes onto the directions of greatest variance',
        summary='The covariance matrix built entry by entry, eigenvectors verified against 20000 '
                'random directions, reconstruction error shown to equal the discarded '
                'eigenvalues, and the SVD route compared.',
        category='dimred', difficulty='intermediate', icon='\U0001f300',
        references=[dict(
            title='Principal Component Analysis',
            authors='Jolliffe, 2002 (2nd ed.)', url='',
        )],
    ),
    dict(
        notebook='how_models_work_neural_network.ipynb',
        title='Neural Network & Backpropagation',
        tagline='The chain rule with its intermediate results kept - and gradient-checked',
        summary='Forward pass with every matrix printed, backpropagation derived and computed by '
                'hand, all 17 gradients verified against central differences, and a deliberately '
                'buggy version shown failing the same check.',
        category='neural', difficulty='intermediate', icon='\U0001f578',
        references=[
            dict(title='Learning representations by back-propagating errors',
                 authors='Rumelhart, Hinton & Williams, 1986 (Nature 323)',
                 url='https://www.nature.com/articles/323533a0'),
            dict(title='Deep Learning, ch. 6',
                 authors='Goodfellow, Bengio & Courville, 2016',
                 url='https://www.deeplearningbook.org/'),
        ],
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
