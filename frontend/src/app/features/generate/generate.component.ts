import { Component, OnInit, signal, ViewChild, ElementRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MarkdownModule } from 'ngx-markdown';
import { DocumentationService } from '../../core/services/documentation.service';
import { PdfExportService } from '../../core/services/pdf-export.service';
import { TemplateService } from '../../core/services/template.service';
import { DocumentationRecord } from '../../core/models/documentation.model';
import { Template } from '../../core/models/template.model';
import { SkeletonComponent } from '../../shared/components/skeleton/skeleton.component';

@Component({
  selector: 'app-generate',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, MatSnackBarModule, MarkdownModule, SkeletonComponent],
  templateUrl: './generate.component.html',
  styleUrls: ['./generate.component.scss'],
})
export class GenerateComponent implements OnInit {
  @ViewChild('markdownResult') private markdownResult!: ElementRef<HTMLDivElement>;

  form: FormGroup;
  templates = signal<Template[]>([]);
  loading = signal(false);
  result = signal<DocumentationRecord | null>(null);
  inputMode = signal<'paste' | 'upload' | 'github'>('paste');
  uploadedFilename = signal<string | null>(null);
  editMode = signal(false);
  editedContent = signal('');

  outputTypes = [
    { value: 'technical', label: 'Técnica (para devs)', icon: 'code' },
    { value: 'functional', label: 'Funcional (para onboarding)', icon: 'groups' },
  ];

  private readonly githubUrlPattern = /^https:\/\/(www\.)?github\.com\/[^/]+\/[^/]+/i;

  constructor(
    private fb: FormBuilder,
    private docService: DocumentationService,
    private templateService: TemplateService,
    private snackBar: MatSnackBar,
    private pdfExport: PdfExportService,
  ) {
    this.form = this.fb.group({
      code: [''],
      github_url: [''],
      branch: [''],
      template_id: ['', Validators.required],
      output_type: ['technical', Validators.required],
    });
  }

  ngOnInit(): void {
    this.applyValidatorsForMode();
    this.templateService.getAll().subscribe(t => {
      this.templates.set(t);
      if (t.length > 0) {
        this.form.patchValue({ template_id: t[0].id });
      }
    });
  }

  setInputMode(mode: 'paste' | 'upload' | 'github'): void {
    this.inputMode.set(mode);
    this.result.set(null);
    this.applyValidatorsForMode();
  }

  private applyValidatorsForMode(): void {
    const codeCtrl = this.form.get('code')!;
    const urlCtrl = this.form.get('github_url')!;
    if (this.inputMode() === 'github') {
      codeCtrl.clearValidators();
      urlCtrl.setValidators([Validators.required, Validators.pattern(this.githubUrlPattern)]);
    } else {
      urlCtrl.clearValidators();
      codeCtrl.setValidators(Validators.required);
    }
    codeCtrl.updateValueAndValidity({ emitEvent: false });
    urlCtrl.updateValueAndValidity({ emitEvent: false });
  }

  onFileChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;

    this.uploadedFilename.set(file.name);
    const reader = new FileReader();
    reader.onload = () => {
      this.form.patchValue({ code: reader.result as string });
    };
    reader.readAsText(file);
  }

  generate(): void {
    if (this.loading()) return;
    if (this.inputMode() === 'github') {
      const urlCtrl = this.form.get('github_url');
      if (!urlCtrl?.valid) return;
    } else if (this.form.invalid) {
      return;
    }

    this.loading.set(true);
    this.result.set(null);

    const mode = this.inputMode();
    const req =
      mode === 'github'
        ? this.docService.generateFromGithub({
            github_url: (this.form.get('github_url')?.value as string).trim(),
            template_id: this.form.get('template_id')?.value,
            output_type: this.form.get('output_type')?.value,
            branch: (this.form.get('branch')?.value as string)?.trim() || undefined,
          })
        : this.docService.generate({
            code: this.form.get('code')?.value,
            template_id: this.form.get('template_id')?.value,
            output_type: this.form.get('output_type')?.value,
            filename: this.uploadedFilename() || 'código-colado.txt',
          });

    req.subscribe({
      next: doc => {
        this.result.set(doc);
        this.editedContent.set(doc.content);
        this.editMode.set(false);
        this.loading.set(false);
        this.snackBar.open('Documentação gerada com sucesso!', '', {
          duration: 3000,
          panelClass: ['snack-success'],
        });
      },
      error: (err: unknown) => {
        this.loading.set(false);
        let msg = 'Erro ao gerar documentação.';
        if (err instanceof HttpErrorResponse) {
          const d = err.error?.detail;
          if (typeof d === 'string') {
            msg = d;
          } else if (Array.isArray(d)) {
            msg = d.map((x: { msg?: string }) => x.msg).filter(Boolean).join(' ') || msg;
          }
        }
        this.snackBar.open(msg, 'Fechar', {
          duration: 5000,
          panelClass: ['snack-error'],
        });
      },
    });
  }

  exportPdf(): void {
    const doc = this.result();
    if (!doc) return;
    this.pdfExport.export({
      renderedHtml: this.markdownResult.nativeElement.innerHTML,
      filename: doc.filename,
      templateName: doc.template_name,
      outputType: doc.output_type,
    });
  }

  downloadMd(): void {
    const doc = this.result();
    if (!doc) return;
    const blob = new Blob([this.editedContent()], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${doc.filename.replace(/\.[^.]+$/, '')}-doc.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  copyMarkdown(): void {
    if (!this.editedContent()) return;
    void navigator.clipboard.writeText(this.editedContent()).then(
      () =>
        this.snackBar.open('Markdown copiado para a área de transferência.', '', {
          duration: 2800,
          panelClass: ['snack-success'],
        }),
      () =>
        this.snackBar.open('Não foi possível copiar. Verifique permissões do navegador.', 'Fechar', {
          duration: 4000,
          panelClass: ['snack-error'],
        }),
    );
  }
}
