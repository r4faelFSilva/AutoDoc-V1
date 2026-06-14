import { Component, OnInit, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subject, Subscription } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';
import { DocumentationService } from '../../core/services/documentation.service';
import { SearchResult } from '../../core/models/documentation.model';
import { HighlightPipe } from '../../shared/pipes/highlight.pipe';

@Component({
  selector: 'app-search',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, HighlightPipe],
  templateUrl: './search.component.html',
  styleUrls: ['./search.component.scss'],
})
export class SearchComponent implements OnInit {
  query = signal('');
  results = signal<SearchResult[]>([]);
  loading = signal(false);
  searched = signal(false);

  private searchSubject = new Subject<string>();
  private subs: Subscription[] = [];

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private docService: DocumentationService,
  ) {}

  ngOnInit(): void {
    const debounced = this.searchSubject.pipe(
      debounceTime(350),
      distinctUntilChanged(),
      switchMap(q => {
        if (q.trim().length < 2) {
          this.results.set([]);
          this.loading.set(false);
          this.searched.set(false);
          return [];
        }
        this.loading.set(true);
        return this.docService.search(q, 20);
      }),
    ).subscribe({
      next: res => {
        this.results.set(res);
        this.loading.set(false);
        this.searched.set(true);
      },
      error: () => this.loading.set(false),
    });
    this.subs.push(debounced);

    const qSub = this.route.queryParams.subscribe(params => {
      const q = params['q'] ?? '';
      this.query.set(q);
      if (q.trim().length >= 2) {
        this.loading.set(true);
        this.searchSubject.next(q);
      }
    });
    this.subs.push(qSub);
  }

  onInput(value: string): void {
    this.query.set(value);
    this.router.navigate([], { queryParams: { q: value }, replaceUrl: true });
    this.searchSubject.next(value);
  }

  formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short', year: 'numeric' });
  }

  ngOnDestroy(): void {
    this.subs.forEach(s => s.unsubscribe());
  }
}
