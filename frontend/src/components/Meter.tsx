/** Thin usage bar; turns red at 80%. */
export default function Meter({ percent }: { percent: number }) {
  const clamped = Math.max(0, Math.min(100, percent));
  return (
    <div className={clamped >= 80 ? "meter hot" : "meter"}>
      <span style={{ width: `${clamped}%` }} />
    </div>
  );
}
