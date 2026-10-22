from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from admissions.services import rag


class Command(BaseCommand):
    help = "Index the admission procedure document(s) (PDF, DOCX, TXT, MD) in data/documents for the RAG."

    def add_arguments(self, parser):
        parser.add_argument("directory", nargs="?", default=str(settings.DOCUMENTS_DIR))

    def handle(self, directory, **options):
        report = rag.ingest_directory(Path(directory))
        if not report["files"]:
            self.stdout.write(self.style.WARNING(f"No PDF/DOCX/TXT/MD document found in {directory}"))
            return
        for f in report["files"]:
            self.stdout.write(f"  {f['name']}: {f['chunks']} chunks")
        self.stdout.write(self.style.SUCCESS(f"{report['chunks']} chunks indexed."))
