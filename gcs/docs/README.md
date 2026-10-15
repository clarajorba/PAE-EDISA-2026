# docs/ — Documentation

| File | Description |
|---|---|
| `Drone_GCS_Manual.pdf` | Full technical manual — architecture, setup, configuration, troubleshooting |
| `Drone_GCS_Presentation.pptx` | 8-slide client presentation deck with live app screenshots |
| `Drone_GCS_Script.docx` | Presenter script for the client demo |
| `generate_report.py` | Python script that generates the PDF manual via ReportLab |
| `assets/` | Screenshots used in READMEs and presentations |

## Regenerate the PDF manual

```bash
pip install reportlab
python generate_report.py
# Output: Drone_GCS_Manual.pdf
```

## Regenerate the presentation

```bash
cd docs
npm install
node make_presentation.js
# Output: Drone_GCS_Presentation.pptx
```
