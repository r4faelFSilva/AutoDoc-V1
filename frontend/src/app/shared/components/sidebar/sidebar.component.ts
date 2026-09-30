import { Component, signal, OnDestroy, HostListener, ElementRef } from '@angular/core';
import { RouterLink, RouterLinkActive, Router } from '@angular/router';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Subject, Subscription } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';
import { AuthService } from '../../../core/services/auth.service';
import { DocumentationService } from '../../../core/services/documentation.service';
import { SearchResult } from '../../../core/models/documentation.model';
import { HighlightPipe } from '../../pipes/highlight.pipe';

interface NavItem {
  path: string;
  label: string;
  icon: string;
}

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, RouterLinkActive, MatTooltipModule, HighlightPipe],
  templateUrl: './sidebar.component.html',
  styleUrls: ['./sidebar.component.scss'],
})
export class SidebarComponent implements OnDestroy {
  collapsed = signal(false);
  searchQuery = signal('');
  suggestions = signal<SearchResult[]>([]);
  searching = signal(false);
  showDropdown = signal(false);

  navItems: NavItem[] = [
    { path: '/dashboard', label: 'Dashboard', icon: 'grid_view' },
    { path: '/generate', label: 'Gerar Doc', icon: 'auto_awesome' },
    { path: '/architect', label: 'Arquitetura', icon: 'account_tree' },
    { path: '/history', label: 'Histórico', icon: 'history' },
    { path: '/templates', label: 'Templates', icon: 'description' },
  ];

  private searchSubject = new Subject<string>();
  private sub: Subscription;

  constructor(
    private auth: AuthService,
    private docService: DocumentationService,
    private router: Router,
    private elRef: ElementRef,
  ) {
    this.sub = this.searchSubject.pipe(
      debounceTime(300),
      distinctUntilChanged(),
      switchMap(q => {
        if (q.trim().length < 2) {
          this.suggestions.set([]);
          this.searching.set(false);
          return [];
        }
        this.searching.set(true);
        return this.docService.search(q, 6);
      }),
    ).subscribe({
      next: results => {
        this.suggestions.set(results);
        this.searching.set(false);
        this.showDropdown.set(true);
      },
      error: () => this.searching.set(false),
    });
  }

  onSearchInput(value: string): void {
    this.searchQuery.set(value);
    if (value.trim().length < 2) {
      this.suggestions.set([]);
      this.showDropdown.set(false);
      return;
    }
    this.searchSubject.next(value);
  }

  onSearchKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && this.searchQuery().trim().length >= 2) {
      this.navigateToSearch();
    } else if (event.key === 'Escape') {
      this.showDropdown.set(false);
    }
  }

  selectSuggestion(result: SearchResult): void {
    this.showDropdown.set(false);
    this.router.navigate(['/history', result.id], {
      queryParams: { highlight: this.searchQuery() },
    });
  }

  navigateToSearch(): void {
    const q = this.searchQuery().trim();
    if (!q) return;
    this.showDropdown.set(false);
    this.router.navigate(['/search'], { queryParams: { q } });
  }

  clearSearch(): void {
    this.searchQuery.set('');
    this.suggestions.set([]);
    this.showDropdown.set(false);
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    if (!this.elRef.nativeElement.contains(event.target)) {
      this.showDropdown.set(false);
    }
  }

  toggleCollapsed(): void {
    this.collapsed.update(v => !v);
    if (this.collapsed()) {
      this.showDropdown.set(false);
    }
  }

  logout(): void {
    this.auth.logout();
  }

  ngOnDestroy(): void {
    this.sub.unsubscribe();
  }
}
