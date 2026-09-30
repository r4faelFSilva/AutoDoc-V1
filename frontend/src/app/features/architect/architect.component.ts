import { Component, ElementRef, ViewChild, computed, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MarkdownModule } from 'ngx-markdown';
import { AgentRunsService } from '../../core/services/agent-runs.service';
import { analyzeLoad } from '../../core/services/loadflow';
import {
  ArchAnnotation,
  ArchEdge,
  ArchNode,
  ArchNodeType,
  ArchitectureGraph,
  ArquitetoOutput,
} from '../../core/models/architecture.model';
import { AgentRun } from '../../core/models/agent-run.model';

const NODE_W = 172;
const NODE_H = 64;

/** Estilo visual por tipo de nó. */
const NODE_STYLE: Record<string, { icon: string; color: string; label: string }> = {
  client: { icon: 'devices', color: '#8b5cf6', label: 'Cliente' },
  gateway: { icon: 'alt_route', color: '#0ea5e9', label: 'Gateway' },
  service: { icon: 'dns', color: '#3b82f6', label: 'Serviço' },
  worker: { icon: 'engineering', color: '#06b6d4', label: 'Worker' },
  db: { icon: 'database', color: '#f59e0b', label: 'Banco' },
  cache: { icon: 'bolt', color: '#ef4444', label: 'Cache' },
  queue: { icon: 'stacked_email', color: '#10b981', label: 'Fila' },
  storage: { icon: 'cloud', color: '#64748b', label: 'Storage' },
  external: { icon: 'public', color: '#a855f7', label: 'Externo' },
};

/** Arquitetura de exemplo para estudo — carregável sem IA. */
const SAMPLE: ArchitectureGraph = {
  nodes: [
    { id: 'client', type: 'client', label: 'Usuários', tech: 'Web/Mobile', props: {} },
    { id: 'api', type: 'service', label: 'API', tech: 'FastAPI', props: { replicas: 2, rps_capacity: 150 } },
    { id: 'cache', type: 'cache', label: 'Cache', tech: 'Redis', props: { replicas: 1, rps_capacity: 5000 } },
    { id: 'db', type: 'db', label: 'Banco', tech: 'PostgreSQL', props: { replicas: 1, rps_capacity: 120 } },
    { id: 'queue', type: 'queue', label: 'Fila', tech: 'RabbitMQ', props: { replicas: 1, rps_capacity: 800 } },
    { id: 'worker', type: 'worker', label: 'Worker', tech: 'Python', props: { replicas: 2, rps_capacity: 100 } },
  ],
  edges: [
    { from: 'client', to: 'api', protocol: 'https', sync: true, weight: 1.0 },
    { from: 'api', to: 'cache', protocol: 'tcp', sync: true, weight: 0.9 },
    { from: 'api', to: 'db', protocol: 'tcp', sync: true, weight: 0.6 },
    { from: 'api', to: 'queue', protocol: 'amqp', sync: false, weight: 0.3 },
    { from: 'queue', to: 'worker', protocol: 'amqp', sync: false, weight: 1.0 },
  ],
};

interface CanvasNode extends ArchNode {
  x: number;
  y: number;
}

@Component({
  selector: 'app-architect',
  standalone: true,
  imports: [CommonModule, FormsModule, MatSnackBarModule, MarkdownModule],
  templateUrl: './architect.component.html',
  styleUrls: ['./architect.component.scss'],
})
export class ArchitectComponent {
  @ViewChild('canvasSvg') private canvasSvg?: ElementRef<SVGSVGElement>;

  readonly nodeTypes = Object.keys(NODE_STYLE) as ArchNodeType[];

  // painel de IA (opcional — o canvas existe sem ele)
  aiPanelOpen = signal(false);
  inputMode = signal<'spec' | 'github'>('spec');
  spec = signal('');
  specFilename = signal<string | null>(null);
  extracting = signal(false);
  githubUrl = signal('');
  branch = signal('');
  expectedRps = signal(100);

  // execução
  loading = signal(false);
  progressMessage = signal('');
  output = signal<ArquitetoOutput | null>(null);

  // canvas — sempre disponível
  nodes = signal<CanvasNode[]>([]);
  edges = signal<ArchEdge[]>([]);
  selectedNodeId = signal<string | null>(null);
  connectTargetId = signal<string>('');
  whatIfRps = signal(200);
  adrOpen = signal(false);

  private aiAnnotations = signal<ArchAnnotation[]>([]);
  private dragging: { id: string; dx: number; dy: number } | null = null;
  private nodeCounter = 1;

  localAnalysis = computed(() => {
    const graph: ArchitectureGraph = { nodes: this.nodes(), edges: this.edges() };
    if (graph.nodes.length === 0) return { loads: {}, annotations: [] as ArchAnnotation[] };
    return analyzeLoad(graph, this.whatIfRps());
  });

  allAnnotations = computed<ArchAnnotation[]>(() => {
    const seen = new Set<string>();
    const merged: ArchAnnotation[] = [];
    for (const a of [...this.localAnalysis().annotations, ...this.aiAnnotations()]) {
      const key = `${a.target}|${a.kind}`;
      if (seen.has(key)) continue;
      seen.add(key);
      merged.push(a);
    }
    const order: Record<string, number> = { high: 0, medium: 1, low: 2 };
    return merged.sort((x, y) => (order[x.severity] ?? 3) - (order[y.severity] ?? 3));
  });

  selectedNode = computed(() => this.nodes().find(n => n.id === this.selectedNodeId()) ?? null);

  otherNodes = computed(() => this.nodes().filter(n => n.id !== this.selectedNodeId()));

  constructor(
    private runsService: AgentRunsService,
    private snackBar: MatSnackBar,
  ) {}

  // ------------------------------------------------------------ modo livre

  addNode(type: ArchNodeType): void {
    const id = this.nextNodeId();
    const count = this.nodes().length;
    const node: CanvasNode = {
      id,
      type,
      label: `${NODE_STYLE[type].label} ${this.nodeCounter}`,
      tech: '',
      props: { replicas: 1 },
      x: 60 + (count % 4) * (NODE_W + 60),
      y: 60 + Math.floor(count / 4) * (NODE_H + 70),
    };
    this.nodes.update(list => [...list, node]);
    this.selectedNodeId.set(id);
  }

  private nextNodeId(): string {
    const existing = new Set(this.nodes().map(n => n.id));
    let id = `c${this.nodeCounter}`;
    while (existing.has(id)) {
      this.nodeCounter += 1;
      id = `c${this.nodeCounter}`;
    }
    this.nodeCounter += 1;
    return id;
  }

  loadSample(): void {
    this.aiAnnotations.set([]);
    this.output.set(null);
    this.whatIfRps.set(200);
    this.layoutGraph(SAMPLE);
    this.selectedNodeId.set(null);
    this.snackBar.open('Exemplo carregado — mexa nas réplicas e no what-if para estudar.', '', {
      duration: 4000,
      panelClass: ['snack-success'],
    });
  }

  clearCanvas(): void {
    this.nodes.set([]);
    this.edges.set([]);
    this.output.set(null);
    this.aiAnnotations.set([]);
    this.selectedNodeId.set(null);
    this.adrOpen.set(false);
  }

  connectSelected(): void {
    const from = this.selectedNodeId();
    const to = this.connectTargetId();
    if (!from || !to || from === to) return;
    if (this.edges().some(e => e.from === from && e.to === to)) {
      this.snackBar.open('Essa conexão já existe.', '', { duration: 2500 });
      return;
    }
    this.edges.update(list => [...list, { from, to, protocol: 'http', sync: true, weight: 1.0 }]);
    this.connectTargetId.set('');
  }

  outgoingEdges(id: string): ArchEdge[] {
    return this.edges().filter(e => e.from === id);
  }

  nodeLabel(id: string): string {
    return this.nodes().find(n => n.id === id)?.label ?? id;
  }

  removeEdge(edge: ArchEdge): void {
    this.edges.update(list => list.filter(e => e !== edge));
  }

  updateEdgeWeight(edge: ArchEdge, value: string): void {
    const num = Number(value);
    if (!Number.isFinite(num) || num < 0) return;
    this.edges.update(list => list.map(e => (e === edge ? { ...e, weight: num } : e)));
  }

  toggleEdgeSync(edge: ArchEdge): void {
    this.edges.update(list => list.map(e => (e === edge ? { ...e, sync: !e.sync } : e)));
  }

  // ------------------------------------------------------------ upload de spec

  onSpecFileChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    const name = file.name.toLowerCase();

    if (name.endsWith('.txt') || name.endsWith('.md')) {
      const reader = new FileReader();
      reader.onload = () => {
        this.spec.set(String(reader.result ?? ''));
        this.specFilename.set(file.name);
      };
      reader.readAsText(file);
      return;
    }

    if (name.endsWith('.docx') || name.endsWith('.pdf')) {
      this.extracting.set(true);
      this.runsService.extractSpecFile(file).subscribe({
        next: res => {
          this.extracting.set(false);
          this.spec.set(res.text);
          this.specFilename.set(res.filename);
          if (res.truncated) {
            this.snackBar.open('Documento longo — texto truncado em 20 mil caracteres.', '', {
              duration: 4500,
            });
          }
        },
        error: (err: unknown) => {
          this.extracting.set(false);
          this.fail(err, 'Não foi possível extrair o texto do documento.');
        },
      });
      return;
    }

    this.snackBar.open('Formato não suportado. Use .txt, .md, .docx ou .pdf.', 'Fechar', {
      duration: 4500,
      panelClass: ['snack-error'],
    });
  }

  // ------------------------------------------------------------ execução IA

  generate(): void {
    if (this.loading()) return;
    const input: Record<string, unknown> = { expected_rps: this.expectedRps() };
    if (this.inputMode() === 'spec') {
      if (!this.spec().trim()) return;
      input['spec'] = this.spec().trim();
    } else {
      if (!this.githubUrl().trim()) return;
      input['github_url'] = this.githubUrl().trim();
      if (this.branch().trim()) input['branch'] = this.branch().trim();
    }
    this.startRun(input);
  }

  recritique(): void {
    if (this.loading() || this.nodes().length === 0) return;
    const graph: ArchitectureGraph = {
      nodes: this.nodes().map(({ x: _x, y: _y, ...node }) => node),
      edges: this.edges(),
    };
    this.startRun({
      base_architecture: graph,
      expected_rps: this.whatIfRps(),
      spec: this.spec().trim() || undefined,
    });
  }

  private startRun(input: Record<string, unknown>): void {
    this.loading.set(true);
    this.progressMessage.set('Enviando para o agente arquiteto…');
    this.runsService.createRun('arquiteto', input).subscribe({
      next: run => this.watchRun(run.id),
      error: (err: unknown) => this.fail(err),
    });
  }

  private watchRun(runId: number): void {
    this.runsService.streamEvents(runId).subscribe({
      next: event => {
        this.progressMessage.set(event.message);
        if (event.kind === 'completed') {
          this.applyOutput(event.data as unknown as ArquitetoOutput);
        } else if (event.kind === 'failed') {
          this.loading.set(false);
          this.snackBar.open(event.message || 'Erro na análise de arquitetura.', 'Fechar', {
            duration: 6000,
            panelClass: ['snack-error'],
          });
        }
      },
      error: () => this.pollRun(runId),
    });
  }

  private pollRun(runId: number, attempt = 0): void {
    this.runsService.getRun(runId).subscribe({
      next: (run: AgentRun) => {
        if (run.status === 'completed') {
          this.applyOutput(run.output as unknown as ArquitetoOutput);
        } else if (run.status === 'failed' || run.status === 'cancelled') {
          this.loading.set(false);
          this.snackBar.open(run.error || 'Erro na análise.', 'Fechar', { duration: 6000 });
        } else if (attempt < 150) {
          setTimeout(() => this.pollRun(runId, attempt + 1), 2000);
        } else {
          this.loading.set(false);
        }
      },
      error: (err: unknown) => this.fail(err),
    });
  }

  private applyOutput(out: ArquitetoOutput): void {
    this.loading.set(false);
    if (!out?.architecture?.nodes?.length) {
      this.snackBar.open('O agente não retornou uma arquitetura válida.', 'Fechar', { duration: 5000 });
      return;
    }
    this.output.set(out);
    this.aiAnnotations.set(
      (out.annotations ?? []).filter(a => !['bottleneck', 'warning', 'spof'].includes(a.kind)),
    );
    this.whatIfRps.set(Math.round(out.nfrs.expected_rps * out.nfrs.peak_multiplier));
    this.layoutGraph(out.architecture);
    this.selectedNodeId.set(null);
    this.aiPanelOpen.set(false);
    this.snackBar.open('Arquitetura pronta — edite no canvas e reanalise.', '', {
      duration: 4000,
      panelClass: ['snack-success'],
    });
  }

  private fail(err: unknown, fallback = 'Erro ao consultar o agente arquiteto.'): void {
    this.loading.set(false);
    let msg = fallback;
    if (err instanceof HttpErrorResponse) {
      const d = err.error?.detail;
      if (typeof d === 'string') msg = d;
      else if (Array.isArray(d)) msg = d.map((x: { msg?: string }) => x.msg).filter(Boolean).join(' ') || msg;
    }
    this.snackBar.open(msg, 'Fechar', { duration: 6000, panelClass: ['snack-error'] });
  }

  // ------------------------------------------------------------ layout

  private layoutGraph(graph: ArchitectureGraph): void {
    const incoming = new Map<string, number>();
    for (const n of graph.nodes) incoming.set(n.id, 0);
    for (const e of graph.edges) incoming.set(e.to, (incoming.get(e.to) ?? 0) + 1);

    let entries = graph.nodes.filter(n => n.type === 'client' || n.type === 'external').map(n => n.id);
    if (entries.length === 0) {
      entries = graph.nodes.filter(n => (incoming.get(n.id) ?? 0) === 0).map(n => n.id);
    }
    if (entries.length === 0) entries = [graph.nodes[0].id];

    const layer = new Map<string, number>();
    const queue = entries.map(id => [id, 0] as [string, number]);
    while (queue.length > 0) {
      const [id, depth] = queue.shift()!;
      if (layer.has(id) && layer.get(id)! >= depth) continue;
      layer.set(id, depth);
      if (depth > graph.nodes.length) continue;
      for (const e of graph.edges.filter(e => e.from === id)) {
        queue.push([e.to, depth + 1]);
      }
    }

    const byLayer = new Map<number, string[]>();
    for (const n of graph.nodes) {
      const l = layer.get(n.id) ?? 0;
      if (!byLayer.has(l)) byLayer.set(l, []);
      byLayer.get(l)!.push(n.id);
    }

    const positioned: CanvasNode[] = graph.nodes.map(n => {
      const l = layer.get(n.id) ?? 0;
      const column = byLayer.get(l)!;
      const row = column.indexOf(n.id);
      const columnHeight = column.length * (NODE_H + 56);
      const yOffset = Math.max((640 - columnHeight) / 2, 24);
      return {
        ...n,
        props: { ...n.props },
        x: 40 + l * (NODE_W + 90),
        y: yOffset + row * (NODE_H + 56),
      };
    });
    this.nodes.set(positioned);
    this.edges.set(graph.edges.map(e => ({ ...e })));
  }

  // ------------------------------------------------------------ canvas

  nodeStyle(type: string): { icon: string; color: string; label: string } {
    return NODE_STYLE[type] ?? NODE_STYLE['service'];
  }

  nodeAnnotations(id: string): ArchAnnotation[] {
    return this.allAnnotations().filter(a => a.target === id);
  }

  worstSeverity(id: string): string | null {
    const anns = this.nodeAnnotations(id);
    if (anns.some(a => a.kind === 'bottleneck')) return 'bottleneck';
    if (anns.some(a => a.severity === 'high')) return 'high';
    if (anns.length > 0) return 'medium';
    return null;
  }

  loadOf(id: string): number | null {
    const v = this.localAnalysis().loads[id];
    return v === undefined ? null : Math.round(v);
  }

  edgePath(e: ArchEdge): string {
    const from = this.nodes().find(n => n.id === e.from);
    const to = this.nodes().find(n => n.id === e.to);
    if (!from || !to) return '';
    const x1 = from.x + NODE_W;
    const y1 = from.y + NODE_H / 2;
    const x2 = to.x;
    const y2 = to.y + NODE_H / 2;
    const dx = Math.max(Math.abs(x2 - x1) / 2, 40);
    return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
  }

  private svgPoint(event: PointerEvent): { x: number; y: number } {
    const svg = this.canvasSvg?.nativeElement;
    if (!svg) return { x: event.clientX, y: event.clientY };
    const rect = svg.getBoundingClientRect();
    const scaleX = 1200 / rect.width;
    const scaleY = 720 / rect.height;
    return { x: (event.clientX - rect.left) * scaleX, y: (event.clientY - rect.top) * scaleY };
  }

  onNodePointerDown(event: PointerEvent, node: CanvasNode): void {
    event.preventDefault();
    this.selectedNodeId.set(node.id);
    this.connectTargetId.set('');
    const p = this.svgPoint(event);
    this.dragging = { id: node.id, dx: p.x - node.x, dy: p.y - node.y };
    (event.target as Element).setPointerCapture?.(event.pointerId);
  }

  onCanvasPointerMove(event: PointerEvent): void {
    if (!this.dragging) return;
    const p = this.svgPoint(event);
    const { id, dx, dy } = this.dragging;
    this.nodes.update(list =>
      list.map(n => (n.id === id ? { ...n, x: Math.max(0, p.x - dx), y: Math.max(0, p.y - dy) } : n)),
    );
  }

  onCanvasPointerUp(): void {
    this.dragging = null;
  }

  // ------------------------------------------------------------ edição de nó

  updateSelected(field: 'label' | 'tech', value: string): void {
    const id = this.selectedNodeId();
    if (!id) return;
    this.nodes.update(list => list.map(n => (n.id === id ? { ...n, [field]: value } : n)));
  }

  updateSelectedType(value: string): void {
    const id = this.selectedNodeId();
    if (!id) return;
    this.nodes.update(list =>
      list.map(n => (n.id === id ? { ...n, type: value as ArchNodeType } : n)),
    );
  }

  updateSelectedProp(field: 'replicas' | 'rps_capacity', value: string): void {
    const id = this.selectedNodeId();
    if (!id) return;
    const num = Number(value);
    this.nodes.update(list =>
      list.map(n =>
        n.id === id
          ? { ...n, props: { ...n.props, [field]: Number.isFinite(num) && num > 0 ? num : undefined } }
          : n,
      ),
    );
  }

  removeSelected(): void {
    const id = this.selectedNodeId();
    if (!id) return;
    this.nodes.update(list => list.filter(n => n.id !== id));
    this.edges.update(list => list.filter(e => e.from !== id && e.to !== id));
    this.selectedNodeId.set(null);
  }

  onWhatIfInput(event: Event): void {
    this.whatIfRps.set(Number((event.target as HTMLInputElement).value) || 1);
  }

  // ------------------------------------------------------------ exports

  downloadAdr(): void {
    const out = this.output();
    if (!out) return;
    const blob = new Blob([out.adr_markdown], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'adr-arquitetura.md';
    a.click();
    URL.revokeObjectURL(url);
  }

  copyMermaid(): void {
    const lines = ['flowchart LR'];
    for (const n of this.nodes()) {
      const label = n.tech ? `${n.label}\\n${n.tech}` : n.label;
      lines.push(`    ${n.id}["${label}"]`);
    }
    for (const e of this.edges()) {
      lines.push(`    ${e.from} ${e.sync ? '-->' : '-.->'}|${e.protocol}| ${e.to}`);
    }
    void navigator.clipboard.writeText(lines.join('\n')).then(
      () => this.snackBar.open('Mermaid copiado.', '', { duration: 2500, panelClass: ['snack-success'] }),
      () => this.snackBar.open('Não foi possível copiar.', 'Fechar', { duration: 3500 }),
    );
  }
}
