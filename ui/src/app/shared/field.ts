import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input,
  output,
} from '@angular/core';

/**
 * One labelled control: a mono label above, the value below.
 *
 * The value is a plain string, so a page never has to hold a half-typed number
 * in a typed signal. The page copies it into its draft and posts it; the next
 * reply is what the page shows, unless the page is re-seeding the field.
 */
@Component({
  selector: 'app-field',
  changeDetection: ChangeDetectionStrategy.OnPush,
  // A field with no width takes the row's whole width. Binding the host style
  // unconditionally would set `--w: 0px` and collapse every such field.
  host: { '[style.--w.px]': 'w() || null' },
  template: `
    <div class="field">
      <label [attr.for]="fieldId()">{{ label() }}</label>
      @switch (kind()) {
        @case ('select') {
          <div class="select-wrap">
            <select
              [id]="fieldId()"
              class="select"
              [value]="value()"
              [disabled]="readonly()"
              [attr.aria-describedby]="hint() ? fieldId() + '-hint' : null"
              (change)="read($event)"
            >
              @for (option of options(); track option.value) {
                <option [value]="option.value">{{ option.label }}</option>
              }
            </select>
          </div>
        }
        @case ('textarea') {
          <textarea
            [id]="fieldId()"
            class="textarea"
            [class.mono]="mono()"
            [style.--rows]="rows()"
            [value]="value()"
            [placeholder]="placeholder()"
            [readOnly]="readonly()"
            [attr.aria-describedby]="hint() ? fieldId() + '-hint' : null"
            spellcheck="false"
            (input)="read($event)"
            (keydown)="onKey($event)"
          ></textarea>
        }
        @case ('password') {
          <input
            [id]="fieldId()"
            class="input"
            [class.mono]="mono()"
            type="password"
            [value]="value()"
            [placeholder]="placeholder()"
            [readOnly]="readonly()"
            [attr.aria-describedby]="hint() ? fieldId() + '-hint' : null"
            autocomplete="off"
            (input)="read($event)"
            (keydown)="onKey($event)"
          />
        }
        @default {
          <input
            [id]="fieldId()"
            class="input"
            [class.mono]="mono()"
            [type]="type()"
            [value]="value()"
            [placeholder]="placeholder()"
            [readOnly]="readonly()"
            [inputMode]="inputMode()"
            [attr.aria-describedby]="hint() ? fieldId() + '-hint' : null"
            [attr.autocomplete]="autocomplete()"
            [attr.spellcheck]="mono() ? 'false' : null"
            (input)="read($event)"
            (keydown)="onKey($event)"
          />
        }
      }
      @if (hint()) {
        <p class="hint" [id]="fieldId() + '-hint'">{{ hint() }}</p>
      }
    </div>
  `,
})
export class Field {
  readonly label = input.required<string>();
  /** The control's id, for a page that has two fields with one label. */
  readonly id = input('');
  readonly value = input<string>('');
  readonly kind = input<'text' | 'select' | 'textarea' | 'password'>('text');
  /** Any `type` a text input takes: number, url; ignored by the other kinds. */
  readonly type = input<string>('text');
  readonly inputMode = input<string | null>(null);
  readonly autocomplete = input<string>('off');
  readonly mono = input(false);
  readonly readonly = input(false);
  readonly rows = input(5);
  readonly placeholder = input('');
  readonly hint = input('');
  /** The width in pixels the prototype gives this control; 0 means fill the row. */
  readonly w = input(0);
  readonly options = input<readonly { value: string; label: string }[]>([]);
  readonly enter = input(false);

  readonly changed = output<string>();
  readonly submitted = output<void>();

  protected readonly fieldId = computed(() => this.id() || `f-${slug(this.label())}`);

  protected read(event: Event): void {
    this.changed.emit(read(event));
  }

  protected onKey(event: KeyboardEvent): void {
    if (event.key === 'Enter' && this.enter()) {
      event.preventDefault();
      this.submitted.emit();
    }
  }
}

function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

/** The value of an input, textarea or select; an event from anywhere else reads as "". */
export function read(event: Event): string {
  return (event.target as HTMLInputElement | null)?.value ?? '';
}

/** The checked state of a checkbox; an event from anywhere else reads as false. */
export function checked(event: Event): boolean {
  return (event.target as HTMLInputElement | null)?.checked ?? false;
}
