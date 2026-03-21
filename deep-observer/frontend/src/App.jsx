import { Route, Routes } from "react-router-dom";
import DashboardPage from "./pages/DashboardPage";
import IncidentDetailsPage from "./pages/IncidentDetailsPage";
import DashboardV2Page from "./pages/DashboardV2Page";
import IncidentV2Page from "./pages/IncidentV2Page";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<DashboardV2Page />} />
      <Route path="/v2" element={<DashboardV2Page />} />
      <Route path="/v2/incidents/:incidentId" element={<IncidentV2Page />} />
      <Route path="/legacy" element={<DashboardPage />} />
      <Route path="/legacy/incidents/:incidentId" element={<IncidentDetailsPage />} />
      <Route path="/incidents/:incidentId" element={<IncidentDetailsPage />} />
    </Routes>
  );
}
