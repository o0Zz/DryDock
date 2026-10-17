import { ArrowUpCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api";
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
  if (!update) return null;
  const details = `/containers/${container.id}?tab=updates`;

  if (update.newest_tag) {
    if (!project) {
      return (
        <Link to={details} className="badge paused" title="Newer version tag available — view details">
          <ArrowUpCircle size={12} /> {update.newest_tag}
        </Link>
      );
    }
    return (
      <Link
        to={`/projects/${project.id}?retag=${encodeURIComponent(container.image)}`}
        className="badge paused"
        title={`Newer version tag ${update.newest_tag} — open ${project.name}'s compose file to change the tag`}
      >
        <ArrowUpCircle size={12} /> {update.newest_tag}
      </Link>
    );
  }

  if (!update.update_available) return null;

  if (!container.compose_service) {
    return (
      <Link
        to={details}
        className="badge paused"
        title="Newer image available, but this container is not managed by Compose — view details"
      >
        <ArrowUpCircle size={12} /> update
      </Link>
    );
  }

  async function run() {
    const question =
      `Pull the latest ${container.image} and recreate ${container.name}?\n` +
      "The container restarts; data in volumes is kept.";
    if (!window.confirm(question)) return;
    try {
      onJob(await api.updateContainer(container.id));
    } catch (e) {
      onError((e as Error).message);
    }
  }

  return (
    <button
      type="button"
      className="badge paused badge-button"
      disabled={pending}
      title={`A newer ${container.image} was published — pull it and recreate ${container.name}`}
      onClick={run}
    >
      <ArrowUpCircle size={12} /> {pending ? "updating…" : "update"}
    </button>
  );
}
