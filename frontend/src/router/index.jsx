import React from 'react';
import { Routes, Route } from 'react-router-dom';
import EnrollPage from '../pages/EnrollPage';
import LandingPage from '../pages/LandingPage';

const AppRouter = () => (
  <Routes>
    <Route path="/" element={<LandingPage />} />
    <Route path="/misiones/:missionId" element={<div>Detalle de la misión</div>} />
    <Route path="/inscripcion/:missionId" element={<EnrollPage />} />
  </Routes>
);

export default AppRouter;
