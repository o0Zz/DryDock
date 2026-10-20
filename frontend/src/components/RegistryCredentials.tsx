import { api } from "../api";
import { useT } from "../i18n";
import LoginTable, { type StoredLogin } from "./LoginTable";

const DOCKER_HUB_KEY = "https://index.docker.io/v1/";

function label(registry: string): string {
  return registry === DOCKER_HUB_KEY ? "Docker Hub" : registry;
}

// Outside the component: LoginTable reloads when `list` changes.
async function list(): Promise<StoredLogin[]> {
  return (await api.listRegistries()).map((credential) => ({
    id: credential.registry,
    // What the field takes back: `docker.io` rather than Docker Hub's config key.
    host: credential.registry === DOCKER_HUB_KEY ? "docker.io" : credential.registry,
    username: credential.username,
  }));
}

function toLogin(registry: string, username: string): StoredLogin {
  return { id: registry, host: registry, username };
}

/** Registry logins for update checks, pulls and scans of private images (admin only). */
export default function RegistryCredentials() {
  const t = useT();
  return (
    <LoginTable
      title={t("Registry credentials")}
      description={t(
        "Used for update checks, pulls and scans of private images. DryDock checks a login with the registry before it saves it. Use an access token instead of a password where the registry offers one.",
      )}
      hostLabel={t("Registry")}
      hostPlaceholder="docker.io, ghcr.io, registry.lan:5000"
      list={list}
      add={async ({ host, username, secret }) => {
        const saved = await api.addRegistry(host, username, secret);
        return toLogin(saved.registry, saved.username);
      }}
      update={async (login, { host, username, secret }) => {
        const saved = await api.updateRegistry(login.id, host, username, secret);
        return toLogin(saved.registry, saved.username);
      }}
      remove={(login) => api.removeRegistry(login.id)}
      removeTitle={(login) => t("Remove the login for {registry}?", { registry: label(login.id) })}
      removeMessage={t("Update checks, pulls and scans of its private images will fail.")}
      savedNotice={(login) =>
        t("Logged in to {registry} as {username}.", {
          registry: label(login.id),
          username: login.username,
        })
      }
    />
  );
}
