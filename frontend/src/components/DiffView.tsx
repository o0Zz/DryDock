import { useMemo } from "react";
import { changesOnly, lineDiff } from "../lineDiff";

/** The changed lines of a file, with a little context; the whole file when too large. */
export default function DiffView({ before, after }: { before: string; after: string }) {
  const shown = useMemo(() => {
    const diff = lineDiff(before, after);
    return diff ? changesOnly(diff) : null;
  }, [before, after]);

  if (!shown) return <pre className="diff">{after}</pre>;
  return (
    <pre className="diff">
      {shown.map((line, index) =>
        line === null ? (
          <div key={index} className="diff-gap">
            ⋯
          </div>
        ) : (
          <div key={index} className={`diff-${line.kind}`}>
            {line.kind === "added" ? "+ " : line.kind === "removed" ? "- " : "  "}
            {line.text}
          </div>
        ),
      )}
    </pre>
  );
}
