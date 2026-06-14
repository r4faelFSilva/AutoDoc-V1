import { Component, OnDestroy, ElementRef, ViewChild, AfterViewInit, NgZone } from '@angular/core';

interface Dot {
  homeX: number;
  homeY: number;
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  opacity: number;
}

@Component({
  selector: 'app-particle-background',
  standalone: true,
  template: `<canvas #canvas></canvas>`,
  styles: [`
    canvas {
      position: fixed;
      inset: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      z-index: 0;
    }
  `],
})
export class ParticleBackgroundComponent implements AfterViewInit, OnDestroy {
  @ViewChild('canvas') private canvasRef!: ElementRef<HTMLCanvasElement>;

  private ctx!: CanvasRenderingContext2D;
  private dots: Dot[] = [];
  private mouse = { x: -9999, y: -9999 };
  private rafId = 0;
  private cleanupFns: Array<() => void> = [];

  constructor(private zone: NgZone) {}

  ngAfterViewInit(): void {
    const canvas = this.canvasRef.nativeElement;
    this.ctx = canvas.getContext('2d')!;
    this.setup(canvas);
    this.zone.runOutsideAngular(() => this.loop());
  }

  ngOnDestroy(): void {
    cancelAnimationFrame(this.rafId);
    this.cleanupFns.forEach(fn => fn());
  }

  private setup(canvas: HTMLCanvasElement): void {
    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      this.spawnDots(canvas);
    };

    const onMove = (e: MouseEvent) => {
      this.mouse.x = e.clientX;
      this.mouse.y = e.clientY;
    };

    const onLeave = () => {
      this.mouse.x = -9999;
      this.mouse.y = -9999;
    };

    resize();

    window.addEventListener('mousemove', onMove);
    window.addEventListener('resize', resize);
    document.addEventListener('mouseleave', onLeave);

    this.cleanupFns = [
      () => window.removeEventListener('mousemove', onMove),
      () => window.removeEventListener('resize', resize),
      () => document.removeEventListener('mouseleave', onLeave),
    ];
  }

  private spawnDots(canvas: HTMLCanvasElement): void {
    const count = Math.round((canvas.width * canvas.height) / 10000);
    this.dots = Array.from({ length: Math.min(count, 150) }, () => {
      const x = Math.random() * canvas.width;
      const y = Math.random() * canvas.height;
      return {
        homeX: x, homeY: y,
        x, y,
        vx: 0, vy: 0,
        radius: Math.random() * 1.8 + 0.4,
        opacity: Math.random() * 0.5 + 0.1,
      };
    });
  }

  private loop(): void {
    const canvas = this.canvasRef.nativeElement;
    const ctx = this.ctx;

    const MOUSE_RADIUS = 140;
    const REPEL = 7;
    const SPRING = 0.055;
    const DAMPING = 0.87;
    const LINE_DIST = 85;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const mx = this.mouse.x;
    const my = this.mouse.y;

    // Atualiza posições
    for (const d of this.dots) {
      const dx = d.x - mx;
      const dy = d.y - my;
      const dist = Math.sqrt(dx * dx + dy * dy);

      if (dist < MOUSE_RADIUS && dist > 0) {
        const force = (1 - dist / MOUSE_RADIUS) * REPEL;
        d.vx += (dx / dist) * force;
        d.vy += (dy / dist) * force;
      }

      // Mola: volta para posição original
      d.vx += (d.homeX - d.x) * SPRING;
      d.vy += (d.homeY - d.y) * SPRING;

      // Amortecimento
      d.vx *= DAMPING;
      d.vy *= DAMPING;

      d.x += d.vx;
      d.y += d.vy;
    }

    // Linhas entre pontos próximos
    ctx.lineWidth = 0.5;
    for (let i = 0; i < this.dots.length; i++) {
      for (let j = i + 1; j < this.dots.length; j++) {
        const a = this.dots[i];
        const b = this.dots[j];
        const dx = a.x - b.x;
        const dy = a.y - b.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < LINE_DIST) {
          ctx.beginPath();
          ctx.strokeStyle = `rgba(255,255,255,${(1 - dist / LINE_DIST) * 0.12})`;
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }
    }

    // Desenha pontos
    for (const d of this.dots) {
      ctx.beginPath();
      ctx.arc(d.x, d.y, d.radius, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(255,255,255,${d.opacity})`;
      ctx.fill();
    }

    this.rafId = requestAnimationFrame(() => this.loop());
  }
}
