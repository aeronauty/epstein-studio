# PDF Redaction Extractor

A Python CLI tool that processes PDF files and extracts a structured catalogue of every redaction.

## Features

- **Dual Detection**: Combines PyMuPDF annotation/drawing extraction with OpenCV pixel-level black bar detection
- **Character Estimation**: Uses surrounding text font metrics to estimate redacted character counts
- **Context Extraction**: Captures ~200 characters before and after each redaction
- **Leakage Detection**: Analyzes border pixels for ascender/descender letterform leakage
- **Multi-line Merging**: Detects and groups redactions that span multiple lines
- **Image Extraction**: Saves tight and context-padded crops of each redaction
- **Parallel Processing**: Scales to thousands of PDFs using multiprocessing

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```bash
python extract.py --input ./pdfs/ --output ./output/
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--input, -i` | (required) | Input directory containing PDF files |
| `--output, -o` | (required) | Output directory for results |
| `--threshold` | 30 | Pixel darkness threshold (0-255). Values below this are considered redaction. |
| `--min-aspect-ratio` | 3.0 | Minimum width/height ratio for redaction bars |
| `--border-padding` | 50 | Padding in pixels for context crop images |
| `--workers` | 4 | Number of parallel worker processes |
| `--dpi` | 150 | Render DPI for pixel-level detection |
| `--verbose, -v` | False | Enable verbose output |

### Examples

Basic usage:
```bash
python extract.py -i ./documents/ -o ./results/
```

Adjust threshold for lighter redactions:
```bash
python extract.py -i ./documents/ -o ./results/ --threshold 50
```

Process with more workers:
```bash
python extract.py -i ./documents/ -o ./results/ --workers 8
```

## Output Files

- `catalogue.json` - Full structured data for all redactions
- `catalogue.csv` - Flat CSV format for analysis
- `summary.json` - Aggregate statistics
- `images/` - Cropped redaction images
  - `{doc_id}_p{page}_r{index}_tight.png` - Exact redaction crop
  - `{doc_id}_p{page}_r{index}_context.png` - Crop with padding

## Detection Methods

### PyMuPDF Extraction
Extracts redactions from PDF structure:
- Redact annotations (PDF_ANNOT_REDACT)
- Rectangle annotations with dark fill
- Drawing commands (filled rectangles)

### OpenCV Pixel Detection
Detects black bars at pixel level:
1. Render page to image
2. Threshold for dark pixels
3. Find contours
4. Filter by aspect ratio

Results from both methods are cross-referenced and merged.

## License

MIT
