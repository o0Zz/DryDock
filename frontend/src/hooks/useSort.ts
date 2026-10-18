import { useEffect, useState } from "react";

export interface Sort<K extends string> {
  column: K;
  descending: boolean;
}

export interface Sorting<K extends string> {
  sort: Sort<K> | null;
  toggle: (column: K) => void;
}

type SortValue = string | number | null | undefined;

interface SortOptions<T, K extends string> {
  /** Remembers the order per table in this browser. */
  storageKey: string;
  /** Value to sort each column by. Ties fall back to the first column. */
  columns: Record<K, (row: T) => SortValue>;
  /** Without one, rows keep the order they came in until a header is clicked. */
  initial?: Sort<NoInfer<K>>;
  /** Columns whose first click sorts high to low (usage, counts, dates). */
  descendingFirst?: NoInfer<K>[];
  /** Rows of a lower group always come first, whatever the direction (folders before files). */
  group?: (row: T) => number;
}

function loadSort<K extends string>(storageKey: string, columns: string[]): Sort<K> | null {
  try {
    const saved = JSON.parse(window.localStorage.getItem(storageKey) ?? "null") as Sort<K> | null;
    if (saved && columns.includes(saved.column)) return saved;
  } catch {
    // storage blocked or bad value: default order
  }
  return null;
}

function compareValues(a: SortValue, b: SortValue): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

/** Click-to-sort state for a table, kept in localStorage. */
export function useSort<T, K extends string>(
  rows: T[] | null | undefined,
  { storageKey, columns, initial, descendingFirst = [], group }: SortOptions<T, K>,
): Sorting<K> & { rows: T[] } {
  const [sort, setSort] = useState<Sort<K> | null>(
    () => loadSort<K>(storageKey, Object.keys(columns)) ?? initial ?? null,
  );

  useEffect(() => {
    if (!sort) return;
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(sort));
    } catch {
      // storage blocked: the order just isn't remembered
    }
  }, [storageKey, sort]);

  const toggle = (column: K): void =>
    setSort((current) =>
      current?.column === column
        ? { column, descending: !current.descending }
        : { column, descending: descendingFirst.includes(column) },
    );

  if (!rows) return { sort, toggle, rows: [] };
  if (!sort) return { sort, toggle, rows };

  const value = columns[sort.column];
  const tieBreak = columns[Object.keys(columns)[0] as K];
  const direction = sort.descending ? -1 : 1;
  // Missing values (no stats yet, no Compose project) sort last in both directions.
  const compare = (a: T, b: T): number => {
    const left = value(a);
    const right = value(b);
    if (left == null || right == null) return left == null ? (right == null ? 0 : 1) : -1;
    return direction * compareValues(left, right);
  };
  const sorted = [...rows].sort(
    (a, b) =>
      (group ? group(a) - group(b) : 0) ||
      compare(a, b) ||
      compareValues(tieBreak(a), tieBreak(b)),
  );
  return { sort, toggle, rows: sorted };
}
