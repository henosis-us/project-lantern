// src/components/SettingsModal.jsx
import React from 'react';

function SettingsModal({ settings, onSettingsChange, onClose }) {
  if (!settings) return null;

  const handleSave = () => {
    onClose(); // In this setup, changes are applied live, so save is just close.
  };

  return (
    <div id="settings-modal" className="active">
      <h3>Playback Settings</h3>
      <label htmlFor="playback-mode">Playback Mode:</label>
      <select 
        id="playback-mode" 
        value={settings.mode}
        onChange={(e) => onSettingsChange({ ...settings, mode: e.target.value })}
      >
        <option value="auto">Auto</option>
        <option value="direct">Force Direct Play</option>
        <option value="transcode">Force Transcode</option>
      </select>

      <label htmlFor="transcode-quality">Transcode Quality:</label>
      <select 
        id="transcode-quality" 
        value={settings.quality}
        onChange={(e) => onSettingsChange({ ...settings, quality: e.target.value })}
      >
        <option value="low">Low</option>
        <option value="medium">Medium</option>
        <option value="high">High</option>
      </select>

      <label htmlFor="resolution-select">Resolution:</label>
      <select 
        id="resolution-select" 
        value={settings.resolution}
        onChange={(e) => onSettingsChange({ ...settings, resolution: e.target.value })}
      >
        <option value="source">Source</option>
        <option value="1080p">1080p</option>
        <option value="720p">720p</option>
        <option value="480p">480p</option>
        <option value="360p">360p</option>
      </select>

      <button id="save-settings" onClick={handleSave}>Save & Close</button>
    </div>
  );
}

export default SettingsModal;