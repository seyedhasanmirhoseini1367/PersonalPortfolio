# projects/models.py
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
import os


class Projects(models.Model):
    # ── Choice constants ──────────────────────────────────────────────────────

    PROJECT_TYPE_CHOICES = [
        ('KAGGLE_COMPETITION', 'Kaggle Competition'),
        ('PERSONAL_PROJECT', 'Personal ML Project'),
        ('DATA_ANALYSIS', 'Data Analysis'),
        ('DATA_VISUALIZATION', 'Data Visualization'),
        ('DEEP_LEARNING', 'Deep Learning'),
        ('NLP_PROJECT', 'NLP Project'),
        ('TIME_SERIES', 'Time Series Analysis'),
        ('ACADEMIC', 'Academic Project'),
        ('WORK', 'Work Project'),
    ]

    DATA_TYPE_CHOICES = [
        ('TABULAR', 'Tabular Data'),
        ('IMAGE', 'Image Data'),
        ('TEXT', 'Text Data'),
        ('TIME_SERIES', 'Time Series Data'),
        ('AUDIO', 'Audio Data'),
        ('VIDEO', 'Video Data'),
        ('MULTIMODAL', 'Multimodal Data'),
    ]

    SKILL_CHOICES = [
        ('PYTHON', 'Python'),
        ('R', 'R Programming'),
        ('SQL', 'SQL & Databases'),
        ('PANDAS', 'Pandas'),
        ('NUMPY', 'NumPy'),
        ('SKLEARN', 'Scikit-learn'),
        ('TENSORFLOW', 'TensorFlow'),
        ('PYTORCH', 'PyTorch'),
        ('KERAS', 'Keras'),
        ('XGBOOST', 'XGBoost'),
        ('LIGHTGBM', 'LightGBM'),
        ('MATPLOTLIB', 'Matplotlib'),
        ('SEABORN', 'Seaborn'),
        ('PLOTLY', 'Plotly'),
        ('OPENCV', 'OpenCV'),
        ('NLTK', 'NLTK'),
        ('SPACY', 'spaCy'),
        ('HUGGINGFACE', 'Hugging Face'),
        ('DOCKER', 'Docker'),
        ('AWS', 'AWS'),
        ('GCP', 'Google Cloud'),
        ('AZURE', 'Microsoft Azure'),
    ]

    DIFFICULTY_LEVEL_CHOICES = [
        ('BEGINNER', 'Beginner'),
        ('INTERMEDIATE', 'Intermediate'),
        ('ADVANCED', 'Advanced'),
        ('EXPERT', 'Expert'),
    ]

    MODEL_TYPE_CHOICES = [
        ('CLASSIFICATION', 'Classification'),
        ('REGRESSION', 'Regression'),
        ('CLUSTERING', 'Clustering'),
        ('NLP', 'Natural Language Processing'),
        ('COMPUTER_VISION', 'Computer Vision'),
    ]

    PREDICTION_INPUT_CHOICES = [
        ('manual', 'Manual — form fields'),
        ('file', 'File upload'),
    ]

    # ── Basic Information ─────────────────────────────────────────────────────

    title = models.CharField(
        max_length=100,
        help_text="Project title (e.g., 'EEG Seizure Detection')",
    )
    short_description = models.CharField(
        max_length=200,
        blank=True,
        help_text="One-line summary shown on cards and the demo page",
    )
    project_type = models.CharField(
        max_length=20,
        choices=PROJECT_TYPE_CHOICES,
        blank=True,
        help_text="Type of project",
    )
    difficulty_level = models.CharField(
        max_length=15,
        choices=DIFFICULTY_LEVEL_CHOICES,
        default='INTERMEDIATE',
        help_text="Project difficulty level",
    )

    # ── ML Model ──────────────────────────────────────────────────────────────

    trained_model = models.FileField(
        upload_to='projects/models/',
        blank=True,
        null=True,
        help_text="Trained model file (.pkl, .joblib, .h5, .pt)",
    )
    model_type = models.CharField(
        max_length=50,
        choices=MODEL_TYPE_CHOICES,
        blank=True,
        help_text="Type of machine learning model",
    )
    target_feature = models.CharField(
        max_length=100,
        blank=True,
        help_text="Target variable name shown on the demo page (e.g., 'seizure')",
    )
    prediction_endpoint = models.BooleanField(
        default=False,
        help_text="Enable the prediction demo page for this project",
    )

    # ── Prediction input mode ─────────────────────────────────────────────────

    prediction_input_type = models.CharField(
        max_length=10,
        choices=PREDICTION_INPUT_CHOICES,
        default='file',
        help_text="How the user provides data: upload a file OR fill in form fields",
    )

    file_input_config = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            'Config for file-upload demo. Must include "handler" slug. '
            'See projects/inference/ADMIN_CONFIGS.md for ready-to-paste examples.'
        ),
    )

    input_features = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            'List of input fields for manual mode. '
            'Example: [{"name": "age", "type": "number", "description": "Patient age"}]'
        ),
    )

    # ── Project Details ───────────────────────────────────────────────────────

    description = models.TextField(
        blank=True,
        default='',
        help_text="Full project description and overview",
    )
    business_problem = models.TextField(
        blank=True,
        help_text="What business or research problem does this solve?",
    )
    technical_approach = models.TextField(
        blank=True,
        help_text="Technical methodology and approach",
    )
    challenges = models.TextField(
        blank=True,
        help_text="Technical challenges faced and how they were solved",
    )
    key_achievements = models.TextField(
        blank=True,
        help_text="Key results and achievements",
    )
    lessons_learned = models.TextField(
        blank=True,
        help_text="What did you learn from this project?",
    )

    # ── Technical Specifications ──────────────────────────────────────────────

    data_type = models.CharField(
        max_length=15,
        choices=DATA_TYPE_CHOICES,
        blank=True,
        help_text="Type of data used in the project",
    )
    skills_used = models.TextField(
        blank=True,
        help_text="Comma-separated skill keys, e.g.: PYTHON, PYTORCH, SKLEARN",
    )
    libraries_used = models.TextField(
        blank=True,
        help_text="Specific libraries and tools used",
    )

    # ── Performance Metrics ───────────────────────────────────────────────────

    accuracy_score = models.FloatField(
        null=True, blank=True,
        help_text="Best accuracy or primary metric score (0–1 or 0–100)",
    )
    evaluation_metric = models.CharField(
        max_length=100,
        blank=True,
        help_text="Metric name, e.g.: F1-Score, RMSE, AUC-ROC",
    )
    kaggle_rank = models.IntegerField(
        null=True, blank=True,
        help_text="Kaggle competition final rank",
    )
    total_competitors = models.IntegerField(
        null=True, blank=True,
        help_text="Total number of competitors (for percentile calculation)",
    )

    # ── Media & Links ─────────────────────────────────────────────────────────

    featured_image = models.ImageField(
        upload_to='projects/images/',
        blank=True, null=True,
        help_text="Thumbnail image shown on project cards",
    )
    additional_images = models.JSONField(
        default=list, blank=True,
        help_text="List of additional image paths",
    )
    github_url = models.URLField(blank=True, help_text="GitHub repository URL")
    kaggle_url = models.URLField(blank=True, help_text="Kaggle notebook/competition URL")
    live_demo_url = models.URLField(blank=True, help_text="Live demo URL (if deployed separately)")
    dataset_url = models.URLField(blank=True, help_text="Dataset source URL")

    # ── RAG Document Upload for AI Context ─────────────────────────────────────

    rag_document = models.FileField(
        upload_to='projects/rag_documents/',
        blank=True,
        null=True,
        help_text=(
            "Upload a PDF, Word, Text, or Markdown file containing detailed project documentation. "
            "This file will be used by the RAG system to provide richer AI interpretations. "
            "Supported formats: .pdf, .docx, .txt, .md"
        )
    )

    rag_document_uploaded_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Timestamp when the RAG document was last uploaded",
    )

    rag_document_processed = models.BooleanField(
        default=False,
        help_text="Whether the document has been processed by the RAG system",
    )

    # ── MLOps / Deployment Info ───────────────────────────────────────────────

    is_dockerized = models.BooleanField(
        default=False,
        help_text='Check if this project has a Dockerfile / is containerised',
    )
    has_api = models.BooleanField(
        default=False,
        help_text='Check if this project exposes a REST API endpoint',
    )
    avg_inference_ms = models.IntegerField(
        null=True, blank=True,
        help_text='Average inference latency in milliseconds (shown on card)',
    )
    ci_cd_badge_url = models.URLField(
        blank=True,
        help_text='GitHub Actions badge image URL (e.g. https://github.com/user/repo/actions/workflows/ci.yml/badge.svg)',
    )

    # ── Project Management ────────────────────────────────────────────────────

    is_featured = models.BooleanField(
        default=False, help_text="Pin this project to the homepage featured section",
    )
    is_public = models.BooleanField(
        default=True, help_text="Show this project to visitors",
    )
    start_date = models.DateField(null=True, blank=True, help_text="Project start date")
    end_date = models.DateField(null=True, blank=True, help_text="Project end date (leave blank if ongoing)")
    time_spent = models.CharField(
        max_length=50, blank=True,
        help_text="Estimated time spent, e.g.: '3 months', '2 weeks'",
    )

    # ── Timestamps ────────────────────────────────────────────────────────────

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ── String / display ─────────────────────────────────────────────────────

    def __str__(self):
        return self.title

    # ── Skills helpers ────────────────────────────────────────────────────────

    def get_skills_list(self):
        """Return skills as a clean Python list."""
        if self.skills_used:
            return [s.strip() for s in self.skills_used.split(',') if s.strip()]
        return []

    def get_skills_display(self):
        """Return human-readable skill names."""
        skill_dict = dict(self.SKILL_CHOICES)
        return [skill_dict.get(s, s) for s in self.get_skills_list()]

    def set_skills(self, skills_list):
        self.skills_used = ', '.join(skills_list)

    # ── Validation ────────────────────────────────────────────────────────────

    def clean(self):
        super().clean()
        if self.skills_used:
            valid = {c[0] for c in self.SKILL_CHOICES}
            for skill in self.get_skills_list():
                if skill not in valid:
                    raise ValidationError(
                        f"Invalid skill: '{skill}'. "
                        f"Valid keys: {', '.join(sorted(valid))}"
                    )

    # ── Prediction helpers ────────────────────────────────────────────────────

    def has_prediction_capability(self):
        """True only when a model file is uploaded, demo is enabled, and project is public."""
        return bool(self.trained_model and self.prediction_endpoint and self.is_public)

    def get_model_path(self):
        """Absolute path to the uploaded model file, or None."""
        if self.trained_model:
            return self.trained_model.path
        return None

    # ── Kaggle helpers ────────────────────────────────────────────────────────

    def get_kaggle_percentile(self):
        if self.kaggle_rank and self.total_competitors:
            return round((self.kaggle_rank / self.total_competitors) * 100, 2)
        return None

    def is_kaggle_competition(self):
        return self.project_type == 'KAGGLE_COMPETITION'

    # ── RAG Document Helpers ──────────────────────────────────────────────────

    def save(self, *args, **kwargs):
        """Override save to handle document processing"""
        is_new_document = False

        if self.pk:
            try:
                old = Projects.objects.get(pk=self.pk)
                if old.rag_document != self.rag_document:
                    is_new_document = True
                    self.rag_document_uploaded_at = timezone.now()
                    self.rag_document_processed = False
            except Projects.DoesNotExist:
                pass
        else:
            if self.rag_document:
                is_new_document = True
                self.rag_document_uploaded_at = timezone.now()
                self.rag_document_processed = False

        super().save(*args, **kwargs)

        if is_new_document and self.rag_document:
            self.process_rag_document()

    def process_rag_document(self):
        """Process the uploaded document through RAG system"""
        try:
            from rag_system.services.document_processor import DocumentProcessor
            from rag_system.models import Document

            processor = DocumentProcessor()

            rag_doc = processor.process_document(
                file_path=self.rag_document.path,
                document_type='project_documentation',
                title=f"{self.title} - Project Documentation"
            )

            # Link document to this project
            if hasattr(rag_doc, 'project'):
                rag_doc.project = self
                rag_doc.save()

            self.rag_document_processed = True
            self.save(update_fields=['rag_document_processed'])
            return True

        except Exception as e:
            print(f"Error processing RAG document: {e}")
            self.rag_document_processed = False
            self.save(update_fields=['rag_document_processed'])
            return False

    def get_rag_document_context(self, max_chunks=5):
        """Retrieve document chunks for RAG context"""
        try:
            from rag_system.models import Document

            doc = Document.objects.filter(
                title__icontains=self.title,
                document_type='project_documentation'
            ).order_by('-created_at').first()

            if doc:
                chunks = doc.chunks.all()[:max_chunks]
                context = "\n\n".join([chunk.content for chunk in chunks])
                return context
        except Exception as e:
            print(f"Error getting RAG context: {e}")

        return ""

    # ── Meta ──────────────────────────────────────────────────────────────────

    class Meta:
        verbose_name = "Project"
        verbose_name_plural = "Projects"
        ordering = ['-is_featured', '-start_date', '-created_at']
        indexes = [
            models.Index(fields=['project_type', 'is_public']),
            models.Index(fields=['is_featured', 'is_public']),
        ]


class ProjectComment(models.Model):
    """A comment left by a user on a project page."""

    project = models.ForeignKey(
        Projects,
        on_delete=models.CASCADE,
        related_name='comments',
        verbose_name='Project',
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='project_comments',
        verbose_name='Author',
    )
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='replies',
        verbose_name='Parent Comment',
    )
    content = models.TextField(
        verbose_name='Comment',
        help_text='Write your comment here (min 5 characters)',
    )
    is_approved = models.BooleanField(
        default=True,
        verbose_name='Approved',
        help_text='Unapprove to hide this comment from visitors',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Project Comment'
        verbose_name_plural = 'Project Comments'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['project', 'created_at']),
            models.Index(fields=['is_approved']),
        ]

    def __str__(self):
        return f'{self.author.username} on "{self.project.title}" ({self.created_at:%Y-%m-%d})'

    def is_reply(self):
        return self.parent_id is not None