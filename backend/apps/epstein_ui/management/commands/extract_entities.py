"""Batch NER extraction: scan all documents and extract named entities via spaCy."""
import fitz
import spacy
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.epstein_ui.models import (
    ExtractionRun,
    ExtractedDocument,
    DocumentEntity,
)


class Command(BaseCommand):
    help = "Extract named entities from all PDF documents using spaCy NER."

    def add_arguments(self, parser):
        parser.add_argument(
            "--run-id",
            type=int,
            help="Extraction run ID to process. Defaults to the latest run.",
        )
        parser.add_argument(
            "--model",
            default="en_core_web_lg",
            help="spaCy model to use (default: en_core_web_lg).",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete existing entities for these documents before extracting.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=50,
            help="spaCy nlp.pipe batch size.",
        )

    def handle(self, *args, **options):
        run_id = options["run_id"]
        model_name = options["model"]
        clear = options["clear"]
        batch_size = options["batch_size"]

        if run_id:
            try:
                run = ExtractionRun.objects.get(pk=run_id)
            except ExtractionRun.DoesNotExist:
                self.stderr.write(f"Extraction run {run_id} not found.")
                return
        else:
            run = ExtractionRun.objects.order_by("-started_at").first()
            if not run:
                self.stderr.write("No extraction runs found.")
                return

        docs = list(
            ExtractedDocument.objects.filter(extraction_run=run)
            .exclude(error__gt="")
            .order_by("doc_id")
        )
        self.stdout.write(f"Processing {len(docs)} documents from run #{run.pk}")

        self.stdout.write(f"Loading spaCy model '{model_name}'...")
        nlp = spacy.load(model_name, disable=["lemmatizer"])
        self.stdout.write(self.style.SUCCESS(f"Model loaded."))

        ENTITY_TYPES = {
            "PERSON", "ORG", "GPE", "LOC", "DATE",
            "NORP", "FAC", "EVENT", "LAW", "MONEY",
        }

        total_entities = 0
        processed = 0

        for doc_record in docs:
            pdf_path = Path(doc_record.file_path)
            if not pdf_path.is_file():
                self.stderr.write(f"  SKIP {doc_record.doc_id}: file not found")
                continue

            if clear:
                DocumentEntity.objects.filter(extracted_document=doc_record).delete()

            try:
                pdf_doc = fitz.open(str(pdf_path))
            except Exception as e:
                self.stderr.write(f"  SKIP {doc_record.doc_id}: {e}")
                continue

            page_texts = []
            for page_idx in range(len(pdf_doc)):
                page = pdf_doc[page_idx]
                text = page.get_text("text")
                if text.strip():
                    page_texts.append((page_idx + 1, text))
            pdf_doc.close()

            if not page_texts:
                processed += 1
                continue

            # entity_key -> (entity_type, {page_nums})
            doc_entities = defaultdict(lambda: {"pages": defaultdict(int)})

            texts_only = [t for _, t in page_texts]
            page_nums = [p for p, _ in page_texts]

            for i, spacy_doc in enumerate(nlp.pipe(texts_only, batch_size=batch_size)):
                page_num = page_nums[i]
                for ent in spacy_doc.ents:
                    etype = ent.label_
                    if etype not in ENTITY_TYPES:
                        etype = "OTHER"
                    etext = ent.text.strip()
                    if not etext or len(etext) > 500:
                        continue
                    key = (etext, etype)
                    doc_entities[key]["pages"][page_num] += 1

            entities_to_create = []
            for (etext, etype), data in doc_entities.items():
                for page_num, count in data["pages"].items():
                    entities_to_create.append(
                        DocumentEntity(
                            extracted_document=doc_record,
                            entity_text=etext,
                            entity_type=etype,
                            page_num=page_num,
                            count=count,
                        )
                    )

            if entities_to_create:
                DocumentEntity.objects.bulk_create(entities_to_create, batch_size=500)
                total_entities += len(entities_to_create)

            processed += 1
            if processed % 10 == 0:
                self.stdout.write(f"  {processed}/{len(docs)} docs, {total_entities} entities so far")

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Processed {processed} documents, extracted {total_entities} entity records."
            )
        )
