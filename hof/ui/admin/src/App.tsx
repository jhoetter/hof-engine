import { Routes, Route } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { Dashboard } from "./pages/Dashboard";
import { FlowViewer } from "./pages/FlowViewer";
import { FlowList } from "./pages/FlowList";
import { TableBrowser } from "./pages/TableBrowser";
import { TaskList } from "./pages/TaskList";
import { FunctionList } from "./pages/FunctionList";
import { PendingActions } from "./pages/PendingActions";

export function App() {
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
