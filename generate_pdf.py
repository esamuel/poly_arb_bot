#!/usr/bin/env python3
"""Generate a styled PDF from BOT_GUIDE.md using fpdf2."""
import os
import re
from fpdf import FPDF

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_FILE = os.path.join(SCRIPT_DIR, "Bot_Guide.pdf")


def sanitize(text):
    """Replace unicode chars that core fonts can't handle."""
    replacements = {
        "\u2192": "->",   # →
        "\u2190": "<-",   # ←
        "\u2194": "<->",  # ↔
        "\u2713": "[ok]", # ✓
        "\u2714": "[ok]", # ✔
        "\u2717": "[x]",  # ✗
        "\u2718": "[x]",  # ✘
        "\u2022": "-",    # •
        "\u2026": "...",  # …
        "\u201c": '"',    # "
        "\u201d": '"',    # "
        "\u2018": "'",    # '
        "\u2019": "'",    # '
        "\u2013": "-",    # –
        "\u2014": "--",   # —
        "\u2660": "*",    # ♠
        "\u2665": "*",    # ♥
        "\u266b": "*",    # ♫
        "\u2642": "",     # ♂
        "\u267b": "[R]",  # ♻
        "\U0001f4b0": "$",  # 💰
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    # Strip any remaining non-latin-1 characters
    return text.encode("latin-1", errors="replace").decode("latin-1")


class BotGuidePDF(FPDF):
    DARK_BLUE = (15, 52, 96)
    MID_BLUE = (22, 33, 62)
    TEXT_COLOR = (26, 26, 46)
    LIGHT_BG = (248, 249, 250)
    CODE_BG = (30, 30, 46)
    CODE_FG = (205, 214, 244)
    TABLE_HEADER = (15, 52, 96)
    TABLE_BORDER = (224, 224, 224)
    ACCENT = (0, 150, 136)

    def header(self):
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(150, 150, 150)
            self.cell(0, 8, "Polymarket Arbitrage Bot - Guide", align="C")
            self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, "Samuel Eskenasy  |  All Rights Reserved", align="L")
        self.set_x(self.l_margin)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="R")

    def title_page(self):
        self.add_page()
        self.ln(50)
        self.set_font("Helvetica", "B", 32)
        self.set_text_color(*self.DARK_BLUE)
        self.cell(0, 16, "Polymarket Arbitrage Bot", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(8)
        self.set_draw_color(*self.DARK_BLUE)
        self.set_line_width(1)
        x = 50
        self.line(x, self.get_y(), self.w - x, self.get_y())
        self.ln(12)
        self.set_font("Helvetica", "", 18)
        self.set_text_color(*self.MID_BLUE)
        self.cell(0, 12, "Complete Guide", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(30)
        self.set_font("Helvetica", "", 11)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, "Auto-start | Position Recycler | Failover | Dashboard", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(20)
        self.set_draw_color(180, 180, 180)
        self.set_line_width(0.3)
        x = 60
        self.line(x, self.get_y(), self.w - x, self.get_y())
        self.ln(10)
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(*self.DARK_BLUE)
        self.cell(0, 8, "Samuel Eskenasy", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(3)
        self.set_font("Helvetica", "I", 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 7, "Creator & Owner", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(3)
        self.set_font("Helvetica", "", 9)
        self.cell(0, 7, "All Rights Reserved  |  February 2026", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(15)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(140, 140, 140)
        self.cell(0, 6, "This document and the software it describes are the intellectual property", align="C", new_x="LMARGIN", new_y="NEXT")
        self.cell(0, 6, "of Samuel Eskenasy. Unauthorized reproduction or distribution is prohibited.", align="C", new_x="LMARGIN", new_y="NEXT")

    def section_heading(self, text):
        self.ln(6)
        self.set_font("Helvetica", "B", 17)
        self.set_text_color(*self.DARK_BLUE)
        self.cell(0, 10, sanitize(text), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*self.DARK_BLUE)
        self.set_line_width(0.6)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(5)

    def sub_heading(self, text):
        self.ln(4)
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(*self.MID_BLUE)
        self.cell(0, 8, sanitize(text), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*self.TABLE_BORDER)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def sub_sub_heading(self, text):
        self.ln(3)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*self.TEXT_COLOR)
        self.cell(0, 7, sanitize(text), new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def body_text(self, text):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*self.TEXT_COLOR)
        self.multi_cell(0, 5.5, sanitize(text))
        self.ln(2)

    def bold_text(self, text):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*self.DARK_BLUE)
        self.multi_cell(0, 5.5, sanitize(text))
        self.ln(1)

    def code_block(self, code):
        self.ln(2)
        self.set_fill_color(*self.CODE_BG)
        self.set_text_color(*self.CODE_FG)
        self.set_font("Courier", "", 8.5)
        lines = code.strip().split("\n")
        block_h = len(lines) * 4.5 + 8
        if self.get_y() + block_h > self.h - 20:
            self.add_page()
        y_start = self.get_y()
        self.rect(self.l_margin, y_start, self.w - self.l_margin - self.r_margin, block_h, "F")
        self.set_xy(self.l_margin + 5, y_start + 4)
        for line in lines:
            self.cell(0, 4.5, sanitize(line), new_x="LMARGIN", new_y="NEXT")
            self.set_x(self.l_margin + 5)
        self.set_y(y_start + block_h + 2)
        self.ln(2)

    def table(self, headers, rows):
        self.ln(2)
        col_count = len(headers)
        avail_w = self.w - self.l_margin - self.r_margin

        # Auto-size columns based on content
        col_widths = []
        for i in range(col_count):
            max_len = len(headers[i])
            for row in rows:
                if i < len(row):
                    max_len = max(max_len, len(row[i]))
            col_widths.append(max_len)
        total = sum(col_widths)
        col_widths = [(w / total) * avail_w for w in col_widths]
        # Ensure minimum width
        col_widths = [max(w, 18) for w in col_widths]
        # Normalize
        total = sum(col_widths)
        col_widths = [(w / total) * avail_w for w in col_widths]

        # Check if table fits on page
        table_h = (len(rows) + 1) * 7
        if self.get_y() + table_h > self.h - 20:
            self.add_page()

        # Header
        self.set_fill_color(*self.TABLE_HEADER)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 9)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 7, sanitize(h[:30]), border=1, fill=True, align="C")
        self.ln()

        # Rows
        self.set_font("Helvetica", "", 9)
        for ri, row in enumerate(rows):
            if ri % 2 == 0:
                self.set_fill_color(255, 255, 255)
            else:
                self.set_fill_color(*self.LIGHT_BG)
            self.set_text_color(*self.TEXT_COLOR)
            for i in range(col_count):
                val = row[i] if i < len(row) else ""
                self.cell(col_widths[i], 6.5, sanitize(val[:40]), border="LRB", fill=True)
            self.ln()
        self.ln(3)

    def bullet(self, text, indent=0):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*self.TEXT_COLOR)
        x = self.l_margin + 4 + indent
        self.set_x(x)
        self.cell(4, 5.5, "-")
        self.multi_cell(0, 5.5, sanitize(text))
        self.ln(1)

    def numbered(self, num, text):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*self.ACCENT)
        self.set_x(self.l_margin + 4)
        self.cell(8, 5.5, f"{num}.")
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*self.TEXT_COLOR)
        self.multi_cell(0, 5.5, sanitize(text))
        self.ln(1)


def parse_and_generate():
    pdf = BotGuidePDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)

    # Title page
    pdf.title_page()

    # Read markdown
    with open(os.path.join(SCRIPT_DIR, "BOT_GUIDE.md"), "r") as f:
        lines = f.readlines()

    i = 0
    in_code = False
    code_buf = []
    in_table = False
    table_headers = []
    table_rows = []

    while i < len(lines):
        line = lines[i].rstrip("\n")

        # Code blocks
        if line.startswith("```"):
            if in_code:
                pdf.code_block("\n".join(code_buf))
                code_buf = []
                in_code = False
            else:
                # Flush table if pending
                if in_table:
                    pdf.table(table_headers, table_rows)
                    in_table = False
                    table_headers = []
                    table_rows = []
                in_code = True
            i += 1
            continue

        if in_code:
            code_buf.append(line)
            i += 1
            continue

        # Table rows
        if "|" in line and line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            # Check if separator row
            if all(re.match(r"^[-:]+$", c) for c in cells):
                i += 1
                continue
            if not in_table:
                table_headers = cells
                in_table = True
            else:
                table_rows.append(cells)
            i += 1
            continue
        else:
            if in_table:
                pdf.table(table_headers, table_rows)
                in_table = False
                table_headers = []
                table_rows = []

        # Skip the main title (already on cover page)
        if line.startswith("# ") and "Complete Guide" in line:
            i += 1
            continue

        # Headings
        if line.startswith("## "):
            text = line[3:].strip()
            pdf.section_heading(text)
            i += 1
            continue
        if line.startswith("### "):
            text = line[4:].strip()
            pdf.sub_heading(text)
            i += 1
            continue
        if line.startswith("#### "):
            text = line[5:].strip()
            pdf.sub_sub_heading(text)
            i += 1
            continue
        if line.startswith("# "):
            text = line[2:].strip()
            pdf.add_page()
            pdf.section_heading(text)
            i += 1
            continue

        # Horizontal rule
        if line.strip() == "---":
            pdf.ln(3)
            i += 1
            continue

        # Bullet points
        if line.strip().startswith("- ") or line.strip().startswith("* "):
            text = re.sub(r"^[\s]*[-*]\s+", "", line)
            text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)  # strip bold markers
            text = re.sub(r"`(.*?)`", r"\1", text)  # strip code markers
            indent = len(line) - len(line.lstrip())
            pdf.bullet(text, indent=indent * 2)
            i += 1
            continue

        # Numbered lists
        m = re.match(r"^(\d+)\.\s+(.*)", line.strip())
        if m:
            text = re.sub(r"\*\*(.*?)\*\*", r"\1", m.group(2))
            text = re.sub(r"`(.*?)`", r"\1", text)
            pdf.numbered(m.group(1), text)
            i += 1
            continue

        # Bold lines
        if line.strip().startswith("**") and line.strip().endswith("**"):
            text = line.strip().strip("*")
            pdf.bold_text(text)
            i += 1
            continue

        # Empty lines
        if not line.strip():
            i += 1
            continue

        # Regular text
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
        text = re.sub(r"`(.*?)`", r"\1", text)
        pdf.body_text(text)
        i += 1

    # Flush remaining table
    if in_table:
        pdf.table(table_headers, table_rows)

    pdf.output(PDF_FILE)
    print(f"PDF generated: {PDF_FILE}")


if __name__ == "__main__":
    parse_and_generate()
