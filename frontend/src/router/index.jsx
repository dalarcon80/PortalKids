import React from 'react';
import { Routes, Route } from 'react-router-dom';
import EnrollPage from '../pages/EnrollPage';

const AppRouter = () => (
  <Routes>
    <Route path="/" element={<div>Inicio del portal</div>} />
    <Route path="/misiones/:missionId" element={<div>Detalle de la misión</div>} />
    <Route path="/inscripcion/:missionId" element={<EnrollPage />} />
  </Routes>
);

export default AppRouter;
