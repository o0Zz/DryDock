import { ArrowUpCircle, Download, GitCommitHorizontal, HardDrive, RotateCw } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { shortCommit } from "../format";
import { useT } from "../i18n";
import { useConfirm } from "./ConfirmDialog";
import type { Container, Job, Project, UpdateSummary } from "../types";

/**
 * One-click path to the newest image for a container.
 *
 * - Same tag rebuilt upstream (e.g. `latest`): pull it and recreate the
 *   container, as a background job.
 * - Pinned to a version with a newer tag out: open the Compose file with the
 *   tag change ready to review, since the file is what has to change.
 *
 * Renders nothing when the image is up to date or was never checked.
 */
export default function UpdateAction({
  container,
  update,
  project,
  pending = false,
  onJob,
  onError,
}: {
  container: Pick<Container, "id" | "name" | "image" | "compose_service">;
  update: UpdateSummary | undefined;
  project: Project | null | undefined;
  pending?: boolean;
  onJob: (job: Job) => void;
  onError: (message: string) => void;
}) {
  const confirm = useConfirm();
  const t = useT();
  if (!update) return null;
  const detailsUrl = `/containers/${container.id}?tab=updates`;

  if (update.newest_tag) {
    if (!project) {
      return (
        <Link to={detailsUrl} className="badge paused" title={t("Newer version tag available — view details")}>
          <ArrowUpCircle size={12} /> {update.newest_tag}
        </Link>
      );
    }
    return (
      <Link
        to={`/projects/${project.id}?retag=${encodeURIComponent(container.image)}`}
        className="badge paused"
        title={t("Newer version tag {tag} — open {project}'s compose file to change the tag", {
          tag: update.newest_tag,
          project: project.name,
        })}
      >
        <ArrowUpCircle size={12} /> {update.newest_tag}
      </Link>
    );
  }

  if (!update.update_available) return null;

  if (!container.compose_service) {
    return (
      <Link
        to={detailsUrl}
        className="badge paused"
        title={t(
          "Newer image available, but this container is not managed by Compose — view details",
        )}
      >
        <ArrowUpCircle size={12} /> {t("update")}
      </Link>
    );
  }

  // Built from git: the update is a new commit, and the job rebuilds the image.
  const gitSource = update.git_source;

  async function run(): Promise<void> {
    // The image name or the repo is set in <code> wherever the translation puts it.
    const [before, after = ""] = gitSource
      ? t("A new commit is on {source}.").split("{source}")
      : t("A newer {image} was published.").split("{image}");
    const confirmed = await confirm({
      title: t("Update {name}?", { name: container.name }),
      icon: ArrowUpCircle,
      confirmLabel: gitSource ? t("Rebuild & recreate") : t("Pull & recreate"),
      message: (
        <>
          <p>
            {before}
            <code>{gitSource ?? container.image}</code>
            {after}
          </p>
          <ol className="confirm-steps">
            <li>
              {gitSource ? (
                <>
                  <GitCommitHorizontal size={15} />{" "}
                  {t("Rebuild the image from commit {commit}", {
                    commit: shortCommit(update?.remote_digest),
                  })}
                </>
              ) : (
                <>
                  <Download size={15} /> {t("Pull the new image")}
                </>
              )}
            </li>
            <li>
              <RotateCw size={15} /> {t("Recreate the container (brief downtime)")}
            </li>
            <li>
              <HardDrive size={15} /> {t("Volumes and their data are kept")}
            </li>
          </ol>
        </>
      ),
    });
    if (!confirmed) return;
    try {
      onJob(await api.updateContainer(container.id));
    } catch (error) {
      onError((error as Error).message);
    }
  }

  return (
    <button
      type="button"
      className="badge paused badge-button"
      disabled={pending}
      title={
        gitSource
          ? t("New commit on {source} — rebuild and recreate {name}", {
              source: gitSource,
              name: container.name,
            })
          : t("A newer {image} was published — pull it and recreate {name}", {
              image: container.image,
              name: container.name,
            })
      }
      onClick={run}
    >
      <ArrowUpCircle size={12} /> {pending ? t("updating…") : t("update")}
    </button>
  );
}
