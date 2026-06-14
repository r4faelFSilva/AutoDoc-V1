import { Component, OnInit, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { DocumentationService } from '../../core/services/documentation.service';
import { TemplateService } from '../../core/services/template.service';
import { DocumentationRecord, OutputType } from '../../core/models/documentation.model';
import { Template } from '../../core/models/template.model';
import { SkeletonComponent } from '../../shared/components/skeleton/skeleton.component';

const PAGE_SIZE = 10;

@Component({
  selector: 'app-history',
  standalone: true,
  imports: [CommonModule, RouterLink, FormsModule, MatSnackBarModule, SkeletonComponent],
  templateUrl: './history.component.html',
  styleUrls: ['./history.component.scss'],
})
export class HistoryComponent implements OnInit {
  allRecords = signal<DocumentationRecord[]>([]);
  templates = signal<Template[]>([]);
  loading = signal(true);

  filterType = signal<string>('');
  filterTemplate = signal<string>('');
  page = signal(0);

  deletingDoc = signal<DocumentationRecord | null>(null);
  deleteConfirmName = signal('');
  deleting = signal(false);

  canConfirmDelete = computed(() =>
    this.deleteConfirmName().trim() === this.deletingDoc()?.filename
  );

  filtered = computed(() => {
    let r = this.allRecords();
    if (this.filterType()) r = r.filter(x => x.output_type === this.filterType());
    if (this.filterTemplate()) r = r.filter(x => x.template_id === this.filterTemplate());
    return r;
  });

  paginated = computed(() => {
    const start = this.page() * PAGE_SIZE;
    return this.filtered().slice(start, start + PAGE_SIZE);
  });

  totalPages = computed(() => Math.ceil(this.filtered().length / PAGE_SIZE));

  constructor(
    private docService: DocumentationService,
    private templateService: TemplateService,
    private snackBar: MatSnackBar,
  ) {}

  ngOnInit(): void {
    this.docService.getHistory().subscribe(r => {
      this.allRecords.set(r);
      this.loading.set(false);
    });
    this.templateService.getAll().subscribe(t => this.templates.set(t));
  }

  resetPage(): void {
    this.page.set(0);
  }

  openDeleteModal(doc: DocumentationRecord): void {
    this.deletingDoc.set(doc);
    this.deleteConfirmName.set('');
  }

  closeDeleteModal(): void {
    if (this.deleting()) return;
    this.deletingDoc.set(null);
    this.deleteConfirmName.set('');
  }

  confirmDelete(): void {
    const doc = this.deletingDoc();
    if (!doc || !this.canConfirmDelete() || this.deleting()) return;
    this.deleting.set(true);
    this.docService.delete(doc.id).subscribe({
      next: () => {
        this.allRecords.update(records => records.filter(r => r.id !== doc.id));
        this.deleting.set(false);
        this.deletingDoc.set(null);
        this.deleteConfirmName.set('');
        if (this.page() > 0 && this.paginated().length === 0) {
          this.page.update(p => p - 1);
        }
        this.snackBar.open('Documentação excluída.', '', {
          duration: 3000,
          panelClass: ['snack-success'],
        });
      },
      error: () => {
        this.deleting.set(false);
        this.snackBar.open('Erro ao excluir. Tente novamente.', 'Fechar', {
          duration: 4000,
          panelClass: ['snack-error'],
        });
      },
    });
  }

  downloadMd(doc: DocumentationRecord): void {
    const blob = new Blob([doc.content], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${doc.filename.replace(/\.[^.]+$/, '')}-doc.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  formatDate(date: string): string {
    return new Date(date).toLocaleDateString('pt-BR', {
      day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  }

  typeBadge(type: OutputType): string {
    return type === 'technical' ? 'Técnica' : 'Funcional';
  }

  statusBadge(status: string): string {
    const map: Record<string, string> = { completed: 'Concluída', processing: 'Processando', failed: 'Falha' };
    return map[status] ?? status;
  }
}
