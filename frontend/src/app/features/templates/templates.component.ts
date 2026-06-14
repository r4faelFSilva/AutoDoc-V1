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
  generatingFromExample = signal(false);

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
    this.form.reset({ type: 'technical' });
    this.drawerOpen.set(true);
  }

  openEdit(template: Template): void {
    this.editingTemplate.set(template);
    this.exampleMarkdown.set('');
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
}
