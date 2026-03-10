import { NavLink } from "react-router-dom";

export function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <h1>hof engine</h1>
        <span className="subtitle">Admin Dashboard</span>
      </div>

      <ul className="sidebar-nav">
        <li>
          <NavLink to="/" className={({ isActive }) => (isActive ? "active" : "")}>
            Dashboard
          </NavLink>
        </li>
      </ul>

      <div className="sidebar-section">Application</div>
      <ul className="sidebar-nav">
        <li>
          <NavLink to="/flows" className={({ isActive }) => (isActive ? "active" : "")}>
            Flows
          </NavLink>
        </li>
        <li>
          <NavLink to="/functions" className={({ isActive }) => (isActive ? "active" : "")}>
            Functions
          </NavLink>
        </li>
        <li>
          <NavLink to="/tables" className={({ isActive }) => (isActive ? "active" : "")}>
            Tables
          </NavLink>
        </li>
      </ul>

      <div className="sidebar-section">Operations</div>
      <ul className="sidebar-nav">
        <li>
          <NavLink to="/tasks" className={({ isActive }) => (isActive ? "active" : "")}>
            Executions
          </NavLink>
        </li>
        <li>
          <NavLink to="/pending" className={({ isActive }) => (isActive ? "active" : "")}>
            Pending Actions
          </NavLink>
        </li>
      </ul>
    </aside>
  );
}
