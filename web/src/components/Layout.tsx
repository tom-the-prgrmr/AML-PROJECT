import { useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  IconBenchmark,
  IconBrand,
  IconCases,
  IconDataQuality,
  IconMetrics,
  IconScreening,
  IconSystem,
} from "./icons";
import UserSwitch from "./UserSwitch";
import "./Layout.css";

const PRODUCT = "AML – Bàn điều tra";

const MENU: { to: string; label: string; icon: ReactNode }[] = [
  { to: "/cases", label: "Hàng đợi case", icon: <IconCases /> },
  { to: "/screening", label: "Rà soát screening", icon: <IconScreening /> },
  { to: "/data-quality", label: "Chất lượng dữ liệu", icon: <IconDataQuality /> },
  { to: "/benchmark", label: "Benchmark", icon: <IconBenchmark /> },
  { to: "/metrics", label: "Chỉ số", icon: <IconMetrics /> },
  { to: "/system", label: "Hệ thống", icon: <IconSystem /> },
];

/** Where the user is: the menu section, plus the item inside it (a case id) when there is one. */
function Context() {
  const { pathname } = useLocation();
  const section = MENU.find((m) => pathname === m.to || pathname.startsWith(`${m.to}/`));
  const item = section ? decodeURIComponent(pathname.slice(section.to.length + 1)) : "";
  return (
    <p className="topbar-context">
      <span className="muted">{PRODUCT}</span>
      {section && <span className="topbar-section">{section.label}</span>}
      {item && <span className="code">{item}</span>}
    </p>
  );
}

export default function Layout() {
  // Bumping this key remounts the page, so its data reloads for the new user.
  const [userVersion, setUserVersion] = useState(0);
  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Bỏ qua điều hướng, tới nội dung chính
      </a>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <IconBrand />
          </span>
          <span className="brand-name">{PRODUCT}</span>
        </div>
        <nav className="menu" aria-label="Điều hướng chính">
          {MENU.map((item) => (
            <NavLink key={item.to} to={item.to}>
              {item.icon}
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <p className="sidebar-note">Bản demo chạy trên dữ liệu tổng hợp</p>
      </aside>
      <div className="app-body">
        <header className="topbar">
          <Context />
          <UserSwitch onChange={() => setUserVersion((v) => v + 1)} />
        </header>
        <main id="main" className="content" tabIndex={-1} key={userVersion}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
