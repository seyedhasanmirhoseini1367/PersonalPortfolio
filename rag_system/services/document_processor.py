# rag_system/services/document_processor.py
import os
import PyPDF2
import docx
from typing import List, Dict, Any
from django.conf import settings
from ..models import Document, DocumentChunk


class DocumentProcessor:
    def __init__(self):
        self.chunk_size = settings.RAG_CONFIG['CHUNK_SIZE']
        self.chunk_overlap = settings.RAG_CONFIG['CHUNK_OVERLAP']

    def read_file(self, file_path: str) -> str:
        """Read different file types and extract text"""
        ext = os.path.splitext(file_path)[1].lower()

        try:
            if ext == '.pdf':
                return self._read_pdf(file_path)
            elif ext == '.docx':
                return self._read_docx(file_path)
            elif ext in ['.txt', '.md']:
                return self._read_text(file_path)
            else:
                raise ValueError(f"Unsupported file type: {ext}")
        except Exception as e:
            raise Exception(f"Error reading file {file_path}: {str(e)}")

    def _read_pdf(self, file_path: str) -> str:
        """Extract text from PDF files"""
        text = ""
        with open(file_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            for page in reader.pages:
                text += page.extract_text() + "\n"
        return text

    def _read_docx(self, file_path: str) -> str:
        """Extract text from DOCX files"""
        doc = docx.Document(file_path)
        return "\n".join([paragraph.text for paragraph in doc.paragraphs])

    def _read_text(self, file_path: str) -> str:
        """Read plain text files"""
        with open(file_path, 'r', encoding='utf-8') as file:
            return file.read()

    def chunk_text(self, text: str, title: str = "") -> List[Dict[str, Any]]:
        """Split text into overlapping chunks"""
        words = text.split()
        chunks = []

        for i in range(0, len(words), self.chunk_size - self.chunk_overlap):
            chunk_words = words[i:i + self.chunk_size]
            chunk_text = ' '.join(chunk_words)

            chunks.append({
                'content': chunk_text,
                'metadata': {
                    'chunk_index': len(chunks),
                    'title': title,
                    'start_word': i,
                    'end_word': min(i + self.chunk_size, len(words))
                }
            })

        return chunks

    def process_document(self, file_path: str, document_type: str, title: str = None) -> Document:
        """Process a document and create chunks"""
        if title is None:
            title = os.path.basename(file_path)

        # Read file content
        content = self.read_file(file_path)

        # Create document
        document = Document.objects.create(
            title=title,
            content=content,
            document_type=document_type,
            source=file_path,
            metadata={'file_size': len(content), 'file_path': file_path}
        )

        # Create chunks
        chunks = self.chunk_text(content, title)
        for chunk_data in chunks:
            DocumentChunk.objects.create(
                document=document,
                content=chunk_data['content'],
                chunk_index=chunk_data['metadata']['chunk_index'],
                metadata=chunk_data['metadata']
            )

        return document
