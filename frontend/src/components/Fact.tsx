import type { ReactNode } from "react";

/** One row of a `.fact-list`: a muted label, then the value. */
export default function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <li>
      <span className="muted">{label}</span>
      <strong>{children}</strong>
    </li>
  );
}
