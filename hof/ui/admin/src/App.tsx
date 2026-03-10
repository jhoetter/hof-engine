import { useState } from "react";
import { Routes, Route } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { Dashboard } from "./pages/Dashboard";
import { FlowViewer } from "./pages/FlowViewer";
import { FlowList } from "./pages/FlowList";
import { TableBrowser } from "./pages/TableBrowser";
import { TaskList } from "./pages/TaskList";
import { FunctionList } from "./pages/FunctionList";
import { PendingActions } from "./pages/PendingActions";
import { isAuthenticated, setAuth, clearAuth, api } from "./api";

function LoginScreen({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    setAuth(username, password);
    try {
      await api.overview();
      onLogin();
    } catch {
      clearAuth();
      setError("Invalid credentials");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "100vh",
        background: "var(--bg-primary)",
      }}
    >
      <form
        onSubmit={handleSubmit}
        className="card"
        style={{ width: 340, padding: 32 }}
      >
        <h2 style={{ marginBottom: 24, textAlign: "center" }}>hof admin</h2>
        <div style={{ marginBottom: 16 }}>
          <label
            style={{
              display: "block",
              marginBottom: 6,
              fontSize: 13,
              color: "var(--text-secondary)",
            }}
          >
            Username
          </label>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            style={{
              width: "100%",
              padding: "8px 12px",
              background: "var(--bg-primary)",
              border: "1px solid var(--border)",
              borderRadius: 6,
              color: "var(--text-primary)",
              fontSize: 14,
              boxSizing: "border-box",
            }}
          />
        </div>
        <div style={{ marginBottom: 20 }}>
          <label
            style={{
              display: "block",
              marginBottom: 6,
              fontSize: 13,
              color: "var(--text-secondary)",
            }}
          >
            Password
          </label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
            style={{
              width: "100%",
              padding: "8px 12px",
              background: "var(--bg-primary)",
              border: "1px solid var(--border)",
              borderRadius: 6,
              color: "var(--text-primary)",
              fontSize: 14,
              boxSizing: "border-box",
            }}
          />
        </div>
        {error && (
          <p style={{ color: "var(--danger)", fontSize: 13, marginBottom: 12 }}>
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={loading}
          style={{
            width: "100%",
            padding: "10px 0",
            background: "var(--accent)",
            color: "#fff",
            border: "none",
            borderRadius: 6,
            fontSize: 14,
            fontWeight: 600,
            cursor: loading ? "wait" : "pointer",
          }}
        >
          {loading ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </div>
  );
}

export function App() {
  const [authed, setAuthed] = useState(isAuthenticated());

  if (!authed) {
    return <LoginScreen onLogin={() => setAuthed(true)} />;
  }

  return (
    <div className="layout">
      <Sidebar />
      <main className="main-content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/flows" element={<FlowList />} />
          <Route path="/flows/:name" element={<FlowViewer />} />
          <Route path="/tables" element={<TableBrowser />} />
          <Route path="/functions" element={<FunctionList />} />
          <Route path="/tasks" element={<TaskList />} />
          <Route path="/pending" element={<PendingActions />} />
        </Routes>
      </main>
    </div>
  );
}
