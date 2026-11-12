import { Component, DestroyRef, OnInit, inject, signal, ViewChild, ElementRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MarkdownModule } from 'ngx-markdown';
import { Subscription } from 'rxjs';
import { DocumentationService } from '../../core/services/documentation.service';
import { AgentRunsService } from '../../core/services/agent-runs.service';
import { PdfExportService } from '../../core/services/pdf-export.service';
import { TemplateService } from '../../core/services/template.service';
import { DocumentationRecord } from '../../core/models/documentation.model';
import { AgentRun, DocumentadorInput } from '../../core/models/agent-run.model';
import { Template } from '../../core/models/template.model';
import { SkeletonComponent } from '../../shared/components/skeleton/skeleton.component';

/** Folga da tela sobre o limite do servidor antes de desistir de esperar. */
const DEADLINE_MARGIN_SECONDS = 60;
/** Usado se a resposta do servidor não informar o limite do run. */
const DEFAULT_RUN_TIMEOUT_SECONDS = 300;

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
  /** Erro da última geração, exibido em destaque até a próxima tentativa. */
  errorMessage = signal<string | null>(null);

  private readonly destroyRef = inject(DestroyRef);
  private watchSub?: Subscription;
  private pollTimer?: ReturnType<typeof setTimeout>;
  private deadlineTimer?: ReturnType<typeof setTimeout>;

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
    // Saiu da tela: para de acompanhar o run (stream, polling e prazo).
    this.destroyRef.onDestroy(() => this.stopWatching());
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

    this.stopWatching();
    this.loading.set(true);
    this.result.set(null);
    this.errorMessage.set(null);
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

    const repoToken = mode === 'github' ? this.githubToken() : undefined;
    this.runsService.createRun('documentador', input as unknown as Record<string, unknown>, repoToken).subscribe({
      next: run => {
        this.startDeadline(run);
        this.watchRun(run.id);
      },
      error: (err: unknown) => this.failGeneration(err),
    });
  }

  /** Prazo total na tela: limite do run no servidor + folga. */
  private startDeadline(run: AgentRun): void {
    const limit = run.timeout_seconds ?? DEFAULT_RUN_TIMEOUT_SECONDS;
    this.deadlineTimer = setTimeout(() => {
      this.stopWatching();
      this.showError(
        `A geração não terminou em ${this.describeDuration(limit)}. ` +
          'Ela pode ter falhado no servidor — confira o Histórico.',
      );
    }, (limit + DEADLINE_MARGIN_SECONDS) * 1000);
  }

  private stopWatching(): void {
    this.watchSub?.unsubscribe();
    this.watchSub = undefined;
    clearTimeout(this.pollTimer);
    clearTimeout(this.deadlineTimer);
  }

  private watchRun(runId: number): void {
    let finished = false;
    this.watchSub = this.runsService.streamEvents(runId).subscribe({
      next: event => {
        this.progressMessage.set(event.message);
        if (event.kind === 'completed' || event.kind === 'failed') {
          finished = true;
          this.stopWatching();
        }
        if (event.kind === 'completed') {
          const docId = event.data?.['doc_id'];
          this.loadGeneratedDoc(String(docId));
        } else if (event.kind === 'failed') {
          this.showError(event.message.replace(/^Run falhou:\s*/, '') || 'Erro ao gerar documentação.');
        }
      },
      // Stream caiu (proxy, rede)? Degrada para polling — o run segue no backend.
      error: () => this.pollRun(runId),
      // Stream encerrado sem completed/failed: não dá para saber o desfecho por ele,
      // então consulta o run por polling em vez de deixar a tela esperando.
      complete: () => {
        if (!finished) {
          this.pollRun(runId);
        }
      },
    });
  }

  /** Consulta o run a cada 2 s até terminar; o prazo total (startDeadline) encerra a espera. */
  private pollRun(runId: number): void {
    this.watchSub = this.runsService.getRun(runId).subscribe({
      next: (run: AgentRun) => {
        if (run.status === 'completed') {
          this.stopWatching();
          this.loadGeneratedDoc(String(run.output?.['doc_id']));
        } else if (run.status === 'failed' || run.status === 'cancelled') {
          this.stopWatching();
          this.showError(run.error || 'Erro ao gerar documentação.');
        } else {
          this.pollTimer = setTimeout(() => this.pollRun(runId), 2000);
        }
      },
      error: (err: unknown) => {
        this.stopWatching();
        this.failGeneration(err);
      },
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

  private showError(message: string): void {
    this.loading.set(false);
    this.errorMessage.set(message);
    this.snackBar.open(message, 'Fechar', {
      duration: 5000,
      panelClass: ['snack-error'],
    });
  }

  private describeDuration(seconds: number): string {
    if (seconds >= 60 && seconds % 60 === 0) {
      const minutes = seconds / 60;
      return minutes === 1 ? '1 minuto' : `${minutes} minutos`;
    }
    return `${seconds} s`;
  }

  private failGeneration(err: unknown): void {
    let msg = 'Erro ao gerar documentação.';
    if (err instanceof HttpErrorResponse) {
      const d = err.error?.detail;
      if (typeof d === 'string') {
        msg = d;
      } else if (Array.isArray(d)) {
        msg = d.map((x: { msg?: string }) => x.msg).filter(Boolean).join(' ') || msg;
      }
    }
    this.showError(msg);
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
