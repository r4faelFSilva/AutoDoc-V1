import { Component, OnInit, signal, ViewChild, ElementRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MarkdownModule } from 'ngx-markdown';
import { DocumentationService } from '../../core/services/documentation.service';
import { AgentRunsService } from '../../core/services/agent-runs.service';
import { PdfExportService } from '../../core/services/pdf-export.service';
import { TemplateService } from '../../core/services/template.service';
import { DocumentationRecord } from '../../core/models/documentation.model';
import { AgentRun, DocumentadorInput } from '../../core/models/agent-run.model';
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
  progressMessage = signal('');
  result = signal<DocumentationRecord | null>(null);
  inputMode = signal<'paste' | 'upload' | 'github'>('paste');
  uploadedFilename = signal<string | null>(null);
  editMode = signal(false);
  editedContent = signal('');
  githubToken = signal('');
  commitTargetPath = signal('README.md');
  commitMessage = signal('docs: atualiza documentação via AutoDoc');
  publishing = signal(false);

  outputTypes = [
    { value: 'technical', label: 'Técnica (para devs)', icon: 'code' },
    { value: 'functional', label: 'Funcional (para onboarding)', icon: 'groups' },
  ];

  private readonly githubUrlPattern = /^https:\/\/(www\.)?github\.com\/[^/]+\/[^/]+/i;

  constructor(
    private fb: FormBuilder,
    private docService: DocumentationService,
    private runsService: AgentRunsService,
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
      // Análise profunda é opt-in — múltiplas chamadas de IA por documento
      deep: [false],
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
    this.githubToken.set('');
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
    this.progressMessage.set('Enviando para o agente documentador…');

    const mode = this.inputMode();
    const depth = this.form.get('deep')?.value ? 'deep' : 'quick';
    const input: DocumentadorInput =
      mode === 'github'
        ? {
            source: 'github',
            github_url: (this.form.get('github_url')?.value as string).trim(),
            template_id: Number(this.form.get('template_id')?.value),
            output_type: this.form.get('output_type')?.value,
            depth,
            branch: (this.form.get('branch')?.value as string)?.trim() || undefined,
          }
        : {
            source: mode,
            code: this.form.get('code')?.value,
            template_id: Number(this.form.get('template_id')?.value),
            output_type: this.form.get('output_type')?.value,
            depth,
            filename: this.uploadedFilename() || 'código-colado.txt',
          };

    this.runsService.createRun('documentador', input as unknown as Record<string, unknown>).subscribe({
      next: run => this.watchRun(run.id),
      error: (err: unknown) => this.failGeneration(err),
    });
  }

  private watchRun(runId: number): void {
    this.runsService.streamEvents(runId).subscribe({
      next: event => {
        this.progressMessage.set(event.message);
        if (event.kind === 'completed') {
          const docId = event.data?.['doc_id'];
          this.loadGeneratedDoc(String(docId));
        } else if (event.kind === 'failed') {
          this.loading.set(false);
          this.snackBar.open(event.message || 'Erro ao gerar documentação.', 'Fechar', {
            duration: 5000,
            panelClass: ['snack-error'],
          });
        }
      },
      // Stream caiu (proxy, rede)? Degrada para polling — o run segue no backend.
      error: () => this.pollRun(runId),
    });
  }

  private pollRun(runId: number, attempt = 0): void {
    const maxAttempts = 150; // ~5 min a cada 2s
    this.runsService.getRun(runId).subscribe({
      next: (run: AgentRun) => {
        if (run.status === 'completed') {
          this.loadGeneratedDoc(String(run.output?.['doc_id']));
        } else if (run.status === 'failed' || run.status === 'cancelled') {
          this.loading.set(false);
          this.snackBar.open(run.error || 'Erro ao gerar documentação.', 'Fechar', {
            duration: 5000,
            panelClass: ['snack-error'],
          });
        } else if (attempt < maxAttempts) {
          setTimeout(() => this.pollRun(runId, attempt + 1), 2000);
        } else {
          this.loading.set(false);
          this.snackBar.open('Tempo esgotado aguardando a geração.', 'Fechar', {
            duration: 5000,
            panelClass: ['snack-error'],
          });
        }
      },
      error: (err: unknown) => this.failGeneration(err),
    });
  }

  private loadGeneratedDoc(docId: string): void {
    this.docService.getById(docId).subscribe({
      next: doc => {
        this.loading.set(false);
        if (!doc) {
          this.snackBar.open('Documento gerado, mas não encontrado no histórico.', 'Fechar', {
            duration: 5000,
            panelClass: ['snack-error'],
          });
          return;
        }
        this.result.set(doc);
        this.editedContent.set(doc.content);
        this.editMode.set(false);
        this.snackBar.open('Documentação gerada com sucesso!', '', {
          duration: 3000,
          panelClass: ['snack-success'],
        });
      },
      error: (err: unknown) => this.failGeneration(err),
    });
  }

  private failGeneration(err: unknown): void {
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

  canPublishToGithub(): boolean {
    const doc = this.result();
    return (
      this.inputMode() === 'github' &&
      !!doc &&
      doc.status === 'completed' &&
      !!doc.github_url &&
      !!this.editedContent().trim()
    );
  }

  publishToGithub(): void {
    if (!this.canPublishToGithub() || this.publishing()) return;

    const token = this.githubToken().trim();
    if (!token) {
      this.snackBar.open('Informe um Personal Access Token do GitHub.', 'Fechar', {
        duration: 4500,
        panelClass: ['snack-error'],
      });
      return;
    }

    const doc = this.result()!;
    this.publishing.set(true);

    this.docService
      .commitGithubReadme({
        github_url: doc.github_url!,
        content: this.editedContent(),
        github_token: token,
        branch: (this.form.get('branch')?.value as string)?.trim() || undefined,
        target_path: this.commitTargetPath().trim() || 'README.md',
        commit_message: this.commitMessage().trim() || undefined,
      })
      .subscribe({
        next: res => {
          this.publishing.set(false);
          this.githubToken.set('');
          const msg = res.commit_url
            ? `Publicado em ${res.target_path} (${res.branch}).`
            : `Publicado em ${res.target_path} (${res.branch}).`;
          this.snackBar.open(msg, res.commit_url ? 'Ver commit' : 'Fechar', {
            duration: 8000,
            panelClass: ['snack-success'],
          }).onAction().subscribe(() => {
            if (res.commit_url) {
              window.open(res.commit_url, '_blank', 'noopener');
            }
          });
        },
        error: (err: unknown) => {
          this.publishing.set(false);
          this.githubToken.set('');
          let msg = 'Não foi possível publicar no GitHub.';
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

  onGithubTokenInput(event: Event): void {
    this.githubToken.set((event.target as HTMLInputElement).value);
  }

  onCommitTargetPathInput(event: Event): void {
    this.commitTargetPath.set((event.target as HTMLInputElement).value);
  }

  onCommitMessageInput(event: Event): void {
    this.commitMessage.set((event.target as HTMLTextAreaElement).value);
  }
}
