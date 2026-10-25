import React from "react";
import ReactDOM from "react-dom/client";
import { HashRouter, Routes, Route, NavLink } from "react-router-dom";
import "./index.css";
import Overview from "./pages/Overview.jsx";
import AlertQueue from "./pages/AlertQueue.jsx";
import RingInvestigation from "./pages/RingInvestigation.jsx";
import WhyFlagged from "./pages/WhyFlagged.jsx";
import TemporalEvolution from "./pages/TemporalEvolution.jsx";
import PatternAnalytics from "./pages/PatternAnalytics.jsx";
import LeadTimeAnalytics from "./pages/LeadTimeAnalytics.jsx";
import ModelPerformance from "./pages/ModelPerformance.jsx";
import RingEarlyWarning from "./pages/RingEarlyWarning.jsx";
import { api } from "./api.js";
import { useApi } from "./components/ui.jsx";
import DataExplorer from "./pages/DataExplorer.jsx";

const nav = [
  ["/", "Overview"],
  ["/alerts", "Alert Queue"],
  ["/rings", "Ring Investigation"],
  ["/why-flagged", "Why Flagged?"],
  ["/temporal", "Temporal Evolution"],
  ["/patterns", "Pattern Analytics"],
  ["/lead-time", "Lead-Time Analytics"],
  ["/models", "Model Performance"],
  ["/early-warning", "Ring Early Warning"],
  ["/explorer", "Data Explorer"],
];

function Shell() {
  // dataset label from the database (synthetic data must be labelled as such)
  const { data: stats } = useApi(() => api.pipelineStats(), []);
  const src = stats?.dataset_source;
  const datasetLabel =
    src === "amlsim" ? "REAL AMLSim data" : src === "demo" ? "DEMO / SYNTHETIC DATA" : src ? `Dataset: ${src}` : "Dataset: \u2014";
  return (
    <div className="min-h-screen flex">
      <aside className="w-60 shrink-0 border-r border-border bg-panel p-4">
        <div className="text-sm font-bold text-accent mb-1">Early-AML-Warning-System</div>
        <div className="text-xs text-muted mb-4">{datasetLabel}</div>
        <nav className="flex flex-col gap-1">
          {nav.map(([to, label]) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `px-3 py-2 rounded text-sm ${isActive ? "bg-accent/20 text-accent" : "text-muted hover:bg-white/5"}`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="flex-1 p-6 max-w-6xl">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/alerts" element={<AlertQueue />} />
          <Route path="/rings" element={<RingInvestigation />} />
          <Route path="/why-flagged" element={<WhyFlagged />} />
          <Route path="/temporal" element={<TemporalEvolution />} />
          <Route path="/patterns" element={<PatternAnalytics />} />
          <Route path="/lead-time" element={<LeadTimeAnalytics />} />
          <Route path="/models" element={<ModelPerformance />} />
          <Route path="/early-warning" element={<RingEarlyWarning />} />
          <Route path="/explorer" element={<DataExplorer />} />
        </Routes>
      </main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <HashRouter>
      <Shell />
    </HashRouter>
  </React.StrictMode>
);
