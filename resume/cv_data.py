"""Resume content, taken from the owner's CV (MirHosseini_CV_DataScience.pdf, Nov 2026).

Keep this honest: only what the CV states. Cloud/DevOps tools are familiarity
(this site was hosted on Azure while learning), not work experience.

apply(models) rewrites the resume tables from this data; models is a dict of
model classes (real models, or apps.get_model(...) in a data migration).
"""
import datetime

D = datetime.date

SETTINGS = {
    'full_name': 'Seyedhasan Mirhosseini',
    'job_title': 'Data Scientist',
    'email': 'seyedhasan.mirhoseini1367@gmail.com',
    'location': 'Finland',
    'website': 'https://hasanai.net',
    'professional_summary': (
        'Data Scientist with an MSc in Statistical Data Analytics and a BSc in Mathematics, with hands-on '
        'experience building machine learning models and retrieval-augmented generation (RAG) systems. '
        'Sole architect and developer of HealthCompass, a deployed RAG assistant built with Python and Django.'
    ),
}

EDUCATION = [
    dict(institution='Tampere University', degree='MASTER', field_of_study='Statistical Data Analytics',
         start_date=D(2023, 9, 1), end_date=D(2025, 6, 30), location='Finland', display_order=1,
         description='Thesis: seizure detection from EEG, comparing an LSTM–Transformer, a CNN–Transformer over '
                     'STFT spectrograms and a fusion model (Python, PyTorch).'),
    dict(institution='University of Tehran', degree='MASTER', field_of_study='Business Administration (MBA)',
         start_date=D(2013, 9, 1), end_date=D(2016, 6, 30), location='Iran', display_order=2, description=''),
    dict(institution='Damghan University', degree='BACHELOR', field_of_study='Mathematics',
         start_date=D(2008, 9, 1), end_date=D(2013, 6, 30), location='Iran', display_order=3, description=''),
]

EXPERIENCE = [
    dict(company='University of Eastern Finland', position='Foundation Model Researcher',
         employment_type='INTERNSHIP', start_date=D(2025, 8, 1), end_date=D(2025, 10, 31), location='Finland',
         display_order=1, description='',
         achievements=[
             'Designed and pretrained a Transformer foundation model on EEG recordings using self-supervised '
             'learning (VICReg, masked signal reconstruction).',
             'Fine-tuned it for downstream classification and regression tasks. Python, PyTorch.',
         ]),
    dict(company='Tampere University', position='Research Assistant (Trainee)', employment_type='INTERNSHIP',
         start_date=D(2024, 1, 1), end_date=D(2025, 1, 31), location='Tampere, Finland', display_order=2,
         description='',
         achievements=[
             'Conducted statistical analyses across experimental and control groups using Python and R to '
             'evaluate the impact of gamification on learning outcomes.',
             'Co-authored 4 peer-reviewed publications.',
         ]),
]

PROJECTS = [
    dict(title='HealthCompass — AI-Powered Personal Health Platform',
         description='Independent project. Designed and built a full-stack Django health platform featuring a '
                     'hybrid RAG pipeline for natural-language medical record querying.',
         technologies_used=['Python', 'Django', 'PyTorch', 'RAG', 'HTML/CSS'],
         start_date=D(2026, 1, 1), is_current=True, display_order=1),
    dict(title='CasvuAI — Multi-Agent LLM Content Pipeline',
         description='Orchestrated 6+ specialised agents in an autonomous multi-agent workflow for '
                     'multilingual content generation.',
         technologies_used=['Python', 'Django', 'LangChain'],
         start_date=D(2024, 9, 1), end_date=D(2024, 9, 30), display_order=2),
    dict(title="Master's Thesis — Seizure Detection",
         description='End-to-end pipeline comparing an LSTM–Transformer over temporal EEG, a CNN–Transformer '
                     'over STFT spectrograms, and a fusion model integrating both representations.',
         technologies_used=['Python', 'PyTorch', 'Transformers', 'CNN', 'LSTM'],
         start_date=D(2024, 9, 1), end_date=D(2025, 6, 30), display_order=3),
    dict(title='hasanai.net — this portfolio',
         description='Django site with live ML model demos, a RAG assistant, a multi-agent content generator, '
                     'an automated AI news digest and ML walkthroughs. First hosted on Azure App Service while '
                     'learning, now on Render with GitHub Actions.',
         technologies_used=['Python', 'Django', 'LangChain', 'RAG', 'Docker', 'GitHub Actions'],
         project_url='https://hasanai.net', start_date=D(2025, 9, 1), is_current=True, display_order=4),
]

# (category, [names]) in the CV's table order; proficiency 1-5.
SKILLS = [
    ('PROGRAMMING', [('Python (primary)', 5), ('R', 4), ('SQL', 3)]),
    ('ML_FRAMEWORKS', [('Supervised & unsupervised learning', 5), ('LightGBM', 4), ('XGBoost', 4), ('CatBoost', 4),
                       ('Ensemble learning', 4), ('Support Vector Machines (SVM)', 4), ('k-Nearest Neighbors (k-NN)', 4),
                       ('Naïve Bayes', 4), ('Clustering (K-means, DBSCAN)', 4),
                       ('Dimensionality reduction (PCA, t-SNE)', 4)]),
    ('DEEP_LEARNING', [('Transformers', 4), ('CNNs', 4), ('LSTMs/GRUs', 4), ('Autoencoders', 4),
                       ('Self-supervised learning', 4), ('Foundation models', 3)]),
    ('TOOLS', [('RAG', 4), ('LangChain', 4), ('LangGraph', 3), ('Multi-agent systems', 3)]),
    ('CLOUD', [('Git', 4), ('GitHub Actions (CI/CD)', 3), ('Docker', 3), ('Azure (familiarity)', 2)]),
    ('DATA_VISUALIZATION', [('Matplotlib', 4), ('Seaborn', 4), ('Interactive data dashboards', 3)]),
    ('DATA_ANALYSIS', [('Exploratory data analysis (EDA)', 5), ('Feature engineering', 4), ('Signal processing', 4),
                       ('Predictive modeling', 4), ('Cross-validation', 4), ('Model selection', 4),
                       ('Imbalanced learning', 4)]),
    ('STATISTICS', [('Hypothesis testing', 5),
                    ('Regression (linear, logistic, ridge, lasso, elastic net)', 5)]),
    ('TECHNOLOGIES', [('PyTorch', 5), ('scikit-learn', 5), ('Optuna', 4), ('Pandas', 5), ('NumPy', 5), ('SciPy', 4),
                      ('MNE-Python', 4)]),
]

LANGUAGES = [
    dict(language='ENGLISH', proficiency='PROFESSIONAL', display_order=1),
    dict(language='PERSIAN', proficiency='NATIVE', display_order=2),
    dict(language='FINNISH', proficiency='BEGINNER', display_order=3),
]


def apply(models):
    """Rewrite the resume from the CV. Soft skills and certifications are left as they are."""
    Settings = models['ResumeSetting']
    resume = Settings.objects.order_by('pk').first() or Settings.objects.create()
    for field, value in SETTINGS.items():
        setattr(resume, field, value)
    resume.save()

    for name in ('Education', 'Experience', 'ProjectHighlight', 'Language'):
        models[name].objects.all().delete()
    models['Skill'].objects.exclude(category='SOFT_SKILLS').delete()

    for row in EDUCATION:
        models['Education'].objects.create(resume=resume, **row)
    for row in EXPERIENCE:
        models['Experience'].objects.create(resume=resume, **row)
    for row in PROJECTS:
        models['ProjectHighlight'].objects.create(resume=resume, **row)
    for row in LANGUAGES:
        models['Language'].objects.create(resume=resume, **row)
    order = 0
    for category, items in SKILLS:
        for i, (name, level) in enumerate(items):
            order += 1
            models['Skill'].objects.create(resume=resume, name=name, category=category, proficiency=level,
                                           display_order=i + 1, is_featured=i < 3)
    return resume
