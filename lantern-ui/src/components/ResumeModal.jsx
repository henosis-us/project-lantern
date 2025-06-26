// src/components/ResumeModal.jsx
import React from 'react';

function ResumeModal({ isOpen, onResume, onStartOver, resumeTime }) {
  if (!isOpen) {
    return null;
  }

  return (
    <div className="modal-overlay" id="resume-modal-overlay">
      <div className="modal-content" id="resume-modal-content">
        <h2>Resume Playback?</h2>
        <p>
          Do you want to continue watching from <strong>{resumeTime}</strong>?
        </p>
        <div className="modal-actions">
          <button onClick={onStartOver} className="btn-secondary">Start Over</button>
          <button onClick={onResume} className="btn-primary">Resume</button>
        </div>
      </div>
    </div>
  );
}

export default ResumeModal;