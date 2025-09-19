import React from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import EnrollPage from '../pages/EnrollPage';
import LandingPage from '../pages/LandingPage';
import AdminIntegrations from '../pages/AdminIntegrations';

const STORAGE_KEYS = {
  token: 'session_token',
  admin: 'session_is_admin',
};

const normalizeAdminFlag = (value) => {
  if (value == null) {
    return false;
  }
  const normalized = String(value).trim().toLowerCase();
  return ['1', 'true', 'yes', 'y', 'on'].includes(normalized);
};

const ProtectedRoute = ({ children }) => {
  if (typeof window === 'undefined' || !window.localStorage) {
    return <Navigate to="/" replace />;
  }
  const token = window.localStorage.getItem(STORAGE_KEYS.token);
  const adminFlag = window.localStorage.getItem(STORAGE_KEYS.admin);
  if (!token || !normalizeAdminFlag(adminFlag)) {
    return <Navigate to="/" replace />;
  }
  return children;
};

const AppRouter = () => (
  <Routes>
    <Route path="/" element={<LandingPage />} />
    <Route path="/misiones/:missionId" element={<div>Detalle de la misión</div>} />
    <Route path="/inscripcion/:missionId" element={<EnrollPage />} />
    <Route
      path="/admin/integrations"
      element={(
        <ProtectedRoute>
          <AdminIntegrations />
        </ProtectedRoute>
      )}
    />
  </Routes>
);

export default AppRouter;
