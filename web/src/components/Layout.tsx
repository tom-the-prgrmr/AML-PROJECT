import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import UserSwitch from "./UserSwitch";

const MENU: { to: string; label: string }[] = [
  { to: "/cases", label: "Hàng đợi case" },
  { to: "/screening", label: "Rà soát screening" },
  { to: "/data-quality", label: "Chất lượng dữ liệu" },
  { to: "/benchmark", label: "Benchmark" },
  { to: "/metrics", label: "Chỉ số" },
  { to: "/system", label: "Hệ thống" },
];

export default function Layout() {
  // Bumping this key remounts the page, so its data reloads for the new user.
  const [userVersion, setUserVersion] = useState(0);
  return (
    <div className="app">
      <header className="header">
        <h1>AML - Bàn điều tra</h1>
        <UserSwitch onChange={() => setUserVersion((v) => v + 1)} />
      </header>
      <nav className="menu">
        {MENU.map((item) => (
          <NavLink key={item.to} to={item.to}>
            {item.label}
          </NavLink>
        ))}
      </nav>
      <main className="content" key={userVersion}>
        <Outlet />
      </main>
    </div>
  );
}
