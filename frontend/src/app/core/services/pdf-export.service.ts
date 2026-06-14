import { Injectable } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';

export interface PdfExportOptions {
  renderedHtml: string;
  filename: string;
  templateName: string;
  outputType: string;
  createdAt?: string;
}

@Injectable({ providedIn: 'root' })
export class PdfExportService {
  constructor(private snackBar: MatSnackBar) {}

  export(options: PdfExportOptions): void {
    const typeLabel = options.outputType === 'technical' ? 'Técnica' : 'Funcional';
    const date = options.createdAt
      ? new Date(options.createdAt).toLocaleDateString('pt-BR', {
          day: '2-digit', month: 'long', year: 'numeric',
          hour: '2-digit', minute: '2-digit',
        })
      : new Date().toLocaleDateString('pt-BR', { day: '2-digit', month: 'long', year: 'numeric' });

    const baseName = options.filename.replace(/\.[^.]+$/, '');

    // iframe invisível — sem popup, sem bloqueio
    const iframe = document.createElement('iframe');
    iframe.style.cssText = 'position:fixed;top:0;left:0;width:0;height:0;opacity:0;border:0;';
    document.body.appendChild(iframe);

    const iframeDoc = iframe.contentDocument ?? iframe.contentWindow?.document;
    if (!iframeDoc) {
      document.body.removeChild(iframe);
      this.snackBar.open('Não foi possível gerar o PDF. Tente novamente.', 'Fechar', {
        duration: 4000, panelClass: ['snack-error'],
      });
      return;
    }

    iframeDoc.open();
    iframeDoc.write(`<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <title>${baseName} — AutoDoc</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
      font-size: 14px;
      line-height: 1.75;
      color: #1a1a1a;
      background: #fff;
    }

    /* ── Header ── */
    .pdf-header {
      padding: 28px 48px 22px;
      border-bottom: 2px solid #e5e7eb;
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 24px;
    }
    .pdf-brand {
      font-size: 22px;
      font-weight: 700;
      color: #5b5bd6;
      letter-spacing: -0.02em;
      white-space: nowrap;
    }
    .pdf-meta {
      text-align: right;
      font-size: 11.5px;
      color: #6b7280;
      line-height: 1.65;
    }
    .pdf-meta-filename {
      font-size: 13.5px;
      font-weight: 600;
      color: #111;
      display: block;
      margin-bottom: 2px;
    }

    /* ── Content ── */
    main {
      padding: 36px 48px 48px;
      max-width: 860px;
      margin: 0 auto;
    }

    h1 {
      font-size: 26px; font-weight: 700; color: #111;
      margin: 0 0 28px; padding-bottom: 14px;
      border-bottom: 2px solid #e5e7eb;
    }
    h2 {
      font-size: 20px; font-weight: 600; color: #111;
      margin: 36px 0 12px; padding-bottom: 8px;
      border-bottom: 1px solid #f0f0f0;
    }
    h3 { font-size: 16px; font-weight: 600; color: #1a1a1a; margin: 28px 0 8px; }
    h4, h5, h6 { font-size: 14px; font-weight: 600; color: #374151; margin: 20px 0 6px; }

    p { margin: 0 0 14px; }

    a { color: #5b5bd6; text-decoration: underline; }
    strong { font-weight: 600; }
    em { font-style: italic; }
    hr { border: none; border-top: 1px solid #e5e7eb; margin: 28px 0; }

    code {
      font-family: 'Cascadia Code', 'Fira Code', 'Consolas', 'Courier New', monospace;
      font-size: 12.5px;
      background: #f3f4f6;
      border: 1px solid #e5e7eb;
      border-radius: 4px;
      padding: 1px 6px;
      color: #b91c1c;
    }

    pre {
      background: #f8f9fa;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      padding: 20px 24px;
      margin: 14px 0 20px;
      overflow-x: auto;
      page-break-inside: avoid;
    }
    pre code {
      background: none; border: none; padding: 0;
      color: #1a1a1a; font-size: 12.5px; border-radius: 0;
    }

    ul, ol { padding-left: 26px; margin: 0 0 14px; }
    li { margin: 4px 0; }
    li > ul, li > ol { margin: 4px 0; }

    table {
      width: 100%; border-collapse: collapse;
      margin: 14px 0 20px; font-size: 13px;
      page-break-inside: avoid;
    }
    th, td { padding: 10px 14px; border: 1px solid #e5e7eb; text-align: left; }
    th { background: #f9fafb; font-weight: 600; color: #374151; }
    tr:nth-child(even) td { background: #fafafa; }

    blockquote {
      border-left: 4px solid #5b5bd6;
      margin: 14px 0 20px;
      padding: 12px 20px;
      background: #f5f3ff;
      border-radius: 0 8px 8px 0;
      color: #4b5563;
    }

    img { max-width: 100%; height: auto; border-radius: 6px; margin: 8px 0; }

    /* highlight.js token classes — cores básicas para impressão */
    .hljs-keyword, .hljs-selector-tag, .hljs-built_in { color: #0550ae; font-weight: 600; }
    .hljs-string, .hljs-attr { color: #067a00; }
    .hljs-comment, .hljs-meta { color: #6e7781; font-style: italic; }
    .hljs-number, .hljs-literal { color: #953800; }
    .hljs-variable, .hljs-name { color: #8250df; }
    .hljs-title, .hljs-section { color: #0550ae; font-weight: 600; }
    .hljs-type { color: #953800; }

    /* ── Footer ── */
    .pdf-footer {
      margin-top: 40px;
      padding: 14px 48px;
      border-top: 1px solid #e5e7eb;
      font-size: 11px;
      color: #9ca3af;
      display: flex;
      justify-content: space-between;
    }

    /* ── Print settings ── */
    @page {
      size: A4;
      margin: 15mm 15mm 20mm;
    }

    @media print {
      .no-print { display: none !important; }
      h1, h2, h3, h4 { page-break-after: avoid; }
      pre, table, blockquote, figure { page-break-inside: avoid; }
      a { color: #5b5bd6 !important; }
    }

  </style>
</head>
<body>
  <header class="pdf-header">
    <div class="pdf-brand">AutoDoc</div>
    <div class="pdf-meta">
      <span class="pdf-meta-filename">${options.filename}</span>
      <span>${options.templateName}</span> &nbsp;·&nbsp;
      <span>${typeLabel}</span><br/>
      <span>${date}</span>
    </div>
  </header>

  <main>${options.renderedHtml}</main>

  <footer class="pdf-footer">
    <span>Gerado pelo AutoDoc</span>
    <span>${options.filename}</span>
  </footer>
</body>
</html>`);

    iframeDoc.close();

    const iframeWin = iframe.contentWindow!;
    iframeWin.addEventListener('load', () => {
      setTimeout(() => {
        iframeWin.focus();
        iframeWin.print();
        // remove o iframe após o diálogo fechar
        iframeWin.addEventListener('afterprint', () => {
          document.body.removeChild(iframe);
        }, { once: true });
      }, 300);
    });
  }
}
