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
        notebook='how_models_work_learning_concepts.ipynb',
        title='How Models Learn: The Concepts',
        tagline='Loss, gradient, learning rate, bias, variance, overfitting - defined with '
                'numbers you can check',
        summary='The ideas every algorithm shares, before any specific algorithm. The learning '
                'loop drawn, derivatives computed by hand, the bias-variance decomposition '
                'verified numerically against measured error, and the overfitting U-curve built '
                'from real numbers. Read this one first.',
        category='foundations', difficulty='beginner', icon='\U0001f9ed',
        references=[
            dict(title='The Elements of Statistical Learning, ch. 2 & 7',
                 authors='Hastie, Tibshirani & Friedman, 2009',
                 url='https://hastie.su.domains/ElemStatLearn/'),
            dict(title='Understanding the Bias-Variance Tradeoff',
                 authors='Fortmann-Roe, 2012',
                 url='http://scott.fortmann-roe.com/docs/BiasVariance.html'),
        ],
    ),
    dict(
        notebook='how_models_work_evaluation_metrics.ipynb',
        title='Evaluation Metrics',
        tagline='Why accuracy lies on imbalanced data, and what to read instead',
        summary='A 5%-positive problem where predicting no scores 95%. Confusion matrix, precision/recall/F1 by hand, the threshold as a policy choice, and ROC/AUC built point by point then verified two independent ways.',
        category='foundations', difficulty='beginner', icon='\U0001f3af',
        references=[dict(
            title='An Introduction to ROC Analysis',
            authors='Fawcett, 2006 (Pattern Recognition Letters)',
            url='https://www.sciencedirect.com/science/article/pii/S016786550500303X',
        )],
    ),
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
        notebook='how_models_work_optimizers.ipynb',
        title='Optimisers: SGD to Adam',
        tagline='Momentum, RMSProp and Adam built up one fix at a time',
        summary='Each optimiser added to solve a specific failure of the last, every update computed by hand, bias correction explained, and all four matched against torch.optim to machine precision.',
        category='foundations', difficulty='intermediate', icon='\U0001f680',
        references=[dict(
            title='Adam: A Method for Stochastic Optimization',
            authors='Kingma & Ba, 2015 (ICLR)',
            url='https://arxiv.org/abs/1412.6980',
        )],
    ),
    dict(
        notebook='how_models_work_cross_validation.ipynb',
        title='Cross-Validation & Model Selection',
        tagline='One split is a sample, not a measurement - and choosing between '
                'models spends the folds you chose on',
        summary='Folds written out by hand and checked against scikit-learn, the '
                'standard error nobody prints, stratified/group/time-series '
                'splitters, and the selection bias that makes a flat search report '
                '62% accuracy on data containing no signal at all.',
        category='validation', difficulty='beginner', icon='\U0001f501',
        references=[
            dict(title='A Study of Cross-Validation and Bootstrap for Accuracy '
                       'Estimation and Model Selection',
                 authors='Kohavi, 1995 (IJCAI)'),
            dict(title='On Over-fitting in Model Selection and Subsequent Selection '
                       'Bias in Performance Evaluation',
                 authors='Cawley & Talbot, 2010 (JMLR)'),
        ],
    ),
    dict(
        notebook='how_models_work_data_leakage.ipynb',
        title='Data Leakage',
        tagline='Five ways a validation score stops measuring what you think, each '
                'one built and then measured',
        summary='Every leak demonstrated on data with no signal in it, so the true '
                'answer is 0.50 and the optimism is exactly the size of the lie - '
                'from the harmless scaler-before-split to group leakage that turns '
                'pure noise into 94% accuracy.',
        category='validation', difficulty='beginner', icon='\U0001f4a7',
        references=[
            dict(title='Leakage in Data Mining: Formulation, Detection, and Avoidance',
                 authors='Kaufman, Rosset & Perlich, 2012 (ACM TKDD)'),
            dict(title='Leakage and the Reproducibility Crisis in ML-based Science',
                 authors='Kapoor & Narayanan, 2023 (Patterns)'),
        ],
    ),
    dict(
        notebook='how_models_work_hyperparameter_search.ipynb',
        title='Hyperparameter Search',
        tagline='Why random search beats grid search, and what Expected Improvement '
                'is actually computing',
        summary='Grid search written out cell by cell, the dimension-free '
                'random-search guarantee verified against simulation, Expected '
                'Improvement decomposed into exploitation and exploration, and '
                'successive halving costed out rung by rung.',
        category='validation', difficulty='intermediate', icon='\U0001f50e',
        references=[
            dict(title='Random Search for Hyper-Parameter Optimization',
                 authors='Bergstra & Bengio, 2012 (JMLR)'),
            dict(title='Practical Bayesian Optimization of Machine Learning Algorithms',
                 authors='Snoek, Larochelle & Adams, 2012 (NeurIPS)'),
            dict(title='Hyperband: A Novel Bandit-Based Approach to Hyperparameter '
                       'Optimization',
                 authors='Li et al., 2018 (JMLR)'),
        ],
    ),
    dict(
        notebook='how_models_work_calibration.ipynb',
        title='Probability Calibration',
        tagline='When the model says 0.70, does it happen 70% of the time? AUC '
                'cannot tell you',
        summary='Reliability diagrams and ECE computed bin by bin, proof that '
                'monotone transforms leave AUC untouched while destroying '
                'calibration, and both repairs - Platt scaling by hand and the PAVA '
                'algorithm for isotonic regression, step by step.',
        category='validation', difficulty='intermediate', icon='\U0001f3af',
        references=[
            dict(title='Predicting Good Probabilities With Supervised Learning',
                 authors='Niculescu-Mizil & Caruana, 2005 (ICML)'),
            dict(title='Probabilistic Outputs for Support Vector Machines and '
                       'Comparisons to Regularized Likelihood Methods',
                 authors='Platt, 1999'),
            dict(title='Transforming Classifier Scores into Accurate Multiclass '
                       'Probability Estimates',
                 authors='Zadrozny & Elkan, 2002 (KDD)'),
        ],
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
        category='instance', difficulty='beginner', icon='\U0001f3b2',
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
        category='trees', difficulty='beginner', icon='\U0001f333',
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
        category='trees', difficulty='beginner', icon='\U0001f332',
        references=[dict(
            title='Random Forests',
            authors='Breiman, 2001 (Machine Learning 45)',
            url='https://link.springer.com/article/10.1023/A:1010933404324',
        )],
    ),
    dict(
        notebook='how_models_work_adaboost.ipynb',
        title='AdaBoost',
        tagline='Boosting by reweighting the data, not by fitting gradients',
        summary='Three rounds with every sample weight, alpha and reweighting written out, the alpha formula verified as the exponential-loss minimiser, and the label-noise weakness demonstrated.',
        category='trees', difficulty='intermediate', icon='\U0001f4ca',
        references=[dict(
            title='A Decision-Theoretic Generalization of On-Line Learning and an Application to Boosting',
            authors='Freund & Schapire, 1997 (JCSS)',
            url='https://www.sciencedirect.com/science/article/pii/S002200009791504X',
        )],
    ),
    dict(
        notebook='how_models_work_gradient_boosting.ipynb',
        title='Gradient Boosting from Scratch',
        tagline='Fit the negative gradient - and why "fit the residual" is only the '
                'squared-error special case',
        summary='Three rounds built by hand and matched to scikit-learn exactly, the '
                'learning rate shown to trade against the number of rounds, the loss '
                'swapped to show where robustness comes from, and the second-order '
                'leaf value that turns this into XGBoost.',
        category='trees', difficulty='intermediate', icon='\U0001f4c9',
        references=[
            dict(title='Greedy Function Approximation: A Gradient Boosting Machine',
                 authors='Friedman, 2001 (Annals of Statistics)'),
            dict(title='Stochastic Gradient Boosting',
                 authors='Friedman, 2002 (Computational Statistics & Data Analysis)'),
        ],
    ),
    dict(
        notebook='how_models_work_stacking.ipynb',
        title='Stacking & Blending',
        tagline='Train a model to combine models - and why out-of-fold predictions '
                'are the whole method',
        summary='The third way to ensemble, after bagging and boosting. Out-of-fold '
                'meta-features built by hand and contrasted with the in-sample '
                'version that quietly hands all the weight to whichever model '
                'memorised best, plus what the meta-learner does that averaging '
                'cannot.',
        category='trees', difficulty='intermediate', icon='\U0001f9f1',
        references=[
            dict(title='Stacked Generalization', authors='Wolpert, 1992 (Neural Networks)'),
            dict(title='Stacked Regressions', authors='Breiman, 1996 (Machine Learning)'),
        ],
    ),
    dict(
        notebook='how_models_work_feature_importance.ipynb',
        title='Feature Importance & SHAP',
        tagline='Three methods, three different questions - and the default one is '
                'measurably biased',
        summary='Impurity importance shown ranking pure noise by cardinality, '
                'permutation importance and its blind spot with correlated features, '
                'and exact Shapley values enumerated over every coalition with the '
                'efficiency, dummy and symmetry axioms checked directly.',
        category='trees', difficulty='intermediate', icon='\U0001f50d',
        references=[
            dict(title='A Unified Approach to Interpreting Model Predictions',
                 authors='Lundberg & Lee, 2017 (NeurIPS)'),
            dict(title='A Value for n-Person Games', authors='Shapley, 1953'),
            dict(title='Conditional Variable Importance for Random Forests',
                 authors='Strobl et al., 2008 (BMC Bioinformatics)'),
        ],
    ),
    dict(
        notebook='how_models_work_xgboost.ipynb',
        title='XGBoost',
        tagline='Second-order Taylor expansion, similarity scores, and the closed-form gain',
        summary='Gradients and Hessians for all 12 rows, the leaf-weight derivation, every split '
                'gain ranked, the tree drawn with G/H/similarity/gain inside each node, and both '
                'trees matched leaf-for-leaf against the real xgboost.',
        category='trees', difficulty='advanced', icon='⚡',
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
        category='trees', difficulty='advanced', icon='\U0001f4a1',
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
        category='trees', difficulty='advanced', icon='\U0001f431',
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
        category='kernel', difficulty='advanced', icon='\U0001f6e1',
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
        category='kernel', difficulty='advanced', icon='\U0001f4cf',
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
        category='unsupervised', difficulty='beginner', icon='\U0001f3af',
        references=[dict(
            title='k-means++: The Advantages of Careful Seeding',
            authors='Arthur & Vassilvitskii, 2007 (SODA)',
            url='https://theory.stanford.edu/~sergei/papers/kMeansPP-soda.pdf',
        )],
    ),
    dict(
        notebook='how_models_work_gmm_em.ipynb',
        title='Gaussian Mixtures & EM',
        tagline='Soft assignment, real covariance, and k-means as the limiting case',
        summary='Responsibilities and the M-step computed by hand, the log-likelihood shown never to decrease, k-means recovered as sigma goes to zero, and every parameter matched against scikit-learn.',
        category='unsupervised', difficulty='advanced', icon='\U0001f52e',
        references=[dict(
            title='Maximum Likelihood from Incomplete Data via the EM Algorithm',
            authors='Dempster, Laird & Rubin, 1977 (JRSS-B)',
            url='https://www.jstor.org/stable/2984875',
        )],
    ),
    dict(
        notebook='how_models_work_pca.ipynb',
        title='Principal Component Analysis',
        tagline='Rotate the axes onto the directions of greatest variance',
        summary='The covariance matrix built entry by entry, eigenvectors verified against 20000 '
                'random directions, reconstruction error shown to equal the discarded '
                'eigenvalues, and the SVD route compared.',
        category='unsupervised', difficulty='intermediate', icon='\U0001f300',
        references=[dict(
            title='Principal Component Analysis',
            authors='Jolliffe, 2002 (2nd ed.)', url='',
        )],
    ),
    dict(
        notebook='how_models_work_autoencoder.ipynb',
        title='Autoencoders',
        tagline='Compress through a bottleneck - and a linear one is exactly PCA',
        summary='A linear autoencoder trained by gradient descent shown to recover the PCA subspace exactly (principal angles of zero), then the non-linear case following a curve PCA cannot.',
        category='unsupervised', difficulty='intermediate', icon='\U0001f5dc',
        references=[dict(
            title='Reducing the Dimensionality of Data with Neural Networks',
            authors='Hinton & Salakhutdinov, 2006 (Science)',
            url='https://www.science.org/doi/10.1126/science.1127647',
        )],
    ),
    dict(
        notebook='how_models_work_neural_network.ipynb',
        title='Neural Network & Backpropagation',
        tagline='The chain rule with its intermediate results kept - and gradient-checked',
        summary='Forward pass with every matrix printed, backpropagation derived and computed by '
                'hand, all 17 gradients verified against central differences, and a deliberately '
                'buggy version shown failing the same check.',
        category='deep', difficulty='intermediate', icon='\U0001f578',
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
        notebook='how_models_work_cnn.ipynb',
        title='Convolutional Networks',
        tagline='Slide a small set of weights everywhere - parameter sharing and its prior',
        summary='Convolution worked out position by position, kernels as feature detectors, stride/padding/pooling, translation equivariance demonstrated, and the backward pass gradient-checked and matched against PyTorch.',
        category='deep', difficulty='intermediate', icon='\U0001f5bc',
        references=[dict(
            title='Gradient-Based Learning Applied to Document Recognition',
            authors='LeCun, Bottou, Bengio & Haffner, 1998 (Proc. IEEE)',
            url='http://yann.lecun.com/exdb/publis/pdf/lecun-98.pdf',
        )],
    ),
    dict(
        notebook='how_models_work_rnn_lstm.ipynb',
        title='RNN & LSTM',
        tagline='Memory across time, why its gradient dies, and how gates rescue it',
        summary='The hidden state unrolled step by step, BPTT gradient-checked, vanishing gradients measured over 200 steps, every LSTM gate computed by hand, and both cells matched against PyTorch.',
        category='deep', difficulty='advanced', icon='\U0001f504',
        references=[dict(
            title='Long Short-Term Memory',
            authors='Hochreiter & Schmidhuber, 1997 (Neural Computation)',
            url='https://www.bioinf.jku.at/publications/older/2604.pdf',
        )],
    ),
    dict(
        notebook='how_models_work_tokenization.ipynb',
        title='Tokenization: Byte-Pair Encoding',
        tagline='How text becomes the integers every transformer page starts from',
        summary='BPE trained by hand, merge by merge, with the pair counts that drove '
                'each one - then applied to unseen words to show why there is no '
                'unknown token, and why counting letters, doing arithmetic and '
                'writing non-English text are all harder than they look.',
        category='transformers', difficulty='beginner', icon='\U0001f524',
        references=[
            dict(title='Neural Machine Translation of Rare Words with Subword Units',
                 authors='Sennrich, Haddow & Birch, 2016 (ACL)'),
            dict(title='A New Algorithm for Data Compression',
                 authors='Gage, 1994 (C Users Journal)'),
            dict(title='SentencePiece: A simple and language independent subword '
                       'tokenizer', authors='Kudo & Richardson, 2018 (EMNLP)'),
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
        category='transformers', difficulty='intermediate', icon='\U0001f9e0',
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
        category='transformers', difficulty='intermediate', icon='\U0001f9ee',
        references=[dict(
            title='Attention Is All You Need',
            authors='Vaswani et al., 2017 (NeurIPS)',
            url='https://arxiv.org/abs/1706.03762',
        )],
    ),
    dict(
        notebook='how_models_work_kimi_k3.ipynb',
        title='Kimi K3: Delta Attention, Attention Residuals, LatentMoE',
        tagline='A 2026 frontier architecture taken apart equation by equation - linear '
                'attention with a bounded forget gate, and a routed MoE that stays stable',
        summary='Every equation of the K3 report worked through on an 8-token sentence: the '
                'Kimi Delta Attention recurrence and its chunkwise form, the lower-bounded '
                'decay gate that replaced Kimi Linear’s unbounded one, gated MLA with NoPE, '
                'attention residuals across blocks, Stable LatentMoE, SiTU-GLU, and quantile '
                'load balancing - each checked against the equation it claims to implement.',
        category='transformers', difficulty='advanced', icon='\U0001f52c',
        references=[
            dict(title='Kimi K3: Open Frontier Intelligence',
                 authors='Kimi Team, Moonshot AI, 2026 (technical report)',
                 url='https://arxiv.org/abs/2607.24653'),
            # Cited by the report as the direct predecessors of KDA, gated MLA and
            # the routed-MoE design. Listed without URLs deliberately: the K3 report
            # is the only one of these I read here, so I am not vouching for an
            # arXiv id from memory on a public page.
            dict(title='Kimi Linear: An Expressive, Efficient Attention Architecture',
                 authors='Moonshot AI, 2025'),
            dict(title='Gated Delta Networks: Improving Mamba2 with Delta Rule',
                 authors='Yang et al., 2024'),
            dict(title='DeepSeek-V2: A Strong, Economical, and Efficient '
                       'Mixture-of-Experts Language Model (Multi-head Latent Attention)',
                 authors='DeepSeek-AI, 2024'),
        ],
    ),
    dict(
        notebook='how_models_work_deepseek_v4.ipynb',
        title='DeepSeek-V4: Compressed Sparse Attention and Muon',
        tagline='How a million-token context is made to fit - compression, sparse '
                'selection, and a residual stream that cannot amplify',
        summary='Every equation of the V4 report worked on an eight-token sentence: '
                'Compressed Sparse Attention and its lightning indexer, Heavily '
                'Compressed Attention, Manifold-Constrained Hyper-Connections projected '
                'onto the Birkhoff polytope by Sinkhorn-Knopp, and Muon with hybrid '
                'Newton-Schulz - each checked, and the paper’s KV-cache claim rebuilt '
                'from scratch.',
        category='transformers', difficulty='advanced', icon='\U0001f5dc',
        references=[
            dict(title='DeepSeek-V4: Towards Highly Efficient Million-Token Context '
                       'Intelligence',
                 authors='DeepSeek-AI, 2026 (technical report)',
                 url='https://arxiv.org/abs/2606.19348'),
            # Cited by the V4 report as the sources of the mechanisms above. Listed
            # without URLs on purpose: the V4 report is the one I read here, so I am
            # not vouching for arXiv ids from memory on a public page.
            dict(title='Hyper-Connections', authors='Zhu et al., 2025'),
            dict(title='Manifold-Constrained Hyper-Connections', authors='Xie et al., 2026'),
            dict(title='Muon: An optimizer for the hidden layers of neural networks',
                 authors='Jordan et al., 2024; Liu et al., 2025'),
            dict(title='DeepSeekMoE: Towards Ultimate Expert Specialization',
                 authors='Dai et al., 2024'),
            dict(title='Efficient Streaming Language Models with Attention Sinks',
                 authors='Xiao et al., 2024'),
        ],
    ),
    dict(
        notebook='how_models_work_rlhf_grpo.ipynb',
        title='RLHF, GRPO & Constitutional AI',
        tagline='What happens after pretraining - the stage that turns a text '
                'continuer into an assistant',
        summary='Reward models fitted from pairwise comparisons, the KL penalty shown '
                'stopping reward hacking as beta falls, GRPO advantages computed by '
                'hand for a group of eight, the clipped objective term by term, and '
                'the critique-revise loop of Constitutional AI.',
        category='transformers', difficulty='advanced', icon='\U0001f9ed',
        references=[
            dict(title='DeepSeekMath: Pushing the Limits of Mathematical Reasoning in '
                       'Open Language Models (introduces GRPO)',
                 authors='Shao et al., 2024'),
            dict(title='Constitutional AI: Harmlessness from AI Feedback',
                 authors='Bai et al., 2022',
                 url='https://arxiv.org/abs/2212.08073'),
            dict(title='Training language models to follow instructions with human '
                       'feedback', authors='Ouyang et al., 2022 (NeurIPS)'),
            dict(title='Proximal Policy Optimization Algorithms',
                 authors='Schulman et al., 2017'),
        ],
    ),
    dict(
        notebook='how_models_work_self_improving_llms.ipynb',
        title='Self-Improving LLMs',
        tagline='A model generating its own training data - and the four ways that '
                'loop quietly breaks',
        summary='Pass@k inversion computed exactly, so a "better" model provably '
                'solves fewer problems; entropy collapse starving the loop of the '
                'diversity it runs on; the arithmetic of why a self-judge gets hacked; '
                'and Gaussian model collapse matching its (1-1/n)^t prediction under '
                'replacement but not under accumulation.',
        category='transformers', difficulty='advanced', icon='\U0001f504',
        references=[
            dict(title='Self-Improvement of Large Language Models: A Technical '
                       'Overview and Future Outlook',
                 authors='Yang et al., 2026',
                 url='https://arxiv.org/abs/2603.25681'),
            dict(title='More Convincing, Not More Correct: Self-Play Reward Hacking '
                       'of Reference-Free LLM Judges',
                 authors='Zhou, 2026',
                 url='https://arxiv.org/abs/2607.05904'),
            dict(title='When RLVR Shrinks the Reasoning Boundary: Diagnosing Pass@k '
                       'Inversion',
                 authors='Zhou, 2026',
                 url='https://arxiv.org/abs/2607.20543'),
            dict(title='Curriculum Reinforcement Learning Can Incentivize Reasoning '
                       'Capacity in LLMs Beyond the Base Model',
                 authors='Cai et al., 2026',
                 url='https://arxiv.org/abs/2606.22317'),
            # Cited by the above and by the notebook text; listed without URLs
            # because I did not open these, only the four above.
            dict(title='STaR: Bootstrapping Reasoning With Reasoning',
                 authors='Zelikman et al., 2022'),
            dict(title='Large Language Models Cannot Self-Correct Reasoning Yet',
                 authors='Huang et al., 2023'),
            dict(title='The Curse of Recursion: Training on Generated Data Makes '
                       'Models Forget', authors='Shumailov et al., 2024 (Nature)'),
            dict(title='Is Model Collapse Inevitable? Breaking the Curse of Recursion '
                       'by Accumulating Real and Synthetic Data',
                 authors='Gerstgrasser et al., 2024'),
        ],
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
                # Metadata below lives in THIS file, not in the notebook, so it
                # must sync even when the content import was skipped -- otherwise
                # editing a category or tagline here would never reach the site.
                meta = dict(order=order, category=spec['category'],
                            difficulty=spec['difficulty'], icon=spec['icon'],
                            tagline=spec['tagline'], summary=spec['summary'])
                stale = [f for f, v in meta.items() if getattr(w, f) != v]
                if stale:
                    for f, v in meta.items():
                        setattr(w, f, v)
                    w.save(update_fields=list(meta))
                    self.stdout.write(f'   metadata updated ({", ".join(stale)})')
                for i, ref in enumerate(spec.get('references', []), start=1):
                    WalkthroughReference.objects.get_or_create(
                        walkthrough=w, title=ref['title'],
                        # url is optional: a reference may be worth listing even when
                    # I have no link I have actually verified.
                    defaults=dict(order=i, authors=ref['authors'], url=ref.get('url', '')),
                    )

        self.stdout.write(self.style.SUCCESS(
            f'walkthroughs: {done} imported/updated, {skipped} unchanged, {missing} missing'))
