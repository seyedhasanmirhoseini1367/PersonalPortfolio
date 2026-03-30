# rag_system/admin.py
from django.contrib import admin
from .models import Document, DocumentChunk, QueryLog


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ['title', 'document_type', 'source', 'created_at', 'updated_at']
    list_filter = ['document_type', 'created_at']
    search_fields = ['title', 'content']
    readonly_fields = ['created_at', 'updated_at', 'id']  # Add id to readonly
    fieldsets = [
        ('Basic Information', {
            'fields': ['title', 'document_type', 'source']
        }),
        ('Content', {
            'fields': ['content']
        }),
        ('Metadata', {
            'fields': ['metadata'],
            'classes': ['collapse']
        }),
        ('Timestamps', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        }),
    ]


@admin.register(DocumentChunk)
class DocumentChunkAdmin(admin.ModelAdmin):
    list_display = ['document_title', 'chunk_index', 'has_embedding', 'created_at_display']
    list_filter = ['document__document_type', 'chunk_index']
    search_fields = ['content', 'document__title']
    readonly_fields = ['id', 'created_at']  # Fix readonly_fields

    def document_title(self, obj):
        return obj.document.title

    document_title.short_description = 'Document'

    def has_embedding(self, obj):
        return bool(obj.embedding)

    has_embedding.boolean = True
    has_embedding.short_description = 'Has Embedding'

    def created_at_display(self, obj):
        return obj.created_at.strftime("%Y-%m-%d %H:%M")

    created_at_display.short_description = 'Created At'


@admin.register(QueryLog)
class QueryLogAdmin(admin.ModelAdmin):
    list_display = ['truncated_query', 'truncated_response', 'created_at_display']
    list_filter = ['created_at']
    search_fields = ['query', 'response']
    readonly_fields = ['id', 'created_at']  # Fix readonly_fields

    def truncated_query(self, obj):
        return obj.query[:50] + '...' if len(obj.query) > 50 else obj.query

    truncated_query.short_description = 'Query'

    def truncated_response(self, obj):
        return obj.response[:50] + '...' if len(obj.response) > 50 else obj.response

    truncated_response.short_description = 'Response'

    def created_at_display(self, obj):
        return obj.created_at.strftime("%Y-%m-%d %H:%M")

    created_at_display.short_description = 'Created At'