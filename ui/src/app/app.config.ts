import { ApplicationConfig, inject, provideAppInitializer, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { provideRouter, withHashLocation } from '@angular/router';
import { routes } from './app.routes';
import { StudioStore } from './core/studio-store';
import { RouteSync } from './core/route-sync';
import { AllCommunityModule, ModuleRegistry } from 'ag-grid-community';

// AG Grid 36 ships its features as modules and registers none by default. The
// community set is everything the studio's four grids use.
ModuleRegistry.registerModules([AllCommunityModule]);

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideHttpClient(),
    provideRouter(routes, withHashLocation()),
    // The stream opens before the first page asks for state, so the first
    // `hello` and the first page fetch agree on what the server is showing.
    provideAppInitializer(() => {
      inject(RouteSync).start();
      inject(StudioStore).connect();
    }),
  ],
};
