import json
from pathlib import Path
from uuid import UUID
from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import ValidationError
from billing.models import Business
from billing.inventory import read_catalog, validate_catalog, import_catalog, import_report

class Command(BaseCommand):
    help = 'Preview and explicitly confirm a kirana catalog import into ONE business. Existing SKUs are preserved.'
    def add_arguments(self, parser):
        parser.add_argument('--business-id', required=True)
        parser.add_argument('--file', help='Optional CSV/JSON path; defaults to the bundled researched catalog.')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--confirm', action='store_true', help='Owner has reviewed the dry-run and authorizes this import.')
        parser.add_argument('--report', help='Write a detailed JSON report at this path.')
    def handle(self, *args, **options):
        try:
            business = Business.objects.get(pk=UUID(options['business_id']), is_active=True)
            path = Path(options['file']) if options['file'] else None
            rows = read_catalog(path.read_bytes(), path.name) if path else read_catalog()
            rows = validate_catalog(rows, business)
            preview = import_report(business, rows)
            self.stdout.write(f"{business.name} ({business.pk}): {preview['create_count']} new, {preview['skipped_count']} preserved, {preview['needs_review_count']} unpriced. New stock: 100 each.")
            if not options['dry_run'] and not options['confirm']:
                raise CommandError('No data imported. Run --dry-run --report preview.json, review every row, then repeat with --confirm to authorize this business.')
            report = import_catalog(business, rows, dry_run=options['dry_run'])
            output = json.dumps(report, indent=2, ensure_ascii=False)
            if options['report']: Path(options['report']).write_text(output+'\n', encoding='utf-8')
            else: self.stdout.write(output)
            self.stdout.write(self.style.SUCCESS('Dry-run complete; no changes.' if options['dry_run'] else 'Import complete; existing SKUs preserved.'))
        except (Business.DoesNotExist, ValueError): raise CommandError('Invalid or inactive business ID, or invalid input.')
        except (OSError, ValidationError) as exc: raise CommandError(str(exc))
