import { Routes } from '@angular/router';
import { authGuard, guestGuard } from './core/guards/auth.guard';

export const routes: Routes = [
  { path: '', redirectTo: '/dashboard', pathMatch: 'full' },
  {
    path: 'login',
    loadComponent: () => import('./features/auth/login/login.component').then(m => m.LoginComponent),
    canActivate: [guestGuard],
  },
  {
    path: 'register',
    loadComponent: () => import('./features/auth/register/register.component').then(m => m.RegisterComponent),
    canActivate: [guestGuard],
  },
  {
    path: '',
    loadComponent: () => import('./layout/layout.component').then(m => m.LayoutComponent),
    canActivate: [authGuard],
    children: [
      {
        path: 'dashboard',
        loadComponent: () => import('./features/dashboard/dashboard.component').then(m => m.DashboardComponent),
      },
      {
        path: 'generate',
        loadComponent: () => import('./features/generate/generate.component').then(m => m.GenerateComponent),
      },
      {
        path: 'architect',
        loadComponent: () => import('./features/architect/architect.component').then(m => m.ArchitectComponent),
      },
      {
        path: 'templates',
        loadComponent: () => import('./features/templates/templates.component').then(m => m.TemplatesComponent),
      },
      {
        path: 'history',
        loadComponent: () => import('./features/history/history.component').then(m => m.HistoryComponent),
      },
      {
        path: 'history/:id',
        loadComponent: () => import('./features/documentation-viewer/documentation-viewer.component').then(m => m.DocumentationViewerComponent),
      },
      {
        path: 'search',
        loadComponent: () => import('./features/search/search.component').then(m => m.SearchComponent),
      },
    ],
  },
  { path: '**', redirectTo: '/dashboard' },
];
