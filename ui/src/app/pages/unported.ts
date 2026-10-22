import { ChangeDetectionStrategy, Component } from '@angular/core';
import { PageFrame } from '../shell/page-frame';

/**
 * A page that has not been through the port yet. It says so plainly instead of
 * showing the last page's body, which would read as a page that failed.
 *
 * One route per unported page points at this component directly. A single
 * parameterised route would keep one instance across page hops, and the page
 * would keep reporting the head of the first one.
 */
@Component({
  selector: 'app-unported',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PageFrame],
  template: `
    <app-page-frame>
      <div class="empty">
        <p class="lead">This page has not moved to the web build yet.</p>
        <p class="detail">
          The server has no controller for it yet. The pages in the rail are the
          ones this build serves.
        </p>
      </div>
    </app-page-frame>
  `,
  styles: `
    :host { display: block; height: 100%; }
    .empty {
      display: grid;
      gap: var(--space-sm);
      max-width: 56ch;
      padding: var(--space-xl) var(--space-lg);
      border: 1px dashed var(--rule);
      border-radius: var(--radius-card);
    }
    .lead { margin: 0; font-family: var(--font-display); font-size: 20px; color: var(--fg); }
    .detail { margin: 0; font-size: 12.5px; color: var(--fg-muted); }
  `,
})
export class UnportedPage {}
