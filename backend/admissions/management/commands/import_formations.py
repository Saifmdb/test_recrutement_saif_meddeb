from pathlib import Path

import openpyxl
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from admissions.models import Formation
from admissions.services.text import normalize


class Command(BaseCommand):
    help = "Import the formations from the Excel file 'diplôme spécialité.xlsx' (replaces the catalogue)."

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", default=str(settings.FORMATIONS_FILE))

    @transaction.atomic
    def handle(self, path, **options):
        file = Path(path)
        if not file.exists():
            raise CommandError(f"File not found: {file}")
        rows = openpyxl.load_workbook(file, read_only=True, data_only=True).worksheets[0].iter_rows(values_only=True)
        next(rows)  # header: Diplôme | Specialité | Ecole | Niveau éligible | Nationalité éligible | Nature du bac

        if Formation.objects.filter(candidatures__isnull=False).exists():
            raise CommandError("Some formations already have candidatures: refusing to replace the catalogue.")
        Formation.objects.all().delete()
        count = 0
        for row in rows:
            if not row or not row[0]:
                continue
            diplome, specialite, ecole, niveau, nationalite, bac = (" ".join(str(v or "").split()) for v in row[:6])
            Formation.objects.create(
                diplome=diplome,
                specialite=specialite,
                ecole=ecole,
                niveau_requis=niveau,
                nationalite_requise=nationalite,
                bac_requis=bac,
                search_text=normalize(f"{diplome} {specialite} {ecole}"),
            )
            count += 1
        self.stdout.write(self.style.SUCCESS(f"{count} formations imported from {file.name}"))
