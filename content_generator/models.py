from django.db import models
from PersonalPortfolio.storage import image_storage
from django.conf import settings
import uuid


class CompetitorProfile(models.Model):
    name        = models.CharField(max_length=200)
    website     = models.URLField(blank=True)
    description = models.TextField(
        help_text="Their product descriptions, marketing copy, positioning — the more the better."
    )
    notes       = models.TextField(blank=True, help_text="Internal notes (not sent to AI)")
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class CompanyProfile(models.Model):
    owner            = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='company_profiles',
        help_text="Profile owner. Null = admin-created global profile visible to all clients.",
    )
    name             = models.CharField(max_length=200)
    about            = models.TextField(help_text="About the company, services, brand voice, values — the richer the better.")
    target_audience  = models.CharField(max_length=300, blank=True, help_text="e.g. Finnish SMEs, 10–100 employees")
    tone_of_voice    = models.CharField(max_length=200, blank=True, help_text="e.g. Professional, warm, concise")
    competitor_info  = models.TextField(blank=True, help_text="Legacy free-text competitors (used if no structured competitors linked)")
    competitors      = models.ManyToManyField(CompetitorProfile, blank=True, related_name='tracked_by',
                                              help_text="Link structured competitor profiles for richer gap analysis")
    rag_indexed      = models.BooleanField(default=False, help_text="Set automatically when RAG index is built")
    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class ServiceProduct(models.Model):
    TYPE_SERVICE = 'service'
    TYPE_PRODUCT = 'product'
    TYPE_CHOICES = [
        (TYPE_SERVICE, 'Service'),
        (TYPE_PRODUCT, 'Product'),
    ]

    company       = models.ForeignKey(CompanyProfile, on_delete=models.CASCADE, related_name='services')
    name          = models.CharField(max_length=200)
    description   = models.TextField()
    item_type     = models.CharField(max_length=10, choices=TYPE_CHOICES, default=TYPE_SERVICE)
    display_order = models.IntegerField(default=0)
    image         = models.ImageField(upload_to='content_generator/service_images/', storage=image_storage, null=True, blank=True)
    document      = models.FileField(upload_to='content_generator/service_docs/',   null=True, blank=True,
                                     help_text="PDF, DOCX, or TXT — used by the AI agents")
    video_url     = models.URLField(null=True, blank=True, help_text="YouTube or Vimeo link")
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['display_order', 'name']

    def __str__(self):
        return f"{self.name} ({self.company.name})"


class CompanyDocument(models.Model):
    company_profile = models.ForeignKey(CompanyProfile, on_delete=models.CASCADE, related_name='documents')
    title           = models.CharField(max_length=200, blank=True)
    file            = models.FileField(upload_to='content_generator/company_docs/',
                                       help_text="PDF, DOCX, TXT — indexed for RAG")
    uploaded_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.title or self.file.name} — {self.company_profile.name}"

    def filename(self):
        import os
        return os.path.basename(self.file.name)


class CMSConnection(models.Model):
    CMS_WORDPRESS = 'wordpress'
    CMS_NOTION    = 'notion'
    CMS_HUBSPOT   = 'hubspot'
    CMS_CHOICES   = [
        (CMS_WORDPRESS, 'WordPress'),
        (CMS_NOTION,    'Notion'),
        (CMS_HUBSPOT,   'HubSpot'),
    ]

    company_profile = models.ForeignKey(CompanyProfile, on_delete=models.CASCADE,
                                        related_name='cms_connections')
    name            = models.CharField(max_length=100)
    cms_type        = models.CharField(max_length=20, choices=CMS_CHOICES)
    api_url         = models.CharField(max_length=500,
                                       help_text="Base site URL (e.g. https://mysite.com)")
    api_token       = models.CharField(max_length=500,
                                       help_text="Application Password (WordPress) or Bearer token")
    is_active       = models.BooleanField(default=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.get_cms_type_display()})"


class GenerationJob(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_DONE    = 'done'
    STATUS_FAILED  = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_DONE,    'Done'),
        (STATUS_FAILED,  'Failed'),
    ]

    FORMAT_CHOICES = [
        ('blog_post',    'Blog Post'),
        ('landing_page', 'Landing Page'),
        ('social_post',  'Social Media Post'),
        ('email',        'Email Campaign'),
        ('ad_copy',      'Ad Copy'),
        ('motto',        'Tagline / Motto'),
    ]

    TONE_CHOICES = [
        ('professional', 'Professional'),
        ('casual',       'Casual'),
        ('bold',         'Bold'),
        ('empathetic',   'Empathetic'),
        ('technical',    'Technical'),
    ]

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job_group_id    = models.UUIDField(default=uuid.uuid4, db_index=True,
                                       help_text="All formats from one submission share this ID")
    owner           = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='generation_jobs',
    )
    variant_group_id = models.UUIDField(null=True, blank=True, db_index=True,
                                        help_text="All variants of the same format share this ID")
    variant_index    = models.IntegerField(default=0,
                                           help_text="0 = original, 1+ = A/B variants")

    company_profile = models.ForeignKey(CompanyProfile, on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name='jobs')
    service         = models.ForeignKey(ServiceProduct, on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name='jobs')
    parent_job      = models.ForeignKey('self', on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name='reruns',
                                        help_text="Set when this job is a re-run of another")

    company_name     = models.CharField(max_length=200)
    goal             = models.TextField()
    content_format   = models.CharField(max_length=20, choices=FORMAT_CHOICES, default='blog_post')
    keywords         = models.CharField(max_length=500, blank=True)
    company_docs     = models.TextField(blank=True)
    competitor_docs  = models.TextField(blank=True)
    tone_preset      = models.CharField(max_length=20, choices=TONE_CHOICES, default='professional')
    target_languages = models.JSONField(default=list,
                                        help_text="e.g. [\"English\", \"Finnish\"]")

    status          = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_message   = models.TextField(blank=True)

    content_en      = models.JSONField(null=True, blank=True)
    content_fi      = models.JSONField(null=True, blank=True)
    evaluation      = models.JSONField(null=True, blank=True)
    overall_score   = models.IntegerField(null=True, blank=True)

    user_approved   = models.BooleanField(null=True, blank=True,
                                          help_text="True=approved, False=rejected, None=not rated")
    user_feedback   = models.TextField(blank=True,
                                       help_text="Human feedback for RLHF-style re-runs")

    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.company_name} — {self.get_content_format_display()} ({self.status})"


class KnowledgeChunk(models.Model):
    """A piece of a client's company text, searched by the content pipeline.

    Stored in the database so it survives deploys (the old on-disk vector
    store was wiped with the container). Searched with BM25 (rank-bm25).
    """
    client_id  = models.CharField(max_length=80, db_index=True)
    scope_id   = models.CharField(max_length=80, default='general')
    scope_name = models.CharField(max_length=200, blank=True)
    position   = models.PositiveIntegerField(default=0)
    text       = models.TextField()

    class Meta:
        ordering = ['client_id', 'scope_id', 'position']
        indexes = [models.Index(fields=['client_id', 'scope_id'])]

    def __str__(self):
        return f"{self.client_id}/{self.scope_id}#{self.position}"
