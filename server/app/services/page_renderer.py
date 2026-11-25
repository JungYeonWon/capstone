"""Paginated PDF projection preserving document table geometry and typography."""
import html
import re
from io import BytesIO

from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.utils import ImageReader


class SealParagraph(Paragraph):
    """Draw the seal first so the signature text stays in front."""
    def draw(self):
        data, width, height = self.seal
        x = self.width - self.style.rightIndent - 17.5 / 2 - width / 2
        y = (self.style.leading - height) / 2
        self.canv.drawImage(ImageReader(BytesIO(data)), x, y, width, height, mask='auto')
        super().draw()


def render_pdf(doc, font):
    section = doc.sections[0]
    width = section.page_width.pt - section.left_margin.pt - section.right_margin.pt
    story = []

    def paragraph(p, name="body", cell=False):
        size = next((r.font.size.pt for r in p.runs if r.font.size), 11)
        align = {1: 1, 2: 2}.get(p.alignment, 0)
        fmt = p.paragraph_format
        style = ParagraphStyle(name, fontName=font, fontSize=size, leading=size * 1.5,
                               alignment=align, wordWrap="CJK",
                               spaceAfter=0 if cell else (fmt.space_after.pt if fmt.space_after else 6),
                               spaceBefore=0 if cell else (fmt.space_before.pt if fmt.space_before else 0),
                               keepWithNext=bool(fmt.keep_with_next))
        style.splitLongWords = True
        style.allowWidows = 0
        style.allowOrphans = 0
        style.leftIndent = fmt.left_indent.pt if fmt.left_indent else 0
        style.rightIndent = fmt.right_indent.pt if fmt.right_indent else 0
        content = []
        for run in p.runs:
            text = html.escape(run.text).replace("\n", "<br/>")
            text = re.sub(r' {2,}', lambda match: '&#160;' * len(match.group()), text)
            if run.bold:
                text = f"<b>{text}</b>"
            content.append(text)
        anchors = p._p.xpath('.//wp:anchor[wp:docPr[@name="CompanySeal"]]')
        if anchors:
            anchor = anchors[0]
            extent = anchor.find(qn('wp:extent'))
            blip = anchor.find('.//' + qn('a:blip'))
            data = p.part.related_parts[blip.get(qn('r:embed'))].blob
            result = SealParagraph(''.join(content) or '&#160;', style)
            result.seal = (data, int(extent.get('cx')) / 12700, int(extent.get('cy')) / 12700)
            return result
        return Paragraph("".join(content) or "&#160;", style)

    for element in doc.element.body.iterchildren():
        if element.tag == qn("w:p"):
            p = DocxParagraph(element, doc)
            if element.xpath('.//w:br[@w:type="page"]') or p.paragraph_format.page_break_before:
                story.append(PageBreak())
            if p.text.strip():
                story.append(paragraph(p))
            elif not element.xpath('.//w:br[@w:type="page"]'):
                story.append(Spacer(1, p.paragraph_format.space_after.pt if p.paragraph_format.space_after else 5))
        elif element.tag == qn("w:tbl"):
            source = DocxTable(element, doc)
            widths = [c.width.pt if c.width else 1 for c in source.columns]
            scale = width / sum(widths)
            widths = [w * scale for w in widths]
            rows, heights, spans = [], [], []
            oversized_row = False
            page_body_height = section.page_height.pt - section.top_margin.pt - section.bottom_margin.pt
            commands = [("GRID", (0, 0), (-1, -1), .45, colors.HexColor("#444444")),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]
            for ri, row in enumerate(source.rows):
                data, ci = [], 0
                while ci < len(row.cells):
                    cell = row.cells[ci]
                    end = ci
                    while end + 1 < len(row.cells) and row.cells[end + 1]._tc is cell._tc:
                        end += 1
                    paragraphs = [paragraph(p, "cell", True) for p in cell.paragraphs]
                    cell_width = max(1, sum(widths[ci:end + 1]) - 16)
                    content_height = sum(item.wrap(cell_width, page_body_height)[1] for item in paragraphs) + 14
                    if content_height > page_body_height - 45:
                        oversized_row = True
                    data.append(paragraphs)
                    data.extend([""] * (end - ci))
                    if end > ci:
                        spans.append(("SPAN", (ci, ri), (end, ri)))
                    shading = cell._tc.xpath("./w:tcPr/w:shd")
                    if shading:
                        fill = shading[0].get(qn("w:fill"))
                        if fill and fill != "auto":
                            commands.append(("BACKGROUND", (ci, ri), (end, ri), colors.HexColor("#" + fill)))
                    ci = end + 1
                rows.append(data)
                heights.append(row.height.pt if row.height else 0)
            repeat = 0
            for row in source.rows:
                if not row._tr.xpath("./w:trPr/w:tblHeader"):
                    break
                repeat += 1
            table = Table(rows, colWidths=widths, minRowHeights=heights, repeatRows=repeat,
                          hAlign="CENTER", splitInRow=int(oversized_row))
            table.setStyle(TableStyle(commands + spans))
            story.extend([table, Spacer(1, 8)])

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.drawCentredString(section.page_width.pt / 2, 28, f"- {document.page} -")
        canvas.restoreState()

    out = BytesIO()
    document = BaseDocTemplate(out, pagesize=(section.page_width.pt, section.page_height.pt),
                               title=doc.core_properties.title or "계약 제출서류")
    frame = Frame(section.left_margin.pt, section.bottom_margin.pt, width,
                  section.page_height.pt - section.top_margin.pt - section.bottom_margin.pt,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    document.addPageTemplates(PageTemplate(id="document", frames=[frame], onPage=footer))
    document.build(story)
    return out.getvalue()
