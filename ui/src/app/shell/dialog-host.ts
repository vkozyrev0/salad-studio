import { ChangeDetectionStrategy, Component, ElementRef, effect, inject } from '@angular/core';
import { StudioStore } from '../core/studio-store';

/**
 * The one dialog layer. It sits above the router outlet, so a dialog a page
 * opened survives the navigation that follows it: a refused save shows the
 * reason and only then moves the person to the page that fixes it.
 *
 * A confirm is a server-issued token, not a callback. Yes posts the token, so
 * it acts on the row that was selected when the dialog opened even if the
 * page has moved on since.
 */
@Component({
  selector: 'app-dialog-host',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '(document:keydown.escape)': 'escape()' },
  template: `
    @if (message(); as box) {
      <div class="scrim" role="presentation" (click)="store.dismissDialog()"></div>
      <div class="box" role="alertdialog" aria-modal="true" [attr.aria-labelledby]="'dialog-title'"
           aria-describedby="dialog-body" (keydown)="trap($event)">
        <div class="head">
          <span class="mark" [class.bad]="box.level === 'error'" aria-hidden="true"></span>
          <h2 id="dialog-title">{{ box.title }}</h2>
        </div>
        <p class="body" id="dialog-body">{{ box.body }}</p>
        <div class="foot">
          <button class="btn quiet" type="button" (click)="store.dismissDialog()" autofocus>OK</button>
        </div>
      </div>
    }
    @if (ask(); as box) {
      <div class="scrim" role="presentation" (click)="store.dismissConfirm()"></div>
      <div class="box" role="alertdialog" aria-modal="true" [attr.aria-labelledby]="'confirm-title'"
           aria-describedby="confirm-body" (keydown)="trap($event)">
        <div class="head">
          <span class="mark" aria-hidden="true"></span>
          <h2 id="confirm-title">{{ box.title }}</h2>
        </div>
        <p class="body" id="confirm-body">{{ box.body }}</p>
        <div class="foot">
          <button class="btn quiet" type="button" (click)="store.dismissConfirm()" autofocus>No</button>
          <button class="btn danger" type="button" (click)="store.confirmYes()">Yes</button>
        </div>
      </div>
    }
  `,
  styles: `
    .scrim {
      position: fixed; inset: 0; z-index: 40;
      background: rgb(10 16 23 / 0.62);
      backdrop-filter: blur(1.5px);
    }
    .box {
      position: fixed; z-index: 41;
      top: 50%; left: 50%;
      transform: translate(-50%, -50%);
      width: min(460px, calc(100vw - 32px));
      display: grid;
      gap: var(--space-md);
      padding: var(--space-lg);
      background: var(--surface);
      border: 1px solid var(--border);
      border-top: 2px solid var(--accent);
      border-radius: var(--radius-card);
      box-shadow: 0 18px 48px rgb(0 0 0 / 0.45);
    }
    .head { display: flex; align-items: baseline; gap: 10px; }
    .mark { width: 8px; height: 8px; border-radius: 1px; background: var(--accent); }
    .mark.bad { background: var(--invalid); }
    h2 { margin: 0; font-family: var(--font-display); font-size: 15px; font-weight: 600; }
    .body { margin: 0; color: var(--fg); font-size: 13px; line-height: 1.5; white-space: pre-wrap; }
    .foot { display: flex; justify-content: flex-end; gap: var(--space-sm); }
  `,
})
export class DialogHost {
  protected readonly store = inject(StudioStore);
  protected readonly message = this.store.dialog;
  protected readonly ask = this.store.confirm;
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  private opener: HTMLElement | null = null;
  private wasOpen = false;

  constructor() {
    effect(() => {
      const open = !!(this.message() || this.ask());
      if (open && !this.wasOpen) {
        this.wasOpen = true;
        this.opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        // The box is inserted after this signal change, so focus on the next turn.
        setTimeout(() => {
          this.host.nativeElement.querySelector<HTMLElement>('.box button')?.focus();
        });
      } else if (!open && this.wasOpen) {
        this.wasOpen = false;
        this.opener?.focus();
        this.opener = null;
      }
    });
  }

  protected escape(): void {
    this.store.dismissDialog();
    this.store.dismissConfirm();
  }

  /** Keep Tab inside the dialog: a delete confirm must not hand focus to the page behind it. */
  protected trap(event: KeyboardEvent): void {
    if (event.key !== 'Tab') return;
    const root = event.currentTarget as HTMLElement;
    const items = [...root.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')];
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
}
