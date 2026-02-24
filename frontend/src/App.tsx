import { Navigate, Route, BrowserRouter as Router, Routes } from "react-router-dom";
import HistoryPage from "./history/HistoryPage";
import IncidentDetailPage from "./history/IncidentDetailPage";

export default function App() {
  return (
    <Router>
      <Routes>
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/incident/:incidentId" element={<IncidentDetailPage />} />
        <Route path="*" element={<Navigate to="/history" replace />} />
      </Routes>
    </Router>
  );
}
