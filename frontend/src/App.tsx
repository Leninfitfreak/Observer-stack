import { Navigate, Route, BrowserRouter as Router, Routes } from "react-router-dom";
import HistoryPage from "./history/HistoryPage";

export default function App() {
  return (
    <Router>
      <Routes>
        <Route path="/history" element={<HistoryPage />} />
        <Route path="*" element={<Navigate to="/history" replace />} />
      </Routes>
    </Router>
  );
}
