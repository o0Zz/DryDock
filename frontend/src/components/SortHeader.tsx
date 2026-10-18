import { ChevronDown, ChevronUp } from "lucide-react";
import type { ReactNode } from "react";
import type { Sorting } from "../hooks/useSort";

/** A table header you click to sort by its column; a second click reverses the order. */
export default function SortHeader<K extends string>({
  sorting,
  column,
  children,
}: {
  sorting: Sorting<K>;
  column: K;
  children: ReactNode;
}) {
  const { sort, toggle } = sorting;
  const active = sort?.column === column;
  const Arrow = sort?.descending ? ChevronDown : ChevronUp;
  return (
    <th aria-sort={active ? (sort.descending ? "descending" : "ascending") : undefined}>
      <button type="button" className="sort-header" onClick={() => toggle(column)}>
        {children}
        {active && <Arrow size={13} />}
      </button>
    </th>
  );
}
