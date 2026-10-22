import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
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
  host: { '(keydown.escape)': 'escape()' },
  template: `
    @if (message(); as box) {
      <div class="scrim" role="presentation" (click)="store.dismissDialog()"></div>
      <div class="box" role="alertdialog" aria-modal="true" [attr.aria-labelledby]="'dialog-title'">
        <div class="head">
          <span class="mark" [class.bad]="box.level === 'error'" aria-hidden="true"></span>
          <h2 id="dialog-title">{{ box.title }}</h2>
        </div>
        <p class="body">{{ box.body }}</p>
        <div class="foot">
          <button class="quiet" type="button" (click)="store.dismissDialog()" autofocus>OK</button>
        </div>
      </div>
    }
    @if (ask(); as box) {
      <div class="scrim" role="presentation" (click)="store.dismissConfirm()"></div>
      <div class="box" role="alertdialog" aria-modal="true" [attr.aria-labelledby]="'confirm-title'">
        <div class="head">
          <span class="mark" aria-hidden="true"></span>
          <h2 id="confirm-title">{{ box.title }}</h2>
        </div>
        <p class="body">{{ box.body }}</p>
        <div class="foot">
          <button class="quiet" type="button" (click)="store.dismissConfirm()" autofocus>No</button>
          <button class="danger" type="button" (click)="store.confirmYes()">Yes</button>
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
    button {
      font-family: var(--font-display);
      font-size: 13px;
      padding: 6px 14px;
      border-radius: var(--radius-control);
      cursor: pointer;
    }
    .quiet { background: transparent; border: 1px solid var(--border); color: var(--fg); }
    .quiet:hover { border-color: var(--fg-muted); }
    .danger { background: var(--invalid); border: 1px solid var(--invalid); color: var(--bg); font-weight: 600; }
    .danger:hover { filter: brightness(1.08); }
  `,
})
export class DialogHost {
  protected readonly store = inject(StudioStore);
  protected readonly message = this.store.dialog;
  protected readonly ask = this.store.confirm;

  protected escape(): void {
    this.store.dismissDialog();
    this.store.dismissConfirm();
  }
}
