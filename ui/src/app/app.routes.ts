import { Routes } from '@angular/router';
import { Shell } from './shell/shell';
import { TokensPage } from './pages/tokens/tokens-page';

/**
 * Hash routing: the server needs no rewrite rule, only the one document.
 *
 * Every page loads on first visit, so AG Grid reaches a browser only when a
 * table page is opened and the initial bundle stays the shell.
 */
export const routes: Routes = [
  {
    path: '',
    component: Shell,
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'config' },
      {
        path: 'config',
        loadComponent: () => import('./pages/config/config-page').then((m) => m.ConfigPage),
      },
      {
        path: 'settings',
        loadComponent: () => import('./pages/settings/settings-page').then((m) => m.SettingsPage),
      },
      { path: 'tokens', component: TokensPage },
      {
        path: 'loras',
        loadComponent: () => import('./pages/loras/loras-page').then((m) => m.LorasPage),
      },
      {
        path: 'editor',
        loadComponent: () => import('./pages/editor/editor-page').then((m) => m.EditorPage),
      },
      {
        path: 'assist',
        loadComponent: () => import('./pages/assist/assist-page').then((m) => m.AssistPage),
      },
      {
        path: 'catalog',
        loadComponent: () => import('./pages/catalog/catalog-page').then((m) => m.CatalogPage),
      },
      {
        path: 'import',
        loadComponent: () => import('./pages/import/import-page').then((m) => m.ImportPage),
      },
      {
        path: 'history',
        loadComponent: () => import('./pages/history/history-page').then((m) => m.HistoryPage),
      },
      {
        path: 'queue',
        loadComponent: () => import('./pages/queue/queue-page').then((m) => m.QueuePage),
      },
      {
        path: 'logs',
        loadComponent: () => import('./pages/logs/logs-page').then((m) => m.LogsPage),
      },
      { path: '**', redirectTo: 'config' },
    ],
  },
];
