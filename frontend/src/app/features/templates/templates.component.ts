import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { TemplateService } from '../../core/services/template.service';
import { Template, CreateTemplateRequest, TemplateType } from '../../core/models/template.model';
import { SkeletonComponent } from '../../shared/components/skeleton/skeleton.component';

@Component({
  selector: 'app-templates',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, MatSnackBarModule, SkeletonComponent],
  templateUrl: './templates.component.html',
  styleUrls: ['./templates.component.scss'],
})
export class TemplatesComponent implements OnInit {
  templates = signal<Template[]>([]);
  loading = signal(true);
  drawerOpen = signal(false);
  editingTemplate = signal<Template | null>(null);
  saving = signal(false);
  deleteConfirm = signal<string | null>(null);

  /** Markdown de uma documentação já pronta (exemplo) para a IA transformar em modelo com ''placeholders'' */
  exampleMarkdown = signal('');
  exampleFilename = signal<string | null>(null);
  suggestedDownloadFilename = signal<string | null>(null);
  generatingFromExample = signal(false);

  private readonly maxExampleBytes = 500 * 1024;
  private readonly allowedExampleExtensions = ['.md', '.markdown', '.txt'];

  form: FormGroup;

  constructor(
    private templateService: TemplateService,
    private fb: FormBuilder,
    private snackBar: MatSnackBar,
  ) {
    this.form = this.fb.group({
      name: ['', Validators.required],
      description: ['', Validators.required],
      content: ['', Validators.required],
      type: ['technical' as TemplateType, Validators.required],
    });
  }

  ngOnInit(): void {
    this.loadTemplates();
  }

  onExampleInput(event: Event): void {
    const v = (event.target as HTMLTextAreaElement).value;
    this.exampleMarkdown.set(v);
    if (v.trim()) {
      this.exampleFilename.set(null);
    }
  }

  onExampleFileChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;

    const ext = file.name.includes('.') ? file.name.slice(file.name.lastIndexOf('.')).toLowerCase() : '';
    if (!this.allowedExampleExtensions.includes(ext)) {
      this.snackBar.open('Selecione um arquivo .md, .markdown ou .txt.', 'Fechar', {
        duration: 4500,
        panelClass: ['snack-error'],
      });
      input.value = '';
      return;
    }
    if (file.size > this.maxExampleBytes) {
      this.snackBar.open('Arquivo muito grande. Limite: 500 KB.', 'Fechar', {
        duration: 4500,
        panelClass: ['snack-error'],
      });
      input.value = '';
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result ?? '');
      this.exampleMarkdown.set(text);
      this.exampleFilename.set(file.name);
    };
    reader.readAsText(file);
  }

  clearExampleFile(): void {
    this.exampleMarkdown.set('');
    this.exampleFilename.set(null);
  }

  loadTemplates(): void {
    this.loading.set(true);
    this.templateService.getAll().subscribe(t => {
      this.templates.set(t);
      this.loading.set(false);
    });
  }

  openNew(): void {
    this.editingTemplate.set(null);
    this.exampleMarkdown.set('');
    this.exampleFilename.set(null);
    this.suggestedDownloadFilename.set(null);
    this.form.reset({ type: 'technical' });
    this.drawerOpen.set(true);
  }

  openEdit(template: Template): void {
    this.editingTemplate.set(template);
    this.exampleMarkdown.set('');
    this.exampleFilename.set(null);
    this.suggestedDownloadFilename.set(null);
    this.form.patchValue(template);
    this.drawerOpen.set(true);
  }

  closeDrawer(): void {
    this.drawerOpen.set(false);
    this.editingTemplate.set(null);
    this.generatingFromExample.set(false);
  }

  generateTemplateFromExample(): void {
    const text = this.exampleMarkdown().trim();
    if (text.length < 80) {
      this.snackBar.open('Cole um exemplo com pelo menos ~80 caracteres para a IA entender a estrutura.', 'Fechar', {
        duration: 4500,
        panelClass: ['snack-error'],
      });
      return;
    }
    this.generatingFromExample.set(true);
    const type = this.form.get('type')?.value as TemplateType;
    this.templateService
      .generateFromExample({ example_markdown: text, type })
      .subscribe({
        next: suggestion => {
          this.generatingFromExample.set(false);
          this.form.patchValue({
            name: suggestion.name,
            description: suggestion.description,
            content: suggestion.content,
            type: suggestion.type,
          });
          this.suggestedDownloadFilename.set(suggestion.suggested_filename ?? null);
          this.snackBar.open('Modelo gerado pela IA — revise e salve o template.', '', {
            duration: 4000,
            panelClass: ['snack-success'],
          });
        },
        error: (err: unknown) => {
          this.generatingFromExample.set(false);
          let msg = 'Não foi possível gerar o modelo. Verifique a API OpenAI e tente de novo.';
          if (err instanceof HttpErrorResponse) {
            const d = err.error?.detail;
            if (typeof d === 'string') {
              msg = d;
            }
          }
          this.snackBar.open(msg, 'Fechar', { duration: 6000, panelClass: ['snack-error'] });
        },
      });
  }

  save(): void {
    if (this.form.invalid || this.saving()) return;
    this.saving.set(true);
    const data = this.form.value as CreateTemplateRequest;
    const editing = this.editingTemplate();

    const op = editing
      ? this.templateService.update(editing.id, data)
      : this.templateService.create(data);

    op.subscribe({
      next: () => {
        this.saving.set(false);
        this.closeDrawer();
        this.loadTemplates();
        this.snackBar.open(editing ? 'Template atualizado!' : 'Template criado!', '', {
          duration: 3000,
          panelClass: ['snack-success'],
        });
      },
      error: () => {
        this.saving.set(false);
        this.snackBar.open('Erro ao salvar template.', 'Fechar', { duration: 4000, panelClass: ['snack-error'] });
      },
    });
  }

  confirmDelete(id: string): void {
    this.deleteConfirm.set(id);
  }

  cancelDelete(): void {
    this.deleteConfirm.set(null);
  }

  deleteTemplate(id: string): void {
    this.templateService.delete(id).subscribe(() => {
      this.deleteConfirm.set(null);
      this.loadTemplates();
      this.snackBar.open('Template removido.', '', { duration: 3000 });
    });
  }

  formatDate(date: string): string {
    return new Date(date).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short', year: 'numeric' });
  }

  typeBadge(type: TemplateType): string {
    return type === 'technical' ? 'Técnico' : 'Funcional';
  }

  downloadTemplateMd(): void {
    const content = (this.form.get('content')?.value as string)?.trim();
    if (!content) {
      this.snackBar.open('Preencha o conteúdo do template antes de baixar.', 'Fechar', {
        duration: 4000,
        panelClass: ['snack-error'],
      });
      return;
    }
    const suggested = this.suggestedDownloadFilename();
    const name = (this.form.get('name')?.value as string)?.trim();
    const filename =
      suggested ||
      (name
        ? `${name
            .toLowerCase()
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '')
            .replace(/[^a-z0-9]+/g, '-')
            .replace(/^-|-$/g, '') || 'template'}.md`
        : 'template-autodoc.md');

    const blob = new Blob([content], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename.endsWith('.md') ? filename : `${filename}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }
}
