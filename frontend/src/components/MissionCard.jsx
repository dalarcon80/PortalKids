import React from 'react';
import { Link } from 'react-router-dom';

const MissionCard = ({ mission = {} }) => {
  const missionIdentifier = mission.slug || mission.id;
  const enrollmentTarget = missionIdentifier
    ? `/inscripcion/${missionIdentifier}`
    : '#';
  const title = mission.title || mission.name || 'Misión sin título';

  return (
    <article className="mission-card">
      <Link to={enrollmentTarget} className="mission-card__link">
        <header className="mission-card__header">
          <h3 className="mission-card__title">{title}</h3>
        </header>
        {mission.summary && (
          <p className="mission-card__summary">{mission.summary}</p>
        )}
        {mission.description && (
          <p className="mission-card__description">{mission.description}</p>
        )}
      </Link>
    </article>
  );
};

export default MissionCard;
