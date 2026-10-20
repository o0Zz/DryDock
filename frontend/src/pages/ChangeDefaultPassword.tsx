import { Anchor, LogOut } from "lucide-react";
import { useAuth } from "../auth";
import ChangePassword from "../components/ChangePassword";
import { useT } from "../i18n";

/** Shown instead of the app while the account still uses the default password. */
export default function ChangeDefaultPassword() {
  const { refresh, logout } = useAuth();
  const t = useT();
  return (
    <div className="login-screen">
      <div className="login-card">
        <div className="brand login-brand">
          <Anchor size={24} />
          DryDock
        </div>
        <p className="muted">
          {t(
            "This account still uses the default password, which anyone can guess. Choose a new one to continue.",
          )}
        </p>
        <ChangePassword onChanged={refresh} />
        <button type="button" className="secondary" onClick={() => logout()}>
          <LogOut size={15} /> {t("Sign out")}
        </button>
      </div>
    </div>
  );
}
