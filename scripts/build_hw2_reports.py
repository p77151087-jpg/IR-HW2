"""Export the reviewed Markdown and exact experiment figures as two PDFs.

Requires reportlab + pypdf; Poppler is used separately for visual QA. Windows
Microsoft JhengHei fonts are embedded, with Segoe UI for missing math glyphs.
Run from any working directory: python scripts/build_hw2_reports.py
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
INK = colors.HexColor('#183143')
TEAL = colors.HexColor('#087F8C')
LIGHT = colors.HexColor('#EDF5F6')
GREY = colors.HexColor('#536774')
DASHES = str.maketrans({'‐': '-', '‑': '-', '‒': '-', '–': '-', '—': '-', '−': '-', '’': "'", '‘': "'"})
WIDTH, HEIGHT = A4
MARGIN = 43
# SimpleDocTemplate's frame also has six points of inner padding per side.
CONTENT_WIDTH = WIDTH - 2 * MARGIN - 12
CONTENT_HEIGHT = HEIGHT - 94 - 12


def register_fonts(font_dir: Path) -> None:
    for name, filename in [('CJK', 'msjh.ttc'), ('CJK-Bold', 'msjhbd.ttc'),
                           ('Symbols', 'segoeui.ttf')]:
        path = font_dir / filename
        if not path.exists():
            raise FileNotFoundError(f'Required font missing: {path}; use --font-dir')
        pdfmetrics.registerFont(TTFont(name, str(path), subfontIndex=0))
    pdfmetrics.registerFontFamily('CJK', normal='CJK', bold='CJK-Bold', italic='CJK', boldItalic='CJK-Bold')


def escape_text(value: str) -> str:
    """Preserve source characters, using an explicit fallback when required."""
    value = value.translate(DASHES)
    cmap = pdfmetrics.getFont('CJK').face.charWidths
    fallback = pdfmetrics.getFont('Symbols').face.charWidths
    parts = []
    for char in value:
        escaped = html.escape(char)
        if ord(char) in cmap or char.isspace():
            parts.append(escaped)
        elif ord(char) in fallback:
            parts.append(f'<font name="Symbols">{escaped}</font>')
        else:
            raise ValueError(f'Unrenderable character: {char!r} U+{ord(char):04X}')
    return ''.join(parts)


def inline(value: str) -> str:
    parts = []
    pattern = re.compile(r'(`[^`]+`|\*\*.+?\*\*|\[[^\]]+\]\([^\)]+\))')
    cursor = 0
    for match in pattern.finditer(value):
        parts.append(escape_text(value[cursor:match.start()]))
        token = match.group()
        if token.startswith('`'):
            parts.append(f'<font color="#3E606E">{escape_text(token[1:-1])}</font>')
        elif token.startswith('**'):
            parts.append(f'<b>{escape_text(token[2:-2])}</b>')
        else:
            link = re.fullmatch(r'\[([^\]]+)\]\(([^\)]+)\)', token)
            label, url = link.groups()
            if url.startswith(('https://', 'http://')):
                parts.append(f'<link href="{html.escape(url, quote=True)}" color="#087F8C">{escape_text(label)}</link>')
            else:
                # Local source paths remain in the companion Markdown and in
                # the deliverable location table, without machine-bound links.
                parts.append(f'<font color="#087F8C">{escape_text(label)}</font>')
        cursor = match.end()
    parts.append(escape_text(value[cursor:]))
    return ''.join(parts)


def styles(summary: bool = False) -> dict[str, ParagraphStyle]:
    body_size, leading = (9.05, 13.5) if summary else (9.5, 15.0)
    common = dict(fontName='CJK', textColor=INK, wordWrap='CJK', alignment=TA_LEFT,
                  splitLongWords=True, allowWidows=0, allowOrphans=0)
    return {
        'body': ParagraphStyle('Body', fontSize=body_size, leading=leading, spaceAfter=6 if summary else 8, **common),
        'english': ParagraphStyle('English', fontName='CJK', fontSize=body_size, leading=leading,
                                  textColor=INK, spaceAfter=8, wordWrap=None, splitLongWords=False),
        'title': ParagraphStyle('Title', fontSize=21 if summary else 20, leading=27, spaceAfter=12,
                                fontName='CJK-Bold', textColor=INK, wordWrap='CJK', keepWithNext=True),
        'h2': ParagraphStyle('Heading2', fontSize=12 if summary else 13.5, leading=19, spaceBefore=7 if summary else 16,
                             spaceAfter=7, fontName='CJK-Bold', textColor=TEAL, wordWrap='CJK', keepWithNext=True),
        'h3': ParagraphStyle('Heading3', fontSize=11, leading=16, spaceBefore=11, spaceAfter=7,
                             fontName='CJK-Bold', textColor=TEAL, wordWrap='CJK', keepWithNext=True),
        'cell': ParagraphStyle('Cell', fontSize=8.2 if summary else 8.1, leading=11.5,
                              spaceAfter=0, **common),
        'cell_small': ParagraphStyle('CellSmall', fontSize=7.4, leading=10.5, spaceAfter=0, **common),
        'header': ParagraphStyle('HeaderCell', fontSize=8.2 if summary else 8.1, leading=11.8,
                                fontName='CJK-Bold', textColor=INK, wordWrap='CJK'),
        'code': ParagraphStyle('Code', fontSize=8.0, leading=12, leftIndent=8,
                              rightIndent=8, spaceAfter=2, **common),
        'caption': ParagraphStyle('Caption', fontSize=8.4, leading=12.5, textColor=GREY,
                                 fontName='CJK', wordWrap='CJK', spaceBefore=6, spaceAfter=10),
        'small': ParagraphStyle('Small', fontSize=7.5, leading=11.3, textColor=GREY,
                               fontName='CJK', wordWrap='CJK', spaceAfter=0),
    }


def table_widths(rows: list[list[str]]) -> list[float]:
    count = len(rows[0])
    if count == 9:
        weights = [0.7, 1.02, 1.04, 1.10, 1.22, 0.98, 1.02, 1.12, 1.02]
    elif count == 8:
        weights = [1.03, 1.60, 0.82, 1.09, 1.22, 1.18, 1.06, 1.20]
    elif count == 5:
        weights = [0.6, 1.05, 1.1, 1.35, 1.0]
    elif count == 6 and rows[0] == ['Rank', 'Term', 'CF', 'Rank', 'Term', 'CF']:
        weights = [0.45, 1.65, 0.8, 0.45, 1.65, 0.8]
    elif count == 4:
        weights = [0.9, 1.45, 1.45, 1.45] if '鄰近詞' in ''.join(rows[0]) else [1.6, 1.0, 1.0, 1.8]
    elif count == 2:
        weights = [1.4, 3.5] if '條件' in rows[0][0] else [2.0, 3.0]
    else:
        weights = [1.0] * count
    return [CONTENT_WIDTH * weight / sum(weights) for weight in weights]


def markdown_table(lines: list[str], style: dict, audit: dict, heading: Flowable | None = None) -> KeepTogether:
    raw_rows = [[cell.strip() for cell in line.strip().strip('|').split('|')] for line in lines]
    rows = [row for row in raw_rows if not all(re.fullmatch(r':?-+:?', cell.replace(' ', '')) for cell in row)]
    assert all(len(row) == len(rows[0]) for row in rows), 'Malformed Markdown table'
    table_style = style['cell_small'] if len(rows[0]) >= 8 else style['cell']
    cells = [[Paragraph(inline(cell).replace('Unique terms', 'Unique<br/>terms'), style['header'] if index == 0 else table_style)
              for cell in row] for index, row in enumerate(rows)]
    table = Table(cells, colWidths=table_widths(rows), repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), LIGHT),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFB')]),
        ('LINEBELOW', (0, 0), (-1, 0), 0.7, TEAL),
        ('LINEBELOW', (0, -1), (-1, -1), 0.5, colors.HexColor('#CBDBE1')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    width, height = table.wrap(CONTENT_WIDTH, CONTENT_HEIGHT)
    if height > CONTENT_HEIGHT - 20:
        raise ValueError(f'Table too tall to keep on one page: {height:.1f} points')
    audit['tables'].append({'columns': len(rows[0]), 'rows': len(rows), 'height_points': height,
                            'header': rows[0], 'kept_on_one_page': True})
    # A separate KeepTogether table does not reliably inherit the preceding
    # heading's keepWithNext. Bind them explicitly to avoid orphan headings.
    prefix = [heading] if heading is not None else []
    return KeepTogether([*prefix, Spacer(1, 3), table, Spacer(1, 10)])


def parse_markdown(source: Path, summary: bool, audit: dict) -> list[Flowable]:
    text = source.read_text(encoding='utf-8-sig')
    audit['source'] = str(source)
    audit['source_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    style = styles(summary)
    lines = text.splitlines()
    story = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line or line.startswith('<!--'):
            index += 1
            continue
        if line.startswith('```'):
            block = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith('```'):
                block.append(Paragraph(escape_text(lines[index]).replace(' ', '&#160;'), style['code']))
                index += 1
            if block:
                box = Table([[item] for item in block], colWidths=[CONTENT_WIDTH])
                box.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), LIGHT),
                                        ('BOX', (0, 0), (-1, -1), 0.4, colors.HexColor('#CBDBE1')),
                                        ('TOPPADDING', (0, 0), (-1, -1), 4),
                                        ('BOTTOMPADDING', (0, 0), (-1, -1), 4)]))
                story.append(KeepTogether([box, Spacer(1, 9)]))
            index += 1
            continue
        if line.startswith('|'):
            table_lines = []
            while index < len(lines) and lines[index].strip().startswith('|'):
                table_lines.append(lines[index])
                index += 1
            heading = None
            if story and isinstance(story[-1], Paragraph) and getattr(story[-1].style, 'keepWithNext', False):
                heading = story.pop()
            story.append(markdown_table(table_lines, style, audit, heading))
            continue
        image_match = re.fullmatch(r'!\[([^\]]*)\]\((.+)\)', line)
        if image_match:
            label, filename = image_match.groups()
            image_path = Path(filename)
            if not image_path.is_absolute():
                image_path = source.parent / image_path
            figure = Image(str(image_path))
            ratio = figure.imageHeight / figure.imageWidth
            figure.drawWidth = CONTENT_WIDTH
            figure.drawHeight = CONTENT_WIDTH * ratio
            figure.hAlign = 'CENTER'
            story.append(KeepTogether([Spacer(1, 7), figure, Paragraph(inline(label), style['caption'])]))
            audit['figures'].append({'source': str(image_path), 'sha256': hashlib.sha256(image_path.read_bytes()).hexdigest(), 'caption': label})
            index += 1
            continue
        heading = re.match(r'^(#{1,3})\s+(.+)$', line)
        if heading:
            level, value = len(heading.group(1)), heading.group(2)
            if value.startswith('English discussion:'):
                # Keep the entire required discussion together and
                # use English word wrapping so words/spaces stay intact.
                discussion = [Paragraph(inline(value), style['h3'])]
                index += 1
                english_lines = []
                while index < len(lines) and 'IR_ENGLISH_END' not in lines[index]:
                    if not lines[index].strip().startswith('<!--'):
                        english_lines.append(lines[index])
                    index += 1
                for paragraph in '\n'.join(english_lines).strip().split('\n\n'):
                    if paragraph.strip():
                        discussion.append(Paragraph(inline(' '.join(paragraph.splitlines())), style['english']))
                index += 1
                while index < len(lines) and not lines[index].strip():
                    index += 1
                if index < len(lines) and lines[index].startswith('英文段落'):
                    discussion.append(Paragraph(inline(lines[index]), style['body']))
                    index += 1
                story.append(KeepTogether(discussion))
                continue
            story.append(Paragraph(inline(value), style[{1: 'title', 2: 'h2', 3: 'h3'}[level]]))
            index += 1
            continue
        paragraph = [line]
        index += 1
        while index < len(lines) and lines[index].strip() and not re.match(r'^(#|\||```|!\[|<!--)', lines[index].strip()):
            # Numbered reference items remain separate paragraphs.
            if re.match(r'^\d+\.\s', lines[index].strip()):
                break
            paragraph.append(lines[index].strip())
            index += 1
        paragraph_text = ' '.join(paragraph)
        paragraph_style = style['small'] if summary and paragraph_text.startswith('來源：') else style['body']
        story.append(Paragraph(inline(paragraph_text), paragraph_style))
    return story


def page_furniture(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(TEAL)
    canvas.setLineWidth(0.8)
    canvas.line(MARGIN, HEIGHT - 30, WIDTH - MARGIN, HEIGHT - 30)
    canvas.setFont('Helvetica', 7.7)
    canvas.setFillColor(GREY)
    canvas.drawString(MARGIN, HEIGHT - 23, 'INFORMATION RETRIEVAL / HOMEWORK 2')
    canvas.drawRightString(WIDTH - MARGIN, HEIGHT - 23, 'GLP-1 / 1,000 PUBMED ABSTRACTS')
    canvas.setFont('CJK', 7.3)
    canvas.drawString(MARGIN, 24, '固定語料 2026-09-29 / HW1 切詞更新 2026-09-30')
    canvas.drawRightString(WIDTH - MARGIN, 24, str(doc.page))
    canvas.restoreState()


def build(source: Path, output: Path, summary: bool) -> dict:
    audit = {'tables': [], 'figures': []}
    story = parse_markdown(source, summary, audit)
    document = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=MARGIN,
                                 leftMargin=MARGIN, topMargin=44, bottomMargin=50,
                                 pageCompression=1, title='HW2 Executive Summary' if summary else 'Biomedical IR Homework 2',
                                 author='IR Homework 2 project', subject='Reproducible PubMed GLP-1 abstract analysis')
    document.build(story, onFirstPage=page_furniture, onLaterPages=page_furniture)
    reader = PdfReader(output)
    audit['pages'] = len(reader.pages)
    audit['output'] = str(output)
    audit['pdf_sha256'] = hashlib.sha256(output.read_bytes()).hexdigest()
    audit['page_text_characters'] = [len(page.extract_text()) for page in reader.pages]
    if summary and len(reader.pages) != 1:
        raise ValueError(f'Executive Summary must be one page, got {len(reader.pages)}')
    extracted = '\n'.join(page.extract_text() for page in reader.pages)
    if not summary:
        source_text = source.read_text(encoding='utf-8')
        discussion = source_text.split('<!-- IR_ENGLISH_START -->')[1].split('<!-- IR_ENGLISH_END -->')[0].strip()
        word_count = len(discussion.split())
        assert 300 <= word_count <= 500, 'Required English discussion must contain 300–500 words'
        requirements = ['RQ1', 'RQ2', 'RQ3', 'RQ4', 'RQ5', f'{word_count} words', 'Word2Vec', 'log(CF)']
        requirements.extend(re.findall(r'\b\d+ passed\b', source_text))
        for requirement in requirements:
            if re.sub(r'\s+', '', requirement) not in re.sub(r'\s+', '', extracted):
                raise ValueError(f'Missing required content after PDF export: {requirement}')
        expected_figures = {'preprocessing_comparison.png', 'rank_frequency.png', 'log_log.png', 'residuals.png',
                            'high_frequency_terms.png', 'segment_fit.png', 'cf_df.png', 'idf_relation.png', 'idf_terms.png'}
        assert len(audit['figures']) == len(expected_figures)
        assert {Path(row['source']).name for row in audit['figures']} == expected_figures
    audit['text_completeness_checks'] = 'passed'
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font-dir', type=Path, default=Path('C:/Windows/Fonts'))
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'output/pdf')
    args = parser.parse_args()
    register_fonts(args.font_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = [build(ROOT / 'reports/hw2/HW2_REPORT.md', args.output_dir / 'HW2_REPORT.pdf', False),
               build(ROOT / 'reports/hw2/EXECUTIVE_SUMMARY.md', args.output_dir / 'HW2_EXECUTIVE_SUMMARY.pdf', True)]
    evidence = {'generator': 'ReportLab with embedded Microsoft JhengHei and Segoe UI',
                'dash_policy': 'Unicode dash variants displayed as ASCII hyphens; curly apostrophes as ASCII apostrophes; source Markdown preserved.',
                'outputs': outputs, 'visual_qa': 'Required after generation; inspect Poppler-rendered pages.'}
    (ROOT / 'reports/hw2/pdf_export.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'outputs': [{'path': row['output'], 'pages': row['pages']} for row in outputs]}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
