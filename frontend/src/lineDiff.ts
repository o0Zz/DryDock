export interface DiffLine {
  kind: "same" | "added" | "removed";
  text: string;
}

// Above this many line pairs the table would cost too much memory on a phone.
const MAX_CELLS = 4_000_000;

/** Line diff of two texts (longest common subsequence), or null when too large. */
export function lineDiff(before: string, after: string): DiffLine[] | null {
  const a = before.replace(/\n$/, "").split("\n");
  const b = after.replace(/\n$/, "").split("\n");
  if (a.length * b.length > MAX_CELLS) return null;

  // lengths[i][j]: common lines of a[i..] and b[j..], flattened.
  const width = b.length + 1;
  const lengths = new Uint32Array((a.length + 1) * width);
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lengths[i * width + j] =
        a[i] === b[j]
          ? lengths[(i + 1) * width + j + 1] + 1
          : Math.max(lengths[(i + 1) * width + j], lengths[i * width + j + 1]);
    }
  }

  const lines: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      lines.push({ kind: "same", text: a[i] });
      i++;
      j++;
    } else if (lengths[(i + 1) * width + j] >= lengths[i * width + j + 1]) {
      lines.push({ kind: "removed", text: a[i++] });
    } else {
      lines.push({ kind: "added", text: b[j++] });
    }
  }
  while (i < a.length) lines.push({ kind: "removed", text: a[i++] });
  while (j < b.length) lines.push({ kind: "added", text: b[j++] });
  return lines;
}

/** The changed lines with `context` unchanged lines around each change; null marks a gap. */
export function changesOnly(lines: DiffLine[], context = 2): (DiffLine | null)[] {
  const keep = lines.map(() => false);
  lines.forEach((line, index) => {
    if (line.kind === "same") return;
    for (let k = Math.max(0, index - context); k <= Math.min(lines.length - 1, index + context); k++) {
      keep[k] = true;
    }
  });
  const shown: (DiffLine | null)[] = [];
  lines.forEach((line, index) => {
    if (keep[index]) shown.push(line);
    else if (shown.length > 0 && shown[shown.length - 1] !== null) shown.push(null);
  });
  if (shown[shown.length - 1] === null) shown.pop();
  return shown;
}
