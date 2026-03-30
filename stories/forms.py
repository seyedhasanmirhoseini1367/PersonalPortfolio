# stories/forms.py
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from .models import Story, Comment, Tag
from django.core.exceptions import ValidationError


class StoryForm(forms.ModelForm):
    """Form for creating and editing stories."""

    # Additional fields for tags as comma-separated input
    tag_input = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Enter tags separated by commas',
            'class': 'form-control'
        }),
        help_text="Enter tags separated by commas (e.g., python, django, machine-learning)"
    )

    class Meta:
        model = Story
        fields = [
            'title', 'excerpt', 'content', 'featured_image',
            'status', 'allow_comments', 'is_featured'
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter your story title'
            }),
            'excerpt': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Brief summary of your story (optional)'
            }),
            'content': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 15,
                'placeholder': 'Write your story here...'
            }),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'featured_image': forms.ClearableFileInput(attrs={
                'class': 'form-control-file'
            }),
        }
        help_texts = {
            'excerpt': 'Optional brief summary (max 500 characters)',
            'content': 'Write your full story here',
            'featured_image': 'Optional image to accompany your story',
            'status': 'Choose whether to publish now or save as draft',
        }

    def __init__(self, *args, **kwargs):
        self.author = kwargs.pop('author', None)
        super().__init__(*args, **kwargs)

        # If editing, pre-populate tag input
        if self.instance and self.instance.pk:
            tags = self.instance.tags.all()
            self.fields['tag_input'].initial = ', '.join([tag.name for tag in tags])

    def clean_title(self):
        title = self.cleaned_data.get('title')
        if len(title) < 10:
            raise ValidationError('Title must be at least 10 characters long.')
        return title

    def clean_content(self):
        content = self.cleaned_data.get('content')
        if len(content) < 100:
            raise ValidationError('Story content must be at least 100 characters.')
        return content

    def save(self, commit=True):
        story = super().save(commit=False)

        # Set author if not already set
        if self.author and not story.author:
            story.author = self.author

        if commit:
            story.save()

            # Handle tags
            tag_input = self.cleaned_data.get('tag_input', '')
            if tag_input:
                tag_names = [name.strip() for name in tag_input.split(',') if name.strip()]

                # Clear existing tags
                story.tags.clear()

                # Add new tags
                for tag_name in tag_names:
                    tag, created = Tag.objects.get_or_create(
                        name__iexact=tag_name,
                        defaults={'name': tag_name.lower()}
                    )
                    story.tags.add(tag)

        return story


class CommentForm(forms.ModelForm):
    """Form for adding comments to stories."""

    class Meta:
        model = Comment
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Write your comment here...',
                'style': 'resize: vertical;'
            })
        }

    def __init__(self, *args, **kwargs):
        self.story = kwargs.pop('story', None)
        self.author = kwargs.pop('author', None)
        self.parent = kwargs.pop('parent', None)
        super().__init__(*args, **kwargs)

    def clean_content(self):
        content = self.cleaned_data.get('content')
        if len(content) < 10:
            raise ValidationError('Comment must be at least 10 characters.')
        if len(content) > 2000:
            raise ValidationError('Comment cannot exceed 2000 characters.')
        return content

    def save(self, commit=True):
        comment = super().save(commit=False)

        # Set related objects if provided
        if self.story:
            comment.story = self.story
        if self.author:
            comment.author = self.author
        if self.parent:
            comment.parent = self.parent

        if commit:
            comment.save()

        return comment


class StorySearchForm(forms.Form):
    """Form for searching stories."""

    query = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search stories...'
        })
    )

    tag = forms.ModelChoiceField(
        queryset=Tag.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    author = forms.ModelChoiceField(
        queryset=get_user_model().objects.filter(stories__isnull=False).distinct(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    sort_by = forms.ChoiceField(
        choices=[
            ('-published_at', 'Newest First'),
            ('published_at', 'Oldest First'),
            ('-view_count', 'Most Viewed'),
            ('-likes', 'Most Liked'),
            ('title', 'Title A-Z'),
        ],
        required=False,
        initial='-published_at',
        widget=forms.Select(attrs={'class': 'form-control'})
    )


class ReplyForm(forms.ModelForm):
    """Form for replying to comments."""

    class Meta:
        model = Comment
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Write your reply here...',
                'style': 'resize: vertical;'
            })
        }

    def __init__(self, *args, **kwargs):
        self.story = kwargs.pop('story', None)
        self.author = kwargs.pop('author', None)
        self.parent = kwargs.pop('parent', None)
        super().__init__(*args, **kwargs)

    def clean_content(self):
        content = self.cleaned_data.get('content')
        if len(content) < 5:
            raise ValidationError('Reply must be at least 5 characters.')
        if len(content) > 1000:
            raise ValidationError('Reply cannot exceed 1000 characters.')
        return content

    def save(self, commit=True):
        comment = super().save(commit=False)

        # Set related objects if provided
        if self.story:
            comment.story = self.story
        if self.author:
            comment.author = self.author
        if self.parent:
            comment.parent = self.parent

        if commit:
            comment.save()

        return comment