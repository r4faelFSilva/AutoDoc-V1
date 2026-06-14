import { Component, OnInit, signal, computed, ViewChild, ElementRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { MarkdownModule } from 'ngx-markdown';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { DocumentationService } from '../../core/services/documentation.service';
import { PdfExportService } from '../../core/services/pdf-export.service';
import { DocumentationRecord } from '../../core/models/documentation.model';
import { SkeletonComponent } from '../../shared/components/skeleton/skeleton.component';

@Component({
  selector: 'app-documentation-viewer',
  standalone: true,
  imports: [CommonModule, RouterLink, MarkdownModule, SkeletonComponent, MatSnackBarModule],
  templateUrl: './documentation-viewer.component.html',
  styleUrls: ['./documentation-viewer.component.scss'],
})
export class DocumentationViewerComponent implements OnInit {
  @ViewChild('markdownContent') private markdownContent!: ElementRef<HTMLDivElement>;

  doc = signal<DocumentationRecord | null>(null);
  loading = signal(true);
  notFound = signal(false);
  editMode = signal(false);
  editedContent = signal('');
  saving = signal(false);
  highlightQuery = signal('');
  highlightCount = signal(0);

  isModified = computed(() =>
    this.editedContent() !== (this.doc()?.content ?? '')
  );

  constructor(
    private route: ActivatedRoute,
    private docService: DocumentationService,
    private snackBar: MatSnackBar,
    private pdfExport: PdfExportService,
  ) {}

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id')!;
    this.highlightQuery.set(this.route.snapshot.queryParamMap.get('highlight') ?? '');

    this.docService.getById(id).subscribe(doc => {
      if (doc) {
        this.doc.set(doc);
        this.editedContent.set(doc.content);
      } else {
        this.notFound.set(true);
      }
      this.loading.set(false);
    });
  }

  onMarkdownReady(): void {
    const query = this.highlightQuery();
    if (!query || query.trim().length < 2) return;
    // Let the markdown component finish painting before traversing
    setTimeout(() => this.applyHighlights(query), 80);
  }

  private applyHighlights(query: string): void {
    const container = this.markdownContent?.nativeElement;
    if (!container) return;

    // Remove stale marks first
    container.querySelectorAll('mark.search-highlight').forEach(mark => {
      const parent = mark.parentNode!;
      parent.replaceChild(document.createTextNode(mark.textContent ?? ''), mark);
      parent.normalize();
    });

    if (!query.trim()) { this.highlightCount.set(0); return; }

    const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(escaped, 'gi');

    // Collect text nodes (skip <script>, <style>, already-marked)
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
      acceptNode: (node) => {
        const tag = (node.parentElement?.tagName ?? '').toLowerCase();
        return ['script', 'style', 'mark'].includes(tag)
          ? NodeFilter.FILTER_REJECT
          : NodeFilter.FILTER_ACCEPT;
      },
    });

    const textNodes: Text[] = [];
    let n: Node | null;
    while ((n = walker.nextNode())) textNodes.push(n as Text);

    let total = 0;
    for (const textNode of textNodes) {
      const text = textNode.textContent ?? '';
      if (!regex.test(text)) { regex.lastIndex = 0; continue; }
      regex.lastIndex = 0;

      const frag = document.createDocumentFragment();
      let last = 0;
      let m: RegExpExecArray | null;
      while ((m = regex.exec(text)) !== null) {
        if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
        const mark = document.createElement('mark');
        mark.className = 'search-highlight';
        mark.textContent = m[0];
        frag.appendChild(mark);
        last = regex.lastIndex;
        total++;
      }
      if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
      textNode.parentNode!.replaceChild(frag, textNode);
    }

    this.highlightCount.set(total);

    // Scroll to first match
    const firstMark = container.querySelector('mark.search-highlight');
    firstMark?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  clearHighlights(): void {
    const container = this.markdownContent?.nativeElement;
    if (container) {
      container.querySelectorAll('mark.search-highlight').forEach(mark => {
        mark.parentNode!.replaceChild(document.createTextNode(mark.textContent ?? ''), mark);
        mark.parentNode?.normalize();
      });
    }
    this.highlightQuery.set('');
    this.highlightCount.set(0);
  }

  formatDate(date: string): string {
    return new Date(date).toLocaleDateString('pt-BR', {
      day: '2-digit', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  }

  downloadMd(): void {
    const doc = this.doc();
    if (!doc) return;
    const blob = new Blob([this.editedContent()], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${doc.filename.replace(/\.[^.]+$/, '')}-doc.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  saveChanges(): void {
    const doc = this.doc();
    if (!doc || this.saving()) return;
    this.saving.set(true);
    this.docService.updateContent(doc.id, this.editedContent()).subscribe({
      next: updated => {
        this.doc.set(updated);
        this.saving.set(false);
        this.editMode.set(false);
        this.snackBar.open('Alterações salvas com sucesso!', '', {
          duration: 3000, panelClass: ['snack-success'],
        });
      },
      error: () => {
        this.saving.set(false);
        this.snackBar.open('Erro ao salvar. Tente novamente.', 'Fechar', {
          duration: 4000, panelClass: ['snack-error'],
        });
      },
    });
  }

  discardChanges(): void {
    const doc = this.doc();
    if (!doc) return;
    this.editedContent.set(doc.content);
    this.editMode.set(false);
  }

  exportPdf(): void {
    const doc = this.doc();
    if (!doc) return;
    this.pdfExport.export({
      renderedHtml: this.markdownContent.nativeElement.innerHTML,
      filename: doc.filename,
      templateName: doc.template_name,
      outputType: doc.output_type,
      createdAt: doc.created_at,
    });
  }

  copyMarkdown(): void {
    if (!this.editedContent()) return;
    void navigator.clipboard.writeText(this.editedContent()).then(
      () => this.snackBar.open('Markdown copiado para a área de transferência.', '', {
        duration: 2800, panelClass: ['snack-success'],
      }),
      () => this.snackBar.open('Não foi possível copiar.', 'Fechar', {
        duration: 4000, panelClass: ['snack-error'],
      }),
    );
  }
}
