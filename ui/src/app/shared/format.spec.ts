import { describe, expect, it } from 'vitest';
import { escapeHtml, graphSummary } from './format';

describe('graphSummary', () => {
  it('keeps the shape and drops the model ids', () => {
    expect(graphSummary('14 nodes · 1 LoRA (civitai:2795018@0.5) · 512×1024 · 20 steps · cfg 1')).toBe(
      '14 nodes · 1 LoRA · 512×1024',
    );
  });

  it('reads a missing graph as an empty line', () => {
    expect(graphSummary(undefined)).toBe('');
  });
});

describe('escapeHtml', () => {
  it('makes a quoted attribute inert', () => {
    expect(escapeHtml('x" onerror="alert(1)')).toBe('x&quot; onerror=&quot;alert(1)');
  });

  it('escapes the text delimiters', () => {
    expect(escapeHtml('<a & b>')).toBe('&lt;a &amp; b&gt;');
    expect(escapeHtml("it's")).toBe('it&#39;s');
  });
});
