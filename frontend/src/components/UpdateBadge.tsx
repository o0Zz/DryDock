import { ArrowUpCircle, CheckCircle2 } from "lucide-react";
import type { UpdateSummary } from "../types";

/** Compact "is a newer image available" status for one image. */
export default function UpdateBadge({ update }: { update: UpdateSummary | undefined }) {
  if (!update) return <span className="muted">not checked</span>;
  const checked = new Date(update.checked_at).toLocaleString();
  // A newer version tag wins over digest status: it is what a pinned tag needs,
  // and it is known even when the image is not pulled locally.
  if (update.newest_tag) {
    const lines = [`Checked ${checked}`, `Newest tag: ${update.newest_tag}`];
    if (update.newest_same_major_tag) {
      lines.push(`Newest in current major: ${update.newest_same_major_tag}`);
    }
    if (update.update_available) lines.push("Current tag was also rebuilt (run pull).");
    lines.push("Change the image tag in the compose file to upgrade.");
    return (
      <span className="badge paused" title={lines.join("\n")}>
        <ArrowUpCircle size={12} /> {update.newest_tag}
        {update.newest_same_major_tag && ` · ${update.newest_same_major_tag}`}
      </span>
    );
  }
  if (update.error) {
    return (
      <span className="badge" title={update.error}>
        unknown
      </span>
    );
  }
  if (!update.update_available) {
    const tagNote = update.tag_error
      ? `\nTag check failed: ${update.tag_error}`
      : "\nNo newer version tag found.";
    return (
      <span className="badge running" title={`Checked ${checked}${tagNote}`}>
        <CheckCircle2 size={12} /> up to date
      </span>
    );
  }
  return (
    <span
      className="badge paused"
      title={
        `Checked ${checked}\nlocal  ${update.local_digest}\n` +
        `remote ${update.remote_digest}\nSame tag was rebuilt. Run "pull" on the project to update.`
      }
    >
      <ArrowUpCircle size={12} /> available
    </span>
  );
}
