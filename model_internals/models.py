from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class Walkthrough(models.Model):
    # Seven groups, listed in reading order: the list page renders one heading
    # per group in exactly this sequence, so the section reads as a curriculum.
    CATEGORY_CHOICES = [
        ('foundations',  'Foundations'),
        ('linear',       'Linear Models'),
        ('instance',     'Instance & Probabilistic'),
        ('trees',        'Trees & Ensembles'),
        ('kernel',       'Kernel Methods'),
        ('unsupervised', 'Unsupervised Learning'),
        ('deep',         'Deep Learning'),
    ]

    # One-line description shown under each group heading.
    CATEGORY_BLURBS = {
        'foundations':  'What learning is, how to measure it, and how the step is taken',
        'linear':       'A weighted sum, and what changes when you squash it',
        'instance':     'Learn nothing in advance; compare, or count',
        'trees':        'Ask questions, then combine many answers',
        'kernel':       'Widest margin, and inner products in disguise',
        'unsupervised': 'No labels: find structure, or compress',
        'deep':         'Layers, weight sharing, memory, attention',
    }

    DIFFICULTY_CHOICES = [
        ('beginner',     'Beginner'),
        ('intermediate', 'Intermediate'),
        ('advanced',     'Advanced'),
    ]

    title        = models.CharField(max_length=200)
    slug         = models.SlugField(max_length=220, unique=True, blank=True)
    tagline      = models.CharField(max_length=300, blank=True)
    summary      = models.TextField(blank=True, help_text='Short blurb shown on the list card')
    category     = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    difficulty   = models.CharField(max_length=20, choices=DIFFICULTY_CHOICES, default='intermediate')
    icon         = models.CharField(max_length=10, blank=True, help_text='Emoji shown on the card, e.g. 🧮')

    cover_image           = models.ImageField(
        upload_to='how_models_work/covers/%Y/%m/', blank=True, null=True,
        help_text='Shown right below the title, e.g. the architecture diagram from the original paper',
    )
    cover_image_caption   = models.CharField(max_length=300, blank=True, help_text='Short caption under the image')
    cover_image_credit    = models.CharField(max_length=300, blank=True, help_text='e.g. "Vaswani et al., 2017 — Attention Is All You Need"')
    cover_image_credit_url = models.URLField(blank=True, help_text='Link to the paper/source for the credit line')

    is_published = models.BooleanField(default=True)
    order        = models.PositiveIntegerField(default=0)
    created_at   = models.DateTimeField(auto_now_add=True)

    # sha256 of the notebook this was imported from. Lets a deploy tell
    # "already imported" apart from "imported, but the notebook has changed
    # since" - without it, --if-empty would freeze the content forever.
    source_fingerprint = models.CharField(max_length=64, blank=True, editable=False)

    class Meta:
        ordering = ['order', '-created_at']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('model_internals:walkthrough_detail', args=[self.slug])


class WalkthroughBlock(models.Model):
    TEXT   = 'text'
    OUTPUT = 'output'
    IMAGE  = 'image'
    BLOCK_TYPE_CHOICES = [
        (TEXT,   'Explanation (markdown)'),
        (OUTPUT, 'Computed output (numbers)'),
        (IMAGE,  'Image / plot'),
    ]

    walkthrough = models.ForeignKey(Walkthrough, on_delete=models.CASCADE, related_name='blocks')
    order       = models.PositiveIntegerField(default=0)
    block_type  = models.CharField(max_length=10, choices=BLOCK_TYPE_CHOICES, default=TEXT)
    content     = models.TextField(blank=True, help_text='Markdown for text blocks, plain text for output blocks')
    image       = models.ImageField(upload_to='how_models_work/%Y/%m/', blank=True, null=True)
    caption     = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f'{self.walkthrough.title} — block {self.order} ({self.block_type})'


class WalkthroughReference(models.Model):
    walkthrough = models.ForeignKey(Walkthrough, on_delete=models.CASCADE, related_name='references')
    order       = models.PositiveIntegerField(default=0)
    title       = models.CharField(max_length=300, help_text='e.g. "Attention Is All You Need"')
    authors     = models.CharField(max_length=300, blank=True, help_text='e.g. "Vaswani et al., 2017"')
    url         = models.URLField(blank=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.title
