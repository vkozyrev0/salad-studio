import { Field } from './field';
import { DataGrid, numeric } from './data-grid';

/** Import this one array into a standalone page's `imports` to get the shared controls. */
export const SHARED = [Field, DataGrid] as const;

export { Field, DataGrid, numeric };
