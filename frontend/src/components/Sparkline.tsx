const WIDTH = 80;
const HEIGHT = 18;

/** Trend of recent values, 0 at the bottom. Turns red with `hot`, like Meter. */
export default function Sparkline({
  values,
  floor = 0,
  hot = false,
  label,
}: {
  values: number[];
  /** Smallest top of the scale, so near-idle noise stays flat. */
  floor?: number;
  hot?: boolean;
  /** Tooltip text. */
  label: string;
}) {
  if (values.length < 2) return <div className="sparkline" />;
  // Headroom above the peak: a steady value reads as steady, not as maxed out.
  const top = Math.max(floor, ...values) * 1.2 || 1;
  const step = WIDTH / (values.length - 1);
  // 1px inset so a flat line at 0 or at the top is not cut by the edge.
  const points = values
    .map((value, index) => `${index * step},${1 + (1 - value / top) * (HEIGHT - 2)}`)
    .join(" ");
  return (
    <svg
      className={hot ? "sparkline hot" : "sparkline"}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={label}
    >
      <title>{label}</title>
      <polyline points={points} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
