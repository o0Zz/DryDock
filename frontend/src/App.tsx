import {
  Anchor,
  Container as ContainerIcon,
  HardDrive,
  Layers,
  LayoutDashboard,
  LogOut,
  Menu,
  Network,
  Boxes,
  Server,
  ScrollText,
  Settings as SettingsIcon,
  Users as UsersIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth";
import JobsIndicator from "./components/JobsIndicator";
import LanguagePicker from "./components/LanguagePicker";
import { useT } from "./i18n";
import ContainerDetail from "./pages/ContainerDetail";
import Containers from "./pages/Containers";
import Dashboard from "./pages/Dashboard";
import Host from "./pages/Host";
import Images from "./pages/Images";
import Login from "./pages/Login";
import Logs from "./pages/Logs";
import NewProject from "./pages/NewProject";
import Networks from "./pages/Networks";
import ProjectDetail from "./pages/ProjectDetail";
import Projects from "./pages/Projects";
import ChangeDefaultPassword from "./pages/ChangeDefaultPassword";
import Settings from "./pages/Settings";
import Users from "./pages/Users";
import VolumeFiles from "./pages/VolumeFiles";
import Volumes from "./pages/Volumes";

export default function App() {
  const { user, loading, logout } = useAuth();
  const t = useT();
  // Phone layout: the sidebar is a drawer, closed again after each navigation.
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setMenuOpen(false), [location.pathname]);

  if (loading) {
    return <div className="login-screen muted">{t("Loading…")}</div>;
  }

  if (!user) {
    return <Login />;
  }

  if (user.must_change_password) {
    return <ChangeDefaultPassword />;
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <button
            type="button"
            className="secondary small icon-only menu-toggle"
            aria-label={t("Menu")}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
          >
            <Menu size={18} />
          </button>
          <Anchor size={22} />
          DryDock <span className="version">v{__APP_VERSION__}</span>
        </div>
        <div className="topbar-user">
          <JobsIndicator />
          <LanguagePicker />
          <Link
            className="topbar-user-name"
            to="/settings?tab=account"
            title={t("Your password and API tokens")}
          >
            {user.username}
            {user.is_admin && <span className="badge admin-badge">admin</span>}
          </Link>
          <button className="secondary small" onClick={() => logout()}>
            <LogOut size={15} /> <span className="hide-narrow">{t("Sign out")}</span>
          </button>
        </div>
      </header>
      {menuOpen && <div className="sidebar-backdrop" onClick={() => setMenuOpen(false)} />}
      <aside className={menuOpen ? "sidebar open" : "sidebar"}>
        <nav>
          <NavLink to="/" end>
            <LayoutDashboard size={18} /> {t("Dashboard")}
          </NavLink>
          <NavLink to="/projects">
            <Boxes size={18} /> {t("Projects")}
          </NavLink>
          <NavLink to="/containers">
            <ContainerIcon size={18} /> {t("Containers")}
          </NavLink>
          <NavLink to="/volumes">
            <HardDrive size={18} /> {t("Volumes")}
          </NavLink>
          <NavLink to="/networks">
            <Network size={18} /> {t("Networks")}
          </NavLink>
          <NavLink to="/images">
            <Layers size={18} /> {t("Images")}
          </NavLink>
          <NavLink to="/host">
            <Server size={18} /> {t("Host")}
          </NavLink>
          <NavLink to="/settings">
            <SettingsIcon size={18} /> {t("Settings")}
          </NavLink>
          {user.is_admin && (
            <NavLink to="/logs">
              <ScrollText size={18} /> {t("Logs")}
            </NavLink>
          )}
          {user.is_admin && (
            <NavLink to="/users">
              <UsersIcon size={18} /> {t("Users")}
            </NavLink>
          )}
        </nav>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/projects" element={<Projects />} />
          <Route path="/projects/new" element={<NewProject />} />
          <Route path="/projects/:id" element={<ProjectDetail />} />
          <Route path="/containers" element={<Containers />} />
          <Route path="/containers/:id" element={<ContainerDetail />} />
          <Route path="/volumes" element={<Volumes />} />
          {user.is_admin && <Route path="/volumes/:name" element={<VolumeFiles />} />}
          <Route path="/networks" element={<Networks />} />
          <Route path="/images" element={<Images />} />
          <Route path="/scans" element={<Navigate to="/images" replace />} />
          <Route path="/host" element={<Host />} />
          <Route path="/settings" element={<Settings />} />
          {user.is_admin && <Route path="/logs" element={<Logs />} />}
          {user.is_admin && <Route path="/users" element={<Users />} />}
        </Routes>
      </main>
    </div>
  );
}
