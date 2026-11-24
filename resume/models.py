from django.db import models
from .storage import cv_storage
from django.core.validators import MinValueValidator, MaxValueValidator


class ResumeSetting(models.Model):
    """
    Global resume settings and personal information
    """
    full_name = models.CharField(max_length=100, default="Seyed Hasan Mirhoseini")
    job_title = models.CharField(max_length=100, default="Junior Data Scientist")
    email = models.EmailField(default="seyedhasan.mirhoseini1367@gmail.com")
    phone = models.CharField(max_length=20, blank=True)
    location = models.CharField(max_length=100, default="Tampere, Finland")
    website = models.URLField(blank=True)

    # Professional Summary
    professional_summary = models.TextField(
        default="Passionate Junior Data Scientist with expertise in machine learning, data analysis, and building predictive models. Strong background in Python, SQL, and data visualization tools.",
        help_text="Your professional summary/objective"
    )

    # Homepage About Me (three editable paragraphs; HTML allowed)
    about_paragraph_1 = models.TextField(
        blank=True, default="",
        help_text="First paragraph of the About Me section on the homepage.",
    )
    about_paragraph_2 = models.TextField(
        blank=True, default="",
        help_text="Second paragraph (focus / specialisation). You can use &lt;strong&gt; for bold.",
    )
    about_paragraph_3 = models.TextField(
        blank=True, default="",
        help_text="Third paragraph (what you are looking for). You can use &lt;strong&gt; for bold.",
    )

    # Social Links
    github_url = models.URLField(blank=True)
    linkedin_url = models.URLField(blank=True)
    kaggle_url = models.URLField(blank=True)

    # Resume PDF — upload your CV here to enable the "Download CV" button
    cv_pdf = models.FileField(
        upload_to='resume/', storage=cv_storage,
        blank=True,
        null=True,
        help_text='Upload your CV as PDF to enable the Download CV button on the resume page',
    )

    # Resume Settings
    is_active = models.BooleanField(default=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Resume Setting"
        verbose_name_plural = "Resume Settings"

    def __str__(self):
        return "Resume Settings"

    def save(self, *args, **kwargs):
        # Ensure only one settings instance exists
        self.__class__.objects.exclude(id=self.id).delete()
        super().save(*args, **kwargs)


class Education(models.Model):
    """
    Education history
    """
    DEGREE_CHOICES = [
        ('BACHELOR', "Bachelor's Degree"),
        ('MASTER', "Master's Degree"),
        ('PHD', "PhD"),
        ('CERTIFICATION', "Certification"),
        ('DIPLOMA', "Diploma"),
    ]

    resume = models.ForeignKey(
        'ResumeSetting', on_delete=models.CASCADE,
        null=True, blank=True, related_name='education_entries',
    )
    institution = models.CharField(max_length=200)
    degree = models.CharField(max_length=20, choices=DEGREE_CHOICES)
    field_of_study = models.CharField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)
    description = models.TextField(blank=True)
    gpa = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    location = models.CharField(max_length=100, blank=True)
    display_order = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-end_date', '-start_date', 'display_order']
        verbose_name = "Education"
        verbose_name_plural = "Education"

    def __str__(self):
        return f"{self.institution} - {self.field_of_study}"


class Experience(models.Model):
    """
    Work experience
    """
    EMPLOYMENT_CHOICES = [
        ('FULL_TIME', 'Full-time'),
        ('PART_TIME', 'Part-time'),
        ('CONTRACT', 'Contract'),
        ('FREELANCE', 'Freelance'),
        ('INTERNSHIP', 'Internship'),
    ]

    resume = models.ForeignKey(
        'ResumeSetting', on_delete=models.CASCADE,
        null=True, blank=True, related_name='experience_entries',
    )
    company = models.CharField(max_length=200)
    position = models.CharField(max_length=200)
    employment_type = models.CharField(max_length=15, choices=EMPLOYMENT_CHOICES, default='FULL_TIME')
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)
    location = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)

    # Key achievements/responsibilities
    achievements = models.JSONField(default=list, help_text="List of key achievements/responsibilities")

    display_order = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-end_date', '-start_date', 'display_order']
        verbose_name = "Experience"
        verbose_name_plural = "Experience"

    def __str__(self):
        return f"{self.position} at {self.company}"


class Skill(models.Model):
    """
    Technical and professional skills
    """
    # Rows of the CV's "Core skills" table, in its order (resume/views.py).
    CATEGORY_CHOICES = [
        ('PROGRAMMING', 'Programming Languages'),
        ('ML_FRAMEWORKS', 'Machine Learning'),
        ('DEEP_LEARNING', 'Deep Learning'),
        ('TOOLS', 'LLMs, RAG & Agents'),
        ('CLOUD', 'Tools & Deployment'),
        ('DATA_VISUALIZATION', 'Visualization & Reporting'),
        ('DATA_ANALYSIS', 'Data Science & Analytics'),
        ('STATISTICS', 'Statistics'),
        ('TECHNOLOGIES', 'Technologies'),
        ('DATABASES', 'Web / Backend'),
        ('SOFT_SKILLS', 'Soft Skills'),
    ]

    resume = models.ForeignKey(
        'ResumeSetting', on_delete=models.CASCADE,
        null=True, blank=True, related_name='skill_entries',
    )
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    proficiency = models.IntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Proficiency level from 1 (Beginner) to 5 (Expert)"
    )
    description = models.TextField(blank=True)
    display_order = models.IntegerField(default=0)
    is_featured = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'display_order', 'name']
        verbose_name = "Skill"
        verbose_name_plural = "Skills"

    def __str__(self):
        return f"{self.name} ({self.get_proficiency_display()})"

    def get_proficiency_display(self):
        proficiency_map = {
            1: "Beginner",
            2: "Intermediate",
            3: "Advanced",
            4: "Expert",
            5: "Master"
        }
        return proficiency_map.get(self.proficiency, "Unknown")


class ProjectHighlight(models.Model):
    """
    Key projects to highlight on resume
    """
    resume = models.ForeignKey(
        'ResumeSetting', on_delete=models.CASCADE,
        null=True, blank=True, related_name='project_highlights',
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    technologies_used = models.JSONField(default=list, help_text='List of technologies used ["Python", "Django", "React", "PostgreSQL", "Docker", "Scikit-learn"]')
    project_url = models.URLField(blank=True)
    github_url = models.URLField(blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)
    display_order = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-end_date', '-start_date', 'display_order']
        verbose_name = "Project Highlight"
        verbose_name_plural = "Project Highlights"

    def __str__(self):
        return self.title


class Certification(models.Model):
    """
    Professional certifications
    """
    resume = models.ForeignKey(
        'ResumeSetting', on_delete=models.CASCADE,
        null=True, blank=True, related_name='certifications',
    )
    name = models.CharField(max_length=200)
    issuing_organization = models.CharField(max_length=200)
    issue_date = models.DateField()
    expiration_date = models.DateField(null=True, blank=True)
    credential_id = models.CharField(max_length=100, blank=True)
    credential_url = models.URLField(blank=True)
    display_order = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-issue_date', 'display_order']
        verbose_name = "Certification"
        verbose_name_plural = "Certifications"

    def __str__(self):
        return f"{self.name} - {self.issuing_organization}"


class Language(models.Model):
    """
    Language proficiency
    """
    LANGUAGE_CHOICES = [
        ('ENGLISH', 'English'),
        ('PERSIAN', 'Persian'),
        ('FINNISH', 'Finnish'),
        ('ARABIC', 'Arabic'),
        # Add more as needed
    ]

    PROFICIENCY_CHOICES = [
        ('NATIVE', 'Native'),
        ('FLUENT', 'Fluent'),
        ('PROFESSIONAL', 'Professional Working Proficiency'),
        ('INTERMEDIATE', 'Intermediate'),
        ('BEGINNER', 'Beginner'),
    ]

    resume = models.ForeignKey(
        'ResumeSetting', on_delete=models.CASCADE,
        null=True, blank=True, related_name='languages',
    )
    language = models.CharField(max_length=20, choices=LANGUAGE_CHOICES)
    proficiency = models.CharField(max_length=15, choices=PROFICIENCY_CHOICES)
    display_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['display_order']
        verbose_name = "Language"
        verbose_name_plural = "Languages"

    def __str__(self):
        return f"{self.get_language_display()} - {self.get_proficiency_display()}"


class QuickFact(models.Model):
    """
    A single item in the Quick Facts list on the homepage About Me card.
    """
    resume = models.ForeignKey(
        'ResumeSetting', on_delete=models.CASCADE,
        related_name='quick_facts',
    )
    icon = models.CharField(
        max_length=10, default='📌',
        help_text="Emoji icon shown before the fact, e.g. 🎓",
    )
    text = models.CharField(
        max_length=300,
        help_text="The fact text. You can use HTML e.g. <strong>bold</strong>.",
    )
    link_text = models.CharField(
        max_length=100, blank=True,
        help_text="Optional: label of an inline link, e.g. 'see docs'",
    )
    link_url = models.CharField(
        max_length=300, blank=True,
        help_text="Optional: URL for the inline link (relative or absolute)",
    )
    display_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['display_order']
        verbose_name = 'Quick Fact'
        verbose_name_plural = 'Quick Facts'

    def __str__(self):
        return self.text[:60]

class StoredFile(models.Model):
    """A small uploaded file kept in the database (resume/storage.py).

    Render's disk is wiped on every deploy, so the CV PDF uploaded in the admin
    lives here instead and survives deploys.
    """
    name         = models.CharField(max_length=255, unique=True)
    data         = models.BinaryField()
    content_type = models.CharField(max_length=100, default='application/pdf')
    uploaded_at  = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
