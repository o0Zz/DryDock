import { api } from "./api";
import type { ConfirmOptions } from "./components/ConfirmDialog";
import { isActive, JOBS_CHANGED_EVENT } from "./hooks/useJobs";
import { translate } from "./i18n";
import type { Job, Project } from "./types";

type Confirm = (options: ConfirmOptions) => Promise<boolean>;

const POLL_MS = 1500;

/** Ask before deleting a stack. Resolves to null when cancelled. */
export async function askDelete(
  confirm: Confirm,
  project: Project,
): Promise<{ removeVolumes: boolean } | null> {
  // The dialog renders its message once, so the checkbox writes here.
  const choice = { removeVolumes: false };
  const accepted = await confirm({
    title: translate("Delete stack {name}?", { name: project.name }),
    message: (
      <>
        <p>
          {translate("DryDock runs")} <code>down</code>
          {translate(", backs the stack up to")} <code>/data/backups</code>
          {translate(
            ", then deletes it. A folder that holds only this stack goes as a whole, data folders included. In a shared folder only its Compose files go.",
          )}
        </p>
        <label className="checkbox-label">
          <input
            type="checkbox"
            onChange={(event) => {
              choice.removeVolumes = event.target.checked;
            }}
          />
          {/* One span: the label is a flex row, and loose text nodes would wrap apart. */}
          <span>
            {translate("Also remove its named volumes")} (<code>-v</code>).{" "}
            {translate("Their data is lost.")}
          </span>
        </label>
      </>
    ),
    confirmLabel: translate("Delete"),
    tone: "danger",
  });
  return accepted ? choice : null;
}

/** Ask for a new stack name. Resolves to null when cancelled. */
export async function askName(
  confirm: Confirm,
  options: { title: string; message: string; confirmLabel: string; initial: string },
): Promise<string | null> {
  const choice = { name: options.initial };
  const accepted = await confirm({
    title: options.title,
    message: (
      <>
        <p>{options.message}</p>
        <label className="field">
          {translate("New name (lowercase letters, digits, - and _)")}
          <input
            defaultValue={options.initial}
            autoFocus
            onChange={(event) => {
              choice.name = event.target.value;
            }}
          />
        </label>
      </>
    ),
    confirmLabel: options.confirmLabel,
  });
  const name = choice.name.trim();
  return accepted && name ? name : null;
}

/** Poll a job until it ends. Throws with the job's error when it fails. */
export async function waitForJob(job: Job): Promise<Job> {
  window.dispatchEvent(new Event(JOBS_CHANGED_EVENT));
  let current = job;
  while (isActive(current)) {
    await new Promise((resolve) => window.setTimeout(resolve, POLL_MS));
    current = await api.getJob(current.id);
  }
  if (current.status !== "success") {
    throw new Error(current.error ?? translate("{label} failed", { label: job.label }));
  }
  return current;
}
