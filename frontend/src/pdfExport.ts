import jsPDF from 'jspdf';
import autoTable, { type CellHookData } from 'jspdf-autotable';
import { marked, type Token, type Tokens } from 'marked';
import { type Message } from './App';

interface TextSegment {
  text: string;
  bold: boolean;
  italic: boolean;
  code: boolean;
  link?: string;
}

// Several marked token variants expose `text`/`tokens` that aren't on the base
// Token union; these narrow shapes let us read them without resorting to `any`.
type MaybeText = { text?: string };
type MaybeTokens = { tokens?: Token[] };

// Matches emoji & symbol Unicode ranges that jsPDF's built-in fonts can't render.
// Only removes the emoji codepoints themselves — never touches whitespace or structure.
const EMOJI_RE = /[\u2700-\u27BF\u{1F000}-\u{1FAFF}\u{FE00}-\u{FE0F}\u{200D}\u{20E3}\u{E0020}-\u{E007F}]/gu;

function stripEmojis(text: string): string {
  return text.replace(EMOJI_RE, '');
}

/** Recursively extract plain text from inline tokens, stripping all markdown syntax. */
function extractTokenText(tokens: Token[]): string {
  let result = '';
  for (const t of tokens) {
    const nested = (t as MaybeTokens).tokens;
    if (Array.isArray(nested) && nested.length > 0) {
      result += extractTokenText(nested);
    } else if ('text' in t) {
      result += (t as MaybeText).text ?? '';
    }
  }
  return stripEmojis(result);
}

// ---------- Public API ----------

export async function exportMessageToPDF(message: Message, messageIndex: number, conversationTitle?: string): Promise<void> {
  const renderer = new PDFRenderer();

  if (message.content?.trim()) {
    renderer.addMarkdown(message.content);
  }

  const slug = conversationTitle
    ? conversationTitle.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60)
    : `chat-response-${messageIndex}`;
  renderer.save(slug);
}

// ---------- Renderer ----------

class PDFRenderer {
  private pdf: jsPDF;
  private y: number;

  private readonly margin = 15;
  private readonly pageW = 210;
  private readonly pageH = 297;
  private readonly cw: number;
  private readonly bodySize = 11;

  constructor() {
    this.pdf = new jsPDF('p', 'mm', 'a4');
    this.cw = this.pageW - 2 * this.margin;
    this.y = this.margin;
  }

  // --- helpers ---

  private lh(fontSize: number) { return fontSize * 0.5; }

  private ensureSpace(h: number) {
    if (this.y + h > this.pageH - this.margin) {
      this.pdf.addPage();
      this.y = this.margin;
    }
  }

  private setColor(r: number, g: number, b: number) {
    this.pdf.setTextColor(r, g, b);
  }

  // ===================== Markdown =====================

  addMarkdown(md: string) {
    this.renderTokens(marked.lexer(md));
  }

  private renderTokens(tokens: Token[]) {
    for (const t of tokens) {
      switch (t.type) {
        case 'heading':    this.renderHeading(t as Tokens.Heading); break;
        case 'paragraph':  this.renderParagraph(t as Tokens.Paragraph); break;
        case 'list':       this.renderList(t as Tokens.List, 0); break;
        case 'table':      this.renderMarkdownTable(t as Tokens.Table); break;
        case 'code':       this.renderCode(t as Tokens.Code); break;
        case 'blockquote': this.renderBlockquote(t as Tokens.Blockquote); break;
        case 'hr':         this.renderHR(); break;
        case 'space':      this.y += 2; break;
        case 'html': {
          const raw = ((t as MaybeText).text || '').replace(/<[^>]*>/g, '').trim();
          if (raw) this.renderPlainText(raw, this.bodySize);
          break;
        }
        case 'text': {
          const tt = t as Tokens.Text;
          if (tt.tokens && tt.tokens.length > 0) {
            this.renderInline(tt.tokens, this.margin, this.cw, this.bodySize);
          } else {
            this.renderPlainText(tt.text, this.bodySize);
          }
          break;
        }
      }
    }
  }

  // ---- block elements ----

  private renderHeading(t: Tokens.Heading) {
    const sizes: Record<number, number> = { 1: 18, 2: 16, 3: 14, 4: 12, 5: 11, 6: 11 };
    const fs = sizes[t.depth] || 12;

    this.y += t.depth <= 2 ? 6 : 4;
    this.ensureSpace(this.lh(fs) + 6);
    this.renderInline(t.tokens || [], this.margin, this.cw, fs, true);

    if (t.depth <= 2) {
      this.pdf.setDrawColor(229, 231, 235);
      this.pdf.setLineWidth(0.3);
      this.pdf.line(this.margin, this.y, this.margin + this.cw, this.y);
      this.y += 2;
    }
    this.y += 3;
  }

  private renderParagraph(t: Tokens.Paragraph) {
    this.ensureSpace(this.lh(this.bodySize));
    this.renderInline(t.tokens || [], this.margin, this.cw, this.bodySize);
    this.y += 2;
  }

  private renderList(t: Tokens.List, depth: number) {
    const indent = this.margin + depth * 6;
    const bulletW = t.ordered ? 6 : 4;
    const itemW = this.cw - (indent - this.margin) - bulletW;

    t.items.forEach((item: Tokens.ListItem, idx: number) => {
      this.ensureSpace(this.lh(this.bodySize));

      this.pdf.setFont('helvetica', 'normal');
      this.pdf.setFontSize(this.bodySize);
      this.setColor(107, 114, 128);
      if (t.ordered) {
        this.pdf.text(`${(t.start || 1) + idx}.`, indent, this.y);
      } else {
        this.pdf.setFillColor(107, 114, 128);
        this.pdf.circle(indent + 1.2, this.y - 1.2, 0.8, 'F');
      }
      this.setColor(31, 41, 55);

      let hasRendered = false;
      for (const child of (item.tokens || [])) {
        if (child.type === 'text' && (child as Tokens.Text).tokens) {
          this.renderInline((child as Tokens.Text).tokens!, indent + bulletW, itemW, this.bodySize);
          hasRendered = true;
        } else if (child.type === 'paragraph') {
          if (hasRendered) this.y += 1;
          this.renderInline((child as Tokens.Paragraph).tokens || [], indent + bulletW, itemW, this.bodySize);
          hasRendered = true;
        } else if (child.type === 'list') {
          if (!hasRendered) this.y += this.lh(this.bodySize);
          this.renderList(child as Tokens.List, depth + 1);
          hasRendered = true;
        } else if (child.type === 'text') {
          this.renderPlainTextAt((child as Tokens.Text).text, indent + bulletW, itemW, this.bodySize);
          hasRendered = true;
        }
      }
      this.y += 1;
    });
    this.y += 2;
  }

  private renderMarkdownTable(t: Tokens.Table) {
    const parseCell = (c: Tokens.TableCell): { text: string; bold: boolean } => {
      if (!c.tokens || c.tokens.length === 0) return { text: c.text, bold: false };
      let text = '';
      let hasBold = false;
      let hasPlain = false;
      for (const tok of c.tokens) {
        if (tok.type === 'strong') {
          text += extractTokenText((tok as Tokens.Strong).tokens || []);
          hasBold = true;
        } else if (tok.type === 'em') {
          text += extractTokenText((tok as Tokens.Em).tokens || []);
          hasPlain = true;
        } else if (tok.type === 'codespan') {
          text += (tok as Tokens.Codespan).text;
          hasPlain = true;
        } else if (tok.type === 'link') {
          text += extractTokenText((tok as Tokens.Link).tokens || []);
          hasPlain = true;
        } else {
          const raw = (tok as MaybeText).text ?? '';
          text += raw;
          if (raw.trim()) hasPlain = true;
        }
      }
      return { text, bold: hasBold && !hasPlain };
    };

    const headCells = t.header.map(parseCell);
    const bodyCells = t.rows.map((row: Tokens.TableCell[]) => row.map(parseCell));

    autoTable(this.pdf, {
      startY: this.y,
      head: [headCells.map(c => c.text)],
      body: bodyCells.map(row => row.map(c => c.text)),
      margin: { left: this.margin, right: this.margin },
      tableWidth: this.cw,
      styles: {
        fontSize: 10,
        cellPadding: 3,
        lineColor: [229, 231, 235],
        lineWidth: 0.3,
        textColor: [75, 85, 99],
        font: 'helvetica',
      },
      headStyles: {
        fillColor: [249, 250, 251],
        textColor: [55, 65, 81],
        fontStyle: 'bold',
        lineWidth: 0.3,
        lineColor: [209, 213, 219],
      },
      alternateRowStyles: { fillColor: [249, 250, 251] },
      bodyStyles: { fillColor: [255, 255, 255] },
      theme: 'grid',
      didParseCell: (data: CellHookData) => {
        if (data.section === 'body') {
          const cell = bodyCells[data.row.index]?.[data.column.index];
          if (cell?.bold) {
            data.cell.styles.fontStyle = 'bold';
            data.cell.styles.textColor = [55, 65, 81];
          }
        }
      },
    });

    this.y = (this.pdf as jsPDF & { lastAutoTable: { finalY: number } }).lastAutoTable.finalY + 4;
  }

  private renderCode(t: Tokens.Code) {
    const padX = 4, padY = 3, codeLH = 4.5;
    this.pdf.setFont('courier', 'normal');
    this.pdf.setFontSize(10);
    const codeW = this.cw - 2 * padX;
    const lines: string[] = this.pdf.splitTextToSize(stripEmojis(t.text), codeW);
    const totalH = lines.length * codeLH + 2 * padY;

    this.y += 3;

    if (this.y + totalH > this.pageH - this.margin) {
      this.pdf.addPage();
      this.y = this.margin;
    }

    const maxPageH = this.pageH - 2 * this.margin;

    if (totalH <= maxPageH) {
      this.drawCodeBg(this.y, totalH);
      this.setColor(31, 41, 55);
      this.pdf.setFont('courier', 'normal');
      this.pdf.setFontSize(10);
      this.y += padY;
      for (const line of lines) {
        this.pdf.text(line, this.margin + padX, this.y);
        this.y += codeLH;
      }
      this.y += padY;
    } else {
      // Very long code block — render line by line with page breaks,
      // drawing a background band per page.
      const segments = this.splitLinesIntoPages(lines, codeLH, padY);
      for (const seg of segments) {
        if (seg.newPage) { this.pdf.addPage(); this.y = this.margin; }
        const blockH = seg.lines.length * codeLH + 2 * padY;
        this.drawCodeBg(this.y, blockH);
        this.setColor(31, 41, 55);
        this.pdf.setFont('courier', 'normal');
        this.pdf.setFontSize(10);
        this.y += padY;
        for (const line of seg.lines) {
          this.pdf.text(line, this.margin + padX, this.y);
          this.y += codeLH;
        }
        this.y += padY;
      }
    }

    this.y += 3;
    this.pdf.setFont('helvetica', 'normal');
  }

  private drawCodeBg(y: number, h: number) {
    this.pdf.setFillColor(248, 249, 250);
    this.pdf.setDrawColor(229, 231, 235);
    this.pdf.roundedRect(this.margin, y, this.cw, h, 1.5, 1.5, 'FD');
  }

  /** Pre-compute line groups per page so background can be drawn before text. */
  private splitLinesIntoPages(lines: string[], codeLH: number, padY: number) {
    const segments: { lines: string[]; newPage: boolean }[] = [];
    let avail = this.pageH - this.margin - this.y - 2 * padY;
    let current: string[] = [];
    let needsNew = false;

    for (const line of lines) {
      if (avail < codeLH && current.length > 0) {
        segments.push({ lines: current, newPage: needsNew });
        current = [];
        needsNew = true;
        avail = this.pageH - 2 * this.margin - 2 * padY;
      }
      current.push(line);
      avail -= codeLH;
    }
    if (current.length > 0) segments.push({ lines: current, newPage: needsNew });
    return segments;
  }

  private renderBlockquote(t: Tokens.Blockquote) {
    const indent = 8;
    this.ensureSpace(this.lh(this.bodySize) + 4);
    this.y += 2;
    const startY = this.y;

    for (const child of (t.tokens || [])) {
      if (child.type === 'paragraph') {
        this.setColor(107, 114, 128);
        this.renderInline(
          (child as Tokens.Paragraph).tokens || [],
          this.margin + indent,
          this.cw - indent,
          this.bodySize,
          false,
          true,
        );
        this.setColor(31, 41, 55);
      } else if (child.type === 'blockquote') {
        this.renderBlockquote(child as Tokens.Blockquote);
      }
    }

    this.pdf.setDrawColor(209, 213, 219);
    this.pdf.setLineWidth(1);
    this.pdf.line(this.margin + 2, startY - 2, this.margin + 2, this.y - 1);
    this.pdf.setLineWidth(0.3);
    this.y += 3;
  }

  private renderHR() {
    this.y += 4;
    this.ensureSpace(4);
    this.pdf.setDrawColor(229, 231, 235);
    this.pdf.setLineWidth(0.3);
    this.pdf.line(this.margin, this.y, this.margin + this.cw, this.y);
    this.y += 6;
  }

  // ===================== Inline rendering with word-wrap =====================

  private renderInline(
    tokens: Token[],
    x0: number,
    maxW: number,
    fontSize: number,
    allBold = false,
    isBlockquote = false,
  ) {
    const segs = this.flattenInline(tokens, allBold, false);
    this.renderSegments(segs, x0, maxW, fontSize, isBlockquote);
  }

  private flattenInline(tokens: Token[], bold = false, italic = false, link?: string): TextSegment[] {
    const out: TextSegment[] = [];
    for (const t of tokens) {
      switch (t.type) {
        case 'text': {
          const tt = t as Tokens.Text;
          if (tt.tokens && tt.tokens.length > 0) {
            out.push(...this.flattenInline(tt.tokens, bold, italic, link));
          } else {
            out.push({ text: tt.text, bold, italic, code: false, link });
          }
          break;
        }
        case 'strong':
          out.push(...this.flattenInline((t as Tokens.Strong).tokens || [], true, italic, link));
          break;
        case 'em':
          out.push(...this.flattenInline((t as Tokens.Em).tokens || [], bold, true, link));
          break;
        case 'link':
          out.push(...this.flattenInline((t as Tokens.Link).tokens || [], bold, italic, (t as Tokens.Link).href));
          break;
        case 'codespan':
          out.push({ text: (t as Tokens.Codespan).text, bold, italic, code: true, link });
          break;
        case 'br':
          out.push({ text: '\n', bold: false, italic: false, code: false });
          break;
        case 'escape':
          out.push({ text: (t as MaybeText).text ?? '', bold, italic, code: false, link });
          break;
        default: {
          const txt = (t as MaybeText).text;
          if (typeof txt === 'string') {
            out.push({ text: txt, bold, italic, code: false, link });
          }
          break;
        }
      }
    }
    return out;
  }

  private renderSegments(
    segs: TextSegment[],
    x0: number,
    maxW: number,
    fontSize: number,
    isBlockquote = false,
  ) {
    let x = x0;
    const lh = this.lh(fontSize);

    for (const rawSeg of segs) {
      const seg = { ...rawSeg, text: rawSeg.text === '\n' ? '\n' : stripEmojis(rawSeg.text) };
      if (!seg.text) continue;

      if (seg.text === '\n') {
        this.y += lh;
        x = x0;
        this.ensureSpace(lh);
        continue;
      }

      const fontFamily = seg.code ? 'courier' : 'helvetica';
      const fontStyle = seg.bold
        ? (seg.italic ? 'bolditalic' : 'bold')
        : (seg.italic ? 'italic' : 'normal');

      this.pdf.setFont(fontFamily, fontStyle);
      this.pdf.setFontSize(fontSize);

      if (seg.link) this.setColor(37, 99, 235);
      else if (isBlockquote) this.setColor(107, 114, 128);
      else this.setColor(31, 41, 55);

      const parts = seg.text.match(/\S+|\s+/g) || [];

      for (const part of parts) {
        const isSpace = /^\s+$/.test(part);
        this.pdf.setFont(fontFamily, fontStyle);
        this.pdf.setFontSize(fontSize);
        const w = this.pdf.getTextWidth(part);

        if (isSpace && x <= x0) continue;

        if (!isSpace && x + w > x0 + maxW && x > x0) {
          this.y += lh;
          x = x0;
          if (this.y > this.pageH - this.margin) {
            this.pdf.addPage();
            this.y = this.margin;
          }
        }
        if (isSpace && x <= x0) continue;

        if (!isSpace) {
          if (seg.code) {
            const codeFontSize = fontSize * 0.9;
            this.pdf.setFont('courier', 'normal');
            this.pdf.setFontSize(codeFontSize);
            const codeW = this.pdf.getTextWidth(part);
            const bgPad = 0.8;
            this.pdf.setFillColor(243, 244, 246);
            this.pdf.roundedRect(x - bgPad, this.y - fontSize * 0.32, codeW + 2 * bgPad, fontSize * 0.42, 0.6, 0.6, 'F');
            this.setColor(31, 41, 55);
            this.pdf.text(part, x, this.y);
            x += codeW;
            this.pdf.setFont(fontFamily, fontStyle);
            this.pdf.setFontSize(fontSize);
            continue;
          }

          this.pdf.text(part, x, this.y);

          if (seg.link && (seg.link.startsWith('http://') || seg.link.startsWith('https://'))) {
            this.pdf.link(x, this.y - fontSize * 0.35, w, fontSize * 0.45, { url: seg.link });
            this.pdf.setDrawColor(37, 99, 235);
            this.pdf.setLineWidth(0.15);
            this.pdf.line(x, this.y + 0.7, x + w, this.y + 0.7);
          }
        }
        x += w;
      }
    }

    this.setColor(31, 41, 55);
    this.pdf.setFont('helvetica', 'normal');
    this.y += lh;
  }

  private renderPlainText(text: string, fontSize: number) {
    this.renderPlainTextAt(text, this.margin, this.cw, fontSize);
  }

  private renderPlainTextAt(text: string, x0: number, maxW: number, fontSize: number) {
    this.pdf.setFont('helvetica', 'normal');
    this.pdf.setFontSize(fontSize);
    this.setColor(31, 41, 55);
    const lines: string[] = this.pdf.splitTextToSize(stripEmojis(text), maxW);
    const lh = this.lh(fontSize);
    for (const line of lines) {
      this.ensureSpace(lh);
      this.pdf.text(line, x0, this.y);
      this.y += lh;
    }
  }

  // ===================== Save =====================

  save(filename: string) {
    this.pdf.save(`${filename}.pdf`);
  }
}
