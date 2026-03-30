from django.db import models
import os
import json


class Projects(models.Model):
    """
    Project model for HasanPortfolio - Data Science Portfolio
    """

    # Project type choices
    PROJECT_TYPE_CHOICES = [
        ('KAGGLE_COMPETITION', '🏆 Kaggle Competition'),
        ('PERSONAL_PROJECT', '🤖 Personal ML Project'),
        ('DATA_ANALYSIS', '📈 Data Analysis'),
        ('DATA_VISUALIZATION', '🎨 Data Visualization'),
        ('DEEP_LEARNING', '🧠 Deep Learning'),
        ('NLP_PROJECT', '💬 NLP Project'),
        ('TIME_SERIES', '⏰ Time Series Analysis'),
        ('ACADEMIC', '🎓 Academic Project'),
        ('WORK', '💼 Work Project'),
    ]

    # Data type choices
    DATA_TYPE_CHOICES = [
        ('TABULAR', 'Tabular Data'),
        ('IMAGE', 'Image Data'),
        ('TEXT', 'Text Data'),
        ('TIME_SERIES', 'Time Series Data'),
        ('AUDIO', 'Audio Data'),
        ('VIDEO', 'Video Data'),
        ('MULTIMODAL', 'Multimodal Data'),
    ]

    # Skill choices
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

    # Difficulty level
    DIFFICULTY_LEVEL_CHOICES = [
        ('BEGINNER', '⭐ Beginner'),
        ('INTERMEDIATE', '⭐⭐ Intermediate'),
        ('ADVANCED', '⭐⭐⭐ Advanced'),
        ('EXPERT', '⭐⭐⭐⭐ Expert'),
    ]

    # Model type choices
    MODEL_TYPE_CHOICES = [
        ('CLASSIFICATION', 'Classification'),
        ('REGRESSION', 'Regression'),
        ('CLUSTERING', 'Clustering'),
        ('NLP', 'Natural Language Processing'),
        ('COMPUTER_VISION', 'Computer Vision'),
    ]

    # Basic Information
    title = models.CharField(
        max_length=100,
        help_text="Project title (e.g., 'House Price Prediction')", default=None
    )
    short_description = models.CharField(
        max_length=200,
        blank=True,
        help_text="Brief one-line description"
    )
    project_type = models.CharField(
        max_length=20,
        choices=PROJECT_TYPE_CHOICES,
        help_text="Type of project", default='NONE'
    )
    difficulty_level = models.CharField(
        max_length=15,
        choices=DIFFICULTY_LEVEL_CHOICES,
        default='INTERMEDIATE',
        help_text="Project difficulty level"
    )

    # ML Model Fields
    trained_model = models.FileField(
        upload_to='projects/models/',
        blank=True,
        null=True,
        help_text="Trained model file (pickle, h5, joblib)"
    )

    model_type = models.CharField(
        max_length=50,
        choices=MODEL_TYPE_CHOICES,
        blank=True,
        help_text="Type of machine learning model"
    )

    input_features = models.JSONField(
        default=list,
        blank=True,
        help_text="List of input features for the model"
    )

    target_feature = models.CharField(
        max_length=100,
        blank=True,
        help_text="Target variable name"
    )

    prediction_endpoint = models.BooleanField(
        default=False,
        help_text="Enable prediction page for this project"
    )

    # Project Details
    description = models.TextField(
        help_text="Detailed project description and overview", default='None'
    )
    business_problem = models.TextField(
        blank=True,
        help_text="What business/problem does this solve?"
    )
    technical_approach = models.TextField(
        blank=True,
        help_text="Technical methodology and approach"
    )
    challenges = models.TextField(
        blank=True,
        help_text="Technical challenges faced and solutions"
    )
    key_achievements = models.TextField(
        blank=True,
        help_text="Key results and achievements"
    )
    lessons_learned = models.TextField(
        blank=True,
        help_text="What did you learn from this project?"
    )

    # Technical Specifications
    data_type = models.CharField(
        max_length=15,
        choices=DATA_TYPE_CHOICES,
        help_text="Type of data used in project"
    )

    skills_used = models.TextField(
        blank=True,
        help_text="Enter skills as comma-separated values from the predefined list"
    )

    def clean(self):
        """Validate skills_used field"""
        super().clean()
        if self.skills_used:
            skills_list = [skill.strip() for skill in self.skills_used.split(',')]
            valid_skills = [choice[0] for choice in self.SKILL_CHOICES]

            for skill in skills_list:
                if skill and skill not in valid_skills:
                    raise ValidationError(
                        f"Invalid skill: '{skill}'. Valid skills are: {', '.join(valid_skills)}"
                    )

    def get_skills_list(self):
        """Get skills as a list"""
        if self.skills_used:
            return [skill.strip() for skill in self.skills_used.split(',') if skill.strip()]
        return []

    def set_skills(self, skills_list):
        """Set skills from a list"""
        self.skills_used = ', '.join(skills_list)

    def get_skills_display(self):
        """Return human-readable skill names"""
        skill_dict = dict(self.SKILL_CHOICES)
        skills_list = self.get_skills_list()
        return [skill_dict.get(skill, skill) for skill in skills_list]

    libraries_used = models.TextField(
        blank=True,
        help_text="Specific libraries and tools used"
    )

    # Performance Metrics
    accuracy_score = models.FloatField(
        null=True,
        blank=True,
        help_text="Best accuracy or main metric score"
    )
    kaggle_rank = models.IntegerField(
        null=True,
        blank=True,
        help_text="Kaggle competition rank (if applicable)"
    )
    total_competitors = models.IntegerField(
        null=True,
        blank=True,
        help_text="Total competitors in Kaggle competition"
    )
    evaluation_metric = models.CharField(
        max_length=100,
        blank=True,
        help_text="Evaluation metric used (e.g., RMSE, Accuracy, F1-Score)"
    )

    # Media & Links
    featured_image = models.ImageField(
        upload_to='projects/images/',
        blank=True,
        null=True,
        help_text="Main project thumbnail image"
    )
    additional_images = models.JSONField(
        default=list,
        blank=True,
        help_text="List of additional image paths"
    )
    github_url = models.URLField(
        blank=True,
        help_text="GitHub repository URL"
    )
    kaggle_url = models.URLField(
        blank=True,
        help_text="Kaggle notebook/competition URL"
    )
    live_demo_url = models.URLField(
        blank=True,
        help_text="Live demo URL (if available)"
    )
    dataset_url = models.URLField(
        blank=True,
        help_text="Dataset source URL"
    )

    # Project Management
    is_featured = models.BooleanField(
        default=False,
        help_text="Feature this project on homepage"
    )
    is_public = models.BooleanField(
        default=True,
        help_text="Show this project publicly"
    )
    start_date = models.DateField(
        null=True,
        blank=True,
        help_text="Project start date"
    )
    end_date = models.DateField(
        null=True,
        blank=True,
        help_text="Project end date"
    )
    time_spent = models.CharField(
        max_length=50,
        blank=True,
        help_text="Estimated time spent (e.g., '2 weeks', '3 months')"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    def get_skills_display(self):
        """Return human-readable skill names"""
        skill_dict = dict(self.SKILL_CHOICES)
        return [skill_dict.get(skill, skill) for skill in self.skills_used]

    def get_kaggle_percentile(self):
        """Calculate Kaggle percentile if rank and total competitors are available"""
        if self.kaggle_rank and self.total_competitors:
            percentile = (self.kaggle_rank / self.total_competitors) * 100
            return round(percentile, 2)
        return None

    def is_kaggle_competition(self):
        """Check if this is a Kaggle competition project"""
        return self.project_type == 'KAGGLE_COMPETITION'

    def has_prediction_capability(self):
        """Check if this project has prediction capability"""
        return bool(self.trained_model and self.prediction_endpoint and self.is_public)

    def get_model_path(self):
        """Get model file path"""
        if self.trained_model:
            return self.trained_model.path
        return None

    class Meta:
        verbose_name = "Project"
        verbose_name_plural = "Projects"
        ordering = ['-is_featured', '-start_date', '-created_at']
        indexes = [
            models.Index(fields=['project_type', 'is_public']),
            models.Index(fields=['is_featured', 'is_public']),
        ]