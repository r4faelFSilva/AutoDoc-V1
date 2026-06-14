import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { DocumentationService } from '../../core/services/documentation.service';
import { TemplateService } from '../../core/services/template.service';
import { DashboardStats } from '../../core/models/documentation.model';
import { SkeletonComponent } from '../../shared/components/skeleton/skeleton.component';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, RouterLink, SkeletonComponent],
  templateUrl: './dashboard.component.html',
  styleUrls: ['./dashboard.component.scss'],
})
export class DashboardComponent implements OnInit {
  stats = signal<DashboardStats | null>(null);
  loading = signal(true);

  quickActions = [
    { label: 'Nova Documentação', icon: 'auto_awesome', path: '/generate', accent: true },
    { label: 'Ver Histórico', icon: 'history', path: '/history', accent: false },
    { label: 'Gerenciar Templates', icon: 'description', path: '/templates', accent: false },
  ];

  constructor(private docService: DocumentationService) {}

  ngOnInit(): void {
    this.docService.getStats().subscribe(s => {
      this.stats.set(s);
      this.loading.set(false);
    });
  }

  formatDate(date: string): string {
    return new Date(date).toLocaleDateString('pt-BR', {
      day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  }
}
