// src/components/SubtitlePicker.jsx
import React, { useState, useEffect, useCallback } from 'react';
// DELETED: import { getLocalSubtitles, searchRemoteSubtitles, downloadSubtitle } from '../api/api';
import { useAuth } from '../context/AuthContext'; // NEW: Import useAuth to get mediaServerApi

function SubtitlePicker({ movie, itemType, onSelect, onClose, activeSubId }) {
  // NEW: Get the dynamic mediaServerApi instance from the context
  const { mediaServerApi } = useAuth();

  const [localSubs, setLocalSubs] = useState([]);
  const [remoteSubs, setRemoteSubs] = useState([]);
  const [status, setStatus] = useState('idle'); // idle | loading | searching | downloading
  const [error, setError] = useState('');
  const [searchLang, setSearchLang] = useState('en');
  const [showSearch, setShowSearch] = useState(false);

  // Fetch already-downloaded subtitles on mount
  const fetchLocalSubs = useCallback(async () => {
    // NEW: Add check for mediaServerApi
    if (!movie || !mediaServerApi) return; 

    setStatus('loading');
    setError('');
    try {
      // Use mediaServerApi for the call
      const { data } = await mediaServerApi.get(`/subtitles/${movie.id}?item_type=${itemType}`);
      setLocalSubs(data || []);
    } catch (err) {
      setError('Could not fetch local subtitles.');
      console.error(err);
    } finally {
      setStatus('idle');
    }
  }, [movie, itemType, mediaServerApi]); // NEW: Add mediaServerApi to dependency array

  useEffect(() => {
    fetchLocalSubs();
  }, [fetchLocalSubs]);

  const handleSearch = async () => {
    // NEW: Check for mediaServerApi
    if (!mediaServerApi) {
      setError('Media server API not available.');
      return;
    }

    setStatus('searching');
    setError('');
    setRemoteSubs([]);
    try {
      // Use mediaServerApi for the call
      const { data } = await mediaServerApi.get(`/subtitles/${movie.id}/search?item_type=${itemType}&lang=${searchLang}`);
      if (data && data.length > 0) {
        setRemoteSubs(data);
      } else {
        setError('No subtitles found for this language.');
      }
    } catch (err) {
      setError('Search failed. Please try again later.');
      console.error(err);
    } finally {
      setStatus('idle');
    }
  };

  const handleDownload = async (sub) => {
    // NEW: Check for mediaServerApi
    if (!mediaServerApi) {
      setError('Media server API not available.');
      return;
    }
    
    const downloadingId = sub.id;
    setStatus(`downloading-${downloadingId}`);
    setError('');
    try {
      const payload = {
        file_id: sub.attributes.file_id,
        file_name: sub.attributes.file_name,
        lang: sub.attributes.language,
      };
      // Use mediaServerApi for the call
      const { data } = await mediaServerApi.post(`/subtitles/${movie.id}/download`, { ...payload, item_type: itemType });
                  
      // Refresh local subs to show the newly downloaded one
      await fetchLocalSubs();
                  
      // Auto-select the newly downloaded subtitle
      onSelect({ id: data.id, url: data.url, lang: payload.lang });
      onClose();
    } catch (err) {
      setError('Download failed. Please try again.');
      console.error(err);
      setStatus('idle');
    }
  };
      
  const handleSelectLocal = (sub) => {
    onSelect({ id: sub.id, url: sub.url, lang: sub.lang });
    onClose();
  };
      
  const handleSelectOff = () => {
    onSelect(null);
    onClose();
  };

  const getLanguageDisplay = (langCode) => {
    const languages = {
      'en': 'English', 'es': 'Spanish', 'fr': 'French', 'de': 'German',
      'it': 'Italian', 'pt': 'Portuguese', 'ru': 'Russian', 'ja': 'Japanese',
      'ko': 'Korean', 'zh': 'Chinese', 'ar': 'Arabic', 'hi': 'Hindi'
    };
    return languages[langCode] || langCode.toUpperCase();
  };

  const isDownloading = (subId) => status === `downloading-${subId}`;

  return (
    <div className="subtitle-modal-overlay">
      <div className="subtitle-modal">
        <div className="subtitle-modal-header">
          <h2>Subtitles</h2>
          <button className="close-btn" onClick={onClose}>×</button>
        </div>
        <div className="subtitle-modal-content">
          {error && (
            <div className="subtitle-error">
              <span className="error-icon">⚠</span>
              {error}
            </div>
          )}
          <div className="current-selection">
            <h3>Current Selection</h3>
            <div className="current-subtitle">
              {activeSubId === null ? (
                <div className="subtitle-option active">
                  <span className="subtitle-info"><span className="subtitle-name">No Subtitles</span></span>
                  <span className="active-badge">ACTIVE</span>
                </div>
              ) : (
                (() => {
                  const activeSub = localSubs.find(sub => sub.id === activeSubId);
                  return activeSub ? (
                    <div className="subtitle-option active">
                      <span className="subtitle-info">
                        <span className="subtitle-name">{activeSub.name}</span>
                        <span className="subtitle-lang">{getLanguageDisplay(activeSub.lang)}</span>
                      </span>
                      <span className="active-badge">ACTIVE</span>
                    </div>
                  ) : (
                    <div className="subtitle-option">
                      <span className="subtitle-info"><span className="subtitle-name">Loading selection...</span></span>
                    </div>
                  );
                })()
              )}
            </div>
          </div>
          <div className="available-subtitles">
            <h3>Available Options</h3>
            {status === 'loading' ? (
              <div className="loading-state">
                <div className="spinner"></div><span>Loading subtitles...</span>
              </div>
            ) : (
              <div className="subtitle-list">
                <div
                  className={`subtitle-option ${activeSubId === null ? 'active' : ''}`}
                  onClick={activeSubId === null ? undefined : handleSelectOff}
                >
                  <span className="subtitle-info">
                    <span className="subtitle-name">No Subtitles</span>
                    <span className="subtitle-description">Turn off all subtitles</span>
                  </span>
                  {activeSubId === null ? <span className="active-badge">ACTIVE</span> : <button className="select-btn">SELECT</button>}
                </div>
                {localSubs.map(sub => (
                  <div
                    key={sub.id}
                    className={`subtitle-option ${activeSubId === sub.id ? 'active' : ''}`}
                    onClick={activeSubId === sub.id ? undefined : () => handleSelectLocal(sub)}
                  >
                    <span className="subtitle-info">
                      <span className="subtitle-name">{sub.name || `Subtitle ${sub.id}`}</span>
                      <span className="subtitle-lang">{getLanguageDisplay(sub.lang)}</span>
                    </span>
                    {activeSubId === sub.id ? <span className="active-badge">ACTIVE</span> : <button className="select-btn">SELECT</button>}
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="search-section">
            <div className="search-header">
              <h3>Find More Subtitles</h3>
              <button className="toggle-search-btn" onClick={() => setShowSearch(!showSearch)}>
                {showSearch ? 'Hide Search' : 'Show Search'}
              </button>
            </div>
            {showSearch && (
              <div className="search-content">
                <div className="search-controls">
                  <select value={searchLang} onChange={(e) => setSearchLang(e.target.value)} className="language-select">
                    <option value="en">English</option><option value="es">Spanish</option><option value="fr">French</option><option value="de">German</option>
                    <option value="it">Italian</option><option value="pt">Portuguese</option><option value="ru">Russian</option><option value="ja">Japanese</option>
                    <option value="ko">Korean</option><option value="zh">Chinese</option>
                  </select>
                  <button onClick={handleSearch} disabled={status === 'searching'} className="search-btn">
                    {status === 'searching' ? <><div className="spinner small"></div>Searching...</> : 'Search OpenSubtitles'}
                  </button>
                </div>
                {remoteSubs.length > 0 && (
                  <div className="search-results">
                    <h4>Search Results</h4>
                    <div className="subtitle-list">
                      {remoteSubs.map(sub => (
                        <div key={sub.id} className="subtitle-option search-result">
                          <span className="subtitle-info">
                            <span className="subtitle-name">{sub.attributes.file_name}</span>
                            <span className="subtitle-lang">{getLanguageDisplay(sub.attributes.language)}</span>
                          </span>
                          <button onClick={() => handleDownload(sub)} disabled={isDownloading(sub.id)} className="download-btn">
                            {isDownloading(sub.id) ? <><div className="spinner small"></div>Downloading...</> : 'Download & Use'}
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default SubtitlePicker;