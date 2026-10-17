import {
  Anchor,
  Container as ContainerIcon,
  HardDrive,
  Layers,
  LayoutDashboard,
  LogOut,
  Network,
  Boxes,
  Server,
  ScrollText,
  Settings as SettingsIcon,
  Users as UsersIcon,
} from "lucide-react";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import JobsIndicator from "./components/JobsIndicator";
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
import Settings from "./pages/Settings";
import Users from "./pages/Users";
import VolumeFiles from "./pages/VolumeFiles";
import Volumes from "./pages/Volumes";

export default function App() {
  const { user, loading, logout } = useAuth();

  if (loading) {
    return <div className="login-screen muted">Loading…</div>;
  }

  if (!user) {
    return <Login />;
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <Anchor size={22} />
          DryDock <span className="version">v{__APP_VERSION__}</span>
        </div>
        <div className="topbar-user">
          <JobsIndicator />
          <span className="topbar-user-name">
            {user.username}
            {user.is_admin && <span className="badge admin-badge">admin</span>}
          </span>
          <button className="secondary small" onClick={() => logout()}>
            <LogOut size={15} /> Sign out
          </button>
        </div>
      </header>
      <aside className="sidebar">
        <nav>
          <NavLink to="/" end>
            <LayoutDashboard size={18} /> Dashboard
          </NavLink>
          <NavLink to="/projects">
            <Boxes size={18} /> Projects
          </NavLink>
          <NavLink to="/containers">
            <ContainerIcon size={18} /> Containers
          </NavLink>
          <NavLink to="/volumes">
            <HardDrive size={18} /> Volumes
          </NavLink>
          <NavLink to="/networks">
            <Network size={18} /> Networks
          </NavLink>
          <NavLink to="/images">
            <Layers size={18} /> Images
          </NavLink>
          <NavLink to="/host">
            <Server size={18} /> Host
          </NavLink>
          <NavLink to="/settings">
            <SettingsIcon size={18} /> Settings
          </NavLink>
          {user.is_admin && (
            <NavLink to="/logs">
              <ScrollText size={18} /> Logs
            </NavLink>
          )}
          {user.is_admin && (
            <NavLink to="/users">
              <UsersIcon size={18} /> Users
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
