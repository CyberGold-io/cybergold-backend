"""Render the three editable process diagrams as the linked A4 PDF.

Authoring dependencies: reportlab and svglib (not serving dependencies).
"""
from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from reportlab.graphics import renderPDF
from svglib.svglib import svg2rlg

root = Path(__file__).resolve().parents[2]
output = root / 'output/pdf/quoter-current-process.pdf'
output.parent.mkdir(parents=True, exist_ok=True)
page = landscape(A4)
document = canvas.Canvas(str(output), pagesize=page, invariant=True)
document.setTitle('CyberGold current quote process')
for path in sorted((root / 'docs/specs/diagrams').glob('*.svg')):
    drawing = svg2rlg(str(path))
    document.saveState()
    document.scale(page[0] / drawing.width, page[1] / drawing.height)
    renderPDF.draw(drawing, document, 0, 0)
    document.restoreState()
    document.showPage()
document.save()
