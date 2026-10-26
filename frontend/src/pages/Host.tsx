import { Copy, RefreshCw, ShieldBan } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import Fact from "../components/Fact";
import JobList from "../components/JobList";
import SortHeader from "../components/SortHeader";
import { formatDate, secondsSince } from "../format";
import { isActive, useJobs } from "../hooks/useJobs";
import { useSort } from "../hooks/useSort";
import { useT } from "../i18n";
import type { HostPackage, HostUpdates } from "../types";

// Package lists older than this mean the host no longer runs `apt update`.
const STALE_LISTS_DAYS = 7;

// Raspberry Pi's documented upgrade. Interactive: apt lists what it removes before asking.
const UPGRADE_COMMAND = "sudo apt update && sudo apt full-upgrade";
const AUTO_UPGRADES_COMMAND =
  "sudo apt install unattended-upgrades\nsudo dpkg-reconfigure -plow unattended-upgrades";

/** A shell command to run on the host, with a copy button. DryDock never runs it. */
function Command({ command }: { command: string }) {
  const t = useT();
  return (
    <div className="output padded">
      <div className="row-between">
        <pre style={{ margin: 0 }}>{command}</pre>
        <button
          type="button"
          className="secondary small"
          onClick={() => navigator.clipboard?.writeText(command)}
        >
          <Copy size={14} /> {t("Copy")}
        </button>
      </div>
    </div>
  );
}

function Updates({ updates }: { updates: HostUpdates | null }) {
  const t = useT();
  if (!updates) {
    return (
      <p className="muted">
        {t("Never checked. Use “Check updates”, or wait for the scheduled update check.")}
      </p>
    );
  }
  if (updates.error) {
    return <div className="error">{t("Last check failed: {error}", { error: updates.error })}</div>;
  }
  if (!updates.supported) {
    return (
      <p className="muted">
        {t("The host has no apt. Only Debian, Ubuntu and Raspberry Pi OS are supported.")}
      </p>
    );
  }
  const listsAge = secondsSince(updates.lists_updated_at);
  const stale = listsAge !== null && listsAge > STALE_LISTS_DAYS * 86_400;
  return (
    <>
      <ul className="fact-list">
        <Fact label={t("Pending updates")}>
          {updates.upgradable}{" "}
          {updates.security > 0 && (
            <span className="badge sev-critical">
              {t("{count} security", { count: updates.security })}
            </span>
          )}
        </Fact>
        <Fact label={t("Reboot required")}>
          {updates.reboot_required ? <span className="badge sev-high">{t("yes")}</span> : t("no")}
        </Fact>
        <Fact label={t("Package lists refreshed")}>
          {formatDate(updates.lists_updated_at, t("never"))}
          {stale && <span className="stat-detail-warn"> · {t("stale")}</span>}
        </Fact>
        {updates.auto_upgrades !== null && (
          <Fact label={t("Automatic security updates")}>
            {updates.auto_upgrades ? t("on") : <span className="badge sev-high">{t("off")}</span>}
          </Fact>
        )}
        <Fact label={t("Kernel")}>{updates.kernel ?? "—"}</Fact>
        <Fact label={t("Last check")}>{formatDate(updates.checked_at)}</Fact>
      </ul>
      {stale && (
        <p className="muted">
          {t("The host has not run")} <code>apt update</code>{" "}
          {t("for over {days} days, so this list may miss updates. Install", {
            days: STALE_LISTS_DAYS,
          })}{" "}
          <code>unattended-upgrades</code> {t("to refresh it daily.")}
        </p>
      )}
      {updates.upgradable > 0 && (
        <>
          <p className="muted">{t("To install them, run this on the host:")}</p>
          <Command command={UPGRADE_COMMAND} />
        </>
      )}
      {updates.reboot_required && (
        <>
          <p className="muted">{t("Then reboot the host to load the new kernel and libraries:")}</p>
          <Command command="sudo reboot" />
        </>
      )}
      {updates.auto_upgrades === false && (
        <>
          <p className="muted">
            {t(
              "Automatic updates are off. To install security updates every day, turn on unattended-upgrades:",
            )}
          </p>
          <Command command={AUTO_UPGRADES_COMMAND} />
        </>
      )}
      {updates.packages.length > 0 && <PackageTable packages={updates.packages} />}
    </>
  );
}

function PackageTable({ packages }: { packages: HostPackage[] }) {
  const t = useT();
  // No default: the server lists security updates first.
  const sorting = useSort(packages, {
    storageKey: "drydock.sort.host-packages",
    columns: {
      name: (pkg) => pkg.name,
    },
  });
  return (
    <table className="projects-table">
      <thead>
        <tr>
          <SortHeader sorting={sorting} column="name">
            {t("Package")}
          </SortHeader>
          <th>{t("Installed")}</th>
          <th>{t("Available")}</th>
        </tr>
      </thead>
      <tbody>
        {sorting.rows.map((pkg) => (
          <tr key={pkg.name}>
            <td>
              <span className="row-name">{pkg.name}</span>{" "}
              {pkg.security && <span className="badge sev-critical">{t("security")}</span>}
            </td>
            <td className="muted">{pkg.current}</td>
            <td>{pkg.candidate}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function Host() {
  const t = useT();
  const { user } = useAuth();
  const [updates, setUpdates] = useState<HostUpdates | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  const loadUpdates = useCallback((): void => {
    api
      .hostUpdates()
      .then(setUpdates)
      .catch((loadError: Error) => setError(loadError.message));
  }, []);

  useEffect(() => {
    loadUpdates();
  }, [loadUpdates]);

  const { jobs, start, dismiss } = useJobs(loadUpdates, setError);
  const checkJobs = jobs.filter((job) => job.kind === "host_update_check");
  const checking = checkJobs.some(isActive);

  return (
    <div>
      <div className="row-between">
        <h1>{t("Host")}</h1>
        <div className="button-row">
          <button type="button" disabled={checking} onClick={() => start(api.checkHostUpdates)}>
            <RefreshCw size={15} /> {t("Check updates")}
          </button>
        </div>
      </div>

      {error && <div className="error">{error}</div>}
      <JobList jobs={checkJobs} onDismiss={dismiss} />

      <section className="section">
        <h2>{t("OS updates")}</h2>
        {updates === undefined ? (
          <div className="empty">{t("Loading…")}</div>
        ) : (
          <Updates updates={updates} />
        )}
      </section>

      {user?.is_admin && (
        <p className="muted">
          <ShieldBan size={14} /> {t("fail2ban and the IP blocklist are on the Proxy page:")}{" "}
          <Link to="/proxy?tab=security">{t("Security")}</Link>
        </p>
      )}
    </div>
  );
}
