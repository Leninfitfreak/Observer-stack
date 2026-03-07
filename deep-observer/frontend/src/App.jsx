import { Route, Routes } from "react-router-dom";
import DashboardPage from "./pages/DashboardPage";
import IncidentDetailsPage from "./pages/IncidentDetailsPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<DashboardPage />} />
      <Route path="/incidents/:incidentId" element={<IncidentDetailsPage />} />
    </Routes>
  );
}
