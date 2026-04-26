from django.core.management.base import BaseCommand
from projects.models import Projects


CHALLENGE_1 = dict(
    title='NeurIPS 2025 EEG Foundation Challenge 1: Cross-Task RT Prediction',
    short_description='Self-supervised EEG Transformer pre-trained on passive tasks, fine-tuned to predict reaction time on unseen active task.',
    project_type='DEEP_LEARNING',
    data_type='TIME_SERIES',
    difficulty_level='EXPERT',
    model_type='REGRESSION',
    target_feature='Reaction Time (s)',
    evaluation_metric='NRMSE (Normalized RMSE)',
    is_featured=True,
    is_public=True,
    prediction_endpoint=True,
    has_api=True,
    prediction_input_type='file',
    file_input_config={
        'handler':           'eeg_rt_predictor',
        'model_bundle_path': 'D:/eegchallenge_results/finetuning_20260426_034840/weights_challenge_1.pt',
        'sample_data_path':  'D:/PersonalPortfolio/projects/inference/sample_eeg_ch1.npy',
        'accepted_formats':  ['npy', 'csv'],
        'description':       (
            'Upload a 129×200 NumPy (.npy) or CSV file representing a 2-second EEG window '
            '(129 channels, 100 Hz, z-scored). Or click "Try with sample EEG data" to see '
            'a live prediction on a real anonymised HBN-EEG window.'
        ),
    },
    skills_used='PYTHON, PYTORCH',
    libraries_used='PyTorch, MNE-Python, scikit-learn, NumPy, pandas',
    description=(
        'Challenge 1 of the NeurIPS 2025 EEG Foundation Model Challenge. '
        'The goal is cross-task transfer: pre-train a foundation model on passive EEG tasks '
        '(Resting State, Surround Suppression, movie clips) and fine-tune it to predict '
        'reaction time on the Contrast Change Detection (CCD) task — which was withheld '
        'during pre-training.\n\n'
        'Architecture: Transformer AutoEncoder with patch-channel cross-attention fusion, '
        'trained with VICReg + MAE reconstruction objective. Fine-tuning uses mean-pooled '
        'encoder representations passed through a regression head.'
    ),
    business_problem=(
        'Can a model trained on passive brain activity generalize to predict active cognitive performance? '
        'This tests whether EEG foundation models capture task-agnostic neural representations.'
    ),
    technical_approach=(
        'Pre-training: VICReg contrastive loss + masked patch reconstruction (MAE) on 6 passive tasks. '
        'Fine-tuning: freeze encoder, train regression head on stimulus-locked 2-second windows from CCD. '
        'Data: HBN-EEG dataset (3000+ participants, 100 Hz, 129 channels, BIDS format).'
    ),
    challenges=(
        'Cross-task generalization with no target-task signal during pre-training. '
        'High inter-subject variability in EEG. '
        'Variable-length recordings requiring windowing strategy.'
    ),
    key_achievements=(
        'Implemented full self-supervised pre-training pipeline with VICReg + MAE. '
        'Task availability filtering from participants.tsv to avoid wasted I/O. '
        'Argparse-based CLI for easy hyperparameter sweeps.'
    ),
    dataset_url='https://fcon_1000.projects.nitrc.org/indi/cmi_healthy_brain_network/',
)

CHALLENGE_2 = dict(
    title='NeurIPS 2025 EEG Foundation Challenge 2: Psychopathology Prediction',
    short_description='Predicting continuous externalizing psychopathology scores from resting and naturalistic EEG using a pre-trained Transformer.',
    project_type='DEEP_LEARNING',
    data_type='TIME_SERIES',
    difficulty_level='EXPERT',
    model_type='REGRESSION',
    target_feature='Externalizing Factor Score',
    evaluation_metric='NRMSE (Normalized RMSE)',
    is_featured=True,
    is_public=True,
    prediction_endpoint=True,
    has_api=True,
    prediction_input_type='file',
    file_input_config={
        'handler':           'eeg_externalizing_predictor',
        'model_bundle_path': 'D:/eegchallenge_results/challenge2_externalizing_unfrozen_20260426_094813/weights_challenge_2.pt',
        'sample_data_path':  'D:/PersonalPortfolio/projects/inference/sample_eeg_ch2.npy',
        'accepted_formats':  ['npy', 'csv'],
        'description':       (
            'Upload a 129×200 NumPy (.npy) or CSV file representing a 2-second EEG window '
            '(129 channels, 100 Hz, z-scored). Or click "Try with sample EEG data" — no file needed.'
        ),
    },
    skills_used='PYTHON, PYTORCH',
    libraries_used='PyTorch, MNE-Python, scikit-learn, NumPy, pandas',
    description=(
        'Challenge 2 of the NeurIPS 2025 EEG Foundation Model Challenge. '
        'A supervised regression task: predict the continuous externalizing psychopathology score '
        '(from the HBN assessment battery) for each participant using their EEG recordings across '
        'all available tasks.\n\n'
        'Architecture: Same Transformer AE backbone as Challenge 1. Random 2-second windows are '
        'sampled across all tasks per subject, producing a distribution of predictions that are '
        'aggregated at evaluation. Task availability is filtered per-subject from participants.tsv.'
    ),
    business_problem=(
        'Can EEG biomarkers reliably predict dimensional psychopathology in children and adolescents? '
        'Externalizing behaviour (ADHD, conduct disorder) leaves measurable neural signatures '
        'that a foundation model may capture across diverse cognitive contexts.'
    ),
    technical_approach=(
        'Load pre-trained backbone from Challenge 1 pre-training. '
        'Sample n random windows per subject across all available task recordings. '
        'Split train/val by subject (not by window) to prevent data leakage. '
        'Regression head on mean-pooled encoder output, trained with MSE loss, '
        'evaluated with NRMSE.'
    ),
    challenges=(
        'Subject-level label with window-level input: many windows share one label, '
        'requiring careful subject-stratified splitting. '
        'Missing data: not all subjects completed all tasks — handled via participants.tsv flags.'
    ),
    key_achievements=(
        'Subject-stratified dataset split preventing any data leakage. '
        'Per-subject task availability filtering using participants.tsv flag columns. '
        'Shared backbone with Challenge 1 enables transfer of pre-trained representations.'
    ),
    dataset_url='https://fcon_1000.projects.nitrc.org/indi/cmi_healthy_brain_network/',
)


class Command(BaseCommand):
    help = 'Create the two NeurIPS 2025 EEG Foundation Challenge project entries'

    def handle(self, *args, **options):
        for data in (CHALLENGE_1, CHALLENGE_2):
            obj, created = Projects.objects.get_or_create(
                title=data['title'],
                defaults=data,
            )
            if not created:
                # Update fields that may have changed (prediction config, etc.)
                for field, value in data.items():
                    setattr(obj, field, value)
                obj.save()
            status = 'Created' if created else 'Updated'
            self.stdout.write(f'{status}: {obj.title}')

        self.stdout.write(self.style.SUCCESS('Done.'))
