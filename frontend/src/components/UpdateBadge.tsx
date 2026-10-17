import { ArrowUpCircle, CheckCircle2 } from "lucide-react";
import { formatDate } from "../format";
import { useT } from "../i18n";
import type { UpdateSummary } from "../types";

/** Either kind of update: same tag rebuilt, or a newer version tag (as UpdateCheck.has_update). */
export function hasUpdate(update: UpdateSummary | null | undefined): boolean {
  return !!update && (update.update_available || !!update.newest_tag);
}

/** Compact "is a newer image available" status for one image. */
export default function UpdateBadge({ update }: { update: UpdateSummary | undefined }) {
  const t = useT();
  if (!update) return <span className="muted">{t("not checked")}</span>;
  const checked = formatDate(update.checked_at);
  // A newer version tag wins over digest status: it is what a pinned tag needs,
  // and it is known even when the image is not pulled locally.
  if (update.newest_tag) {
    const lines = [
      t("Checked {date}", { date: checked }),
      t("Newest tag: {tag}", { tag: update.newest_tag }),
    ];
    if (update.newest_same_major_tag) {
      lines.push(t("Newest in current major: {tag}", { tag: update.newest_same_major_tag }));
    }
    if (update.update_available) lines.push(t("Current tag was also rebuilt (run pull)."));
    lines.push(t("Change the image tag in the compose file to upgrade."));
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
        {t("unknown")}
      </span>
    );
  }
  if (!update.update_available) {
    const tagNote = update.tag_error
      ? t("Tag check failed: {error}", { error: update.tag_error })
      : t("No newer version tag found.");
    return (
      <span
        className="badge running"
        title={`${t("Checked {date}", { date: checked })}\n${tagNote}`}
      >
        <CheckCircle2 size={12} /> {t("up to date")}
      </span>
    );
  }
  return (
    <span
      className="badge paused"
      title={[
        t("Checked {date}", { date: checked }),
        t("local  {digest}", { digest: update.local_digest ?? "" }),
        t("remote {digest}", { digest: update.remote_digest ?? "" }),
        t('Same tag was rebuilt. Run "pull" on the project to update.'),
      ].join("\n")}
    >
      <ArrowUpCircle size={12} /> {t("available")}
    </span>
  );
}
