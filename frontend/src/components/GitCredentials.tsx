import { api } from "../api";
import { useT } from "../i18n";
import type { GitCredential } from "../types";
import LoginTable, { type StoredLogin } from "./LoginTable";

function toLogin(credential: GitCredential): StoredLogin {
  return { id: credential.host, host: credential.host, username: credential.username };
}

// Outside the component: LoginTable reloads when `list` changes.
async function list(): Promise<StoredLogin[]> {
  return (await api.listGitCredentials()).map(toLogin);
}

/** Git logins for private repos: builds, update checks, push and pull (admin only). */
export default function GitCredentials() {
  const t = useT();
  return (
    <LoginTable
      title={t("Git logins")}
      description={t(
        "Used for private git repos over https: builds from a git URL, their update checks, and push and pull of the repo folder. Enter a repo URL to check the login before it is saved, or only a host. Use an access token instead of a password.",
      )}
      hostLabel={t("Repo URL or host")}
      hostPlaceholder="https://github.com/me/app.git, git.lan:3000"
      list={list}
      add={async ({ host, username, secret }) =>
        toLogin(await api.addGitCredential(host, username, secret))
      }
      update={async (login, { host, username, secret }) =>
        toLogin(await api.updateGitCredential(login.id, host, username, secret))
      }
      remove={(login) => api.removeGitCredential(login.id)}
      removeTitle={(login) => t("Remove the git login for {host}?", { host: login.id })}
      removeMessage={t("Builds, update checks, pushes and pulls of its private repos will fail.")}
      savedNotice={(login) =>
        t("Saved the git login for {host} ({username}).", {
          host: login.host,
          username: login.username,
        })
      }
    />
  );
}
