#!/usr/bin/env python3
"""
PDF Redaction Extractor CLI

Processes PDF files to extract a structured catalogue of every redaction,
using dual detection (PyMuPDF annotations + OpenCV pixel analysis).

Usage:
    python extract.py --input ./pdfs/ --output ./output/
"""

import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

import click

from redaction_extractor.models import ExtractionParams
from redaction_extractor.parallel import process_corpus_with_tqdm, get_processing_stats
from redaction_extractor.output_writer import write_all_outputs
from redaction_extractor.db_writer import write_to_database


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


def validate_input_dir(ctx, param, value):
    """Validate that input directory exists and contains PDFs."""
    path = Path(value)
    if not path.exists():
        raise click.BadParameter(f"Input directory does not exist: {value}")
    if not path.is_dir():
        raise click.BadParameter(f"Input path is not a directory: {value}")
    return path


def validate_output_dir(ctx, param, value):
    """Validate output directory (create if needed)."""
    path = Path(value)
    return path


@click.command()
@click.option(
    "--input", "-i",
    "input_dir",
    required=True,
    callback=validate_input_dir,
    help="Input directory containing PDF files to process"
)
@click.option(
    "--output", "-o",
    "output_dir",
    required=True,
    callback=validate_output_dir,
    help="Output directory for results (catalogue.json, catalogue.csv, images/)"
)
@click.option(
    "--threshold", "-t",
    default=30,
    type=int,
    help="Pixel darkness threshold (0-255). Values below this are considered redaction. Default: 30"
)
@click.option(
    "--min-aspect-ratio",
    default=3.0,
    type=float,
    help="Minimum width/height ratio for redaction bars. Default: 3.0"
)
@click.option(
    "--border-padding",
    default=50,
    type=int,
    help="Padding in pixels for context crop images. Default: 50"
)
@click.option(
    "--workers", "-w",
    default=4,
    type=int,
    help="Number of parallel worker processes. Default: 4"
)
@click.option(
    "--dpi",
    default=150,
    type=int,
    help="DPI for rendering pages (higher = more accurate but slower). Default: 150"
)
@click.option(
    "--min-area",
    default=500,
    type=int,
    help="Minimum area in pixels for redaction detection. Default: 500"
)
@click.option(
    "--context-chars",
    default=200,
    type=int,
    help="Characters of context to extract before/after redactions. Default: 200"
)
@click.option(
    "--iou-threshold",
    default=0.7,
    type=float,
    help="IoU threshold for merging detections from both methods. Default: 0.7"
)
@click.option(
    "--subset", "-s",
    default=None,
    type=int,
    help="Process only the first N PDFs (for testing)"
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Enable verbose output"
)
@click.option(
    "--no-images",
    is_flag=True,
    help="Skip image extraction (faster processing)"
)
@click.option(
    "--db-url",
    default=None,
    envvar="REDACTION_DB_URL",
    help="PostgreSQL connection URL to write results (e.g. postgresql://user:pass@host:5432/dbname)"
)
def main(
    input_dir: Path,
    output_dir: Path,
    threshold: int,
    min_aspect_ratio: float,
    border_padding: int,
    workers: int,
    dpi: int,
    min_area: int,
    context_chars: int,
    iou_threshold: float,
    subset: int,
    verbose: bool,
    no_images: bool,
    db_url: Optional[str],
):
    """
    Extract and catalogue redactions from PDF files.
    
    Processes all PDFs in the input directory, detecting redactions using
    both PyMuPDF (annotations/drawings) and OpenCV (pixel analysis).
    
    Outputs:
    
    \b
    - catalogue.json: Full structured data for all redactions
    - catalogue.csv: Flat CSV format for analysis
    - summary.json: Aggregate statistics
    - images/: Cropped redaction images (unless --no-images)
    """
    # Set logging level
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Print banner
    click.echo("=" * 60)
    click.echo("PDF Redaction Extractor")
    click.echo("=" * 60)
    click.echo()
    
    # Print configuration
    click.echo("Configuration:")
    click.echo(f"  Input directory:  {input_dir}")
    click.echo(f"  Output directory: {output_dir}")
    click.echo(f"  Threshold:        {threshold}")
    click.echo(f"  Min aspect ratio: {min_aspect_ratio}")
    click.echo(f"  Border padding:   {border_padding}px")
    click.echo(f"  Workers:          {workers}")
    click.echo(f"  DPI:              {dpi}")
    click.echo(f"  Extract images:   {not no_images}")
    if subset:
        click.echo(f"  Subset:           first {subset} PDFs")
    if db_url:
        click.echo(f"  Database:         {db_url.split('@')[-1] if '@' in db_url else '(configured)'}")
    click.echo()
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Build extraction parameters
    params = ExtractionParams(
        threshold=threshold,
        min_aspect_ratio=min_aspect_ratio,
        min_area=min_area,
        border_padding=border_padding,
        dpi=dpi,
        context_chars=context_chars,
        iou_threshold=iou_threshold,
    )
    
    # Count PDFs
    pdf_count = len(list(input_dir.glob("**/*.pdf")))
    if pdf_count == 0:
        click.echo(click.style("Error: No PDF files found in input directory", fg="red"))
        sys.exit(1)
    
    click.echo(f"Found {pdf_count} PDF file(s) to process")
    click.echo()
    
    # Process corpus
    start_time = datetime.now()
    
    # If no-images, pass None as output_dir for image extraction
    image_output_dir = None if no_images else output_dir
    
    try:
        corpus = process_corpus_with_tqdm(
            input_dir,
            image_output_dir,
            params,
            workers,
            subset=subset
        )
    except KeyboardInterrupt:
        click.echo()
        click.echo(click.style("Processing interrupted by user", fg="yellow"))
        sys.exit(130)
    except Exception as e:
        click.echo(click.style(f"Error during processing: {e}", fg="red"))
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)
    
    elapsed = datetime.now() - start_time
    
    click.echo()
    click.echo("Processing complete!")
    click.echo(f"  Time elapsed: {elapsed}")
    click.echo()
    
    # Get processing stats
    stats = get_processing_stats(corpus)
    
    click.echo("Results:")
    click.echo(f"  Documents processed: {stats['successful_documents']}/{stats['total_documents']}")
    click.echo(f"  Total pages:         {stats['total_pages']}")
    click.echo(f"  Total redactions:    {stats['total_redactions']}")
    
    if stats['failed_documents'] > 0:
        click.echo()
        click.echo(click.style(f"  Failed documents: {stats['failed_documents']}", fg="yellow"))
        if verbose:
            for doc_id in stats['failed_doc_ids']:
                click.echo(f"    - {doc_id}")
    
    click.echo()
    
    # Write outputs
    click.echo("Writing output files...")
    
    try:
        paths = write_all_outputs(corpus, params, output_dir)
        
        click.echo(f"  {paths['catalogue_json']}")
        click.echo(f"  {paths['catalogue_csv']}")
        click.echo(f"  {paths['summary_json']}")
        
        if not no_images:
            images_dir = output_dir / "images"
            image_count = len(list(images_dir.glob("*.png"))) if images_dir.exists() else 0
            click.echo(f"  {images_dir}/ ({image_count} images)")

        if db_url:
            click.echo()
            click.echo("Writing to database...")
            try:
                run_id = write_to_database(corpus, params, db_url)
                click.echo(f"  Extraction run ID: {run_id}")
            except Exception as e:
                click.echo(click.style(f"Error writing to database: {e}", fg="red"))
                if verbose:
                    import traceback
                    traceback.print_exc()
                sys.exit(1)
        
    except Exception as e:
        click.echo(click.style(f"Error writing outputs: {e}", fg="red"))
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)
    
    click.echo()
    click.echo(click.style("Done!", fg="green"))


if __name__ == "__main__":
    main()
