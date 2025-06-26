import axios from 'axios';

// --- 1. Lantern Identity Service API ---
// This is a static instance for user auth, registration, and server management.
export const identityApi = axios.create({
  baseURL: 'https://lantern.henosis.us', // No /api suffix as per your plan
});

// Interceptor to add the auth token to every Identity Service request
identityApi.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('jwt');
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);


// --- 2. Media Server API Factory ---
// This function creates a new, configured Axios instance for a specific media server.
// The instance should be created and managed in a React context.
export const createMediaServerApi = (serverUrl) => {
  const mediaApi = axios.create({
    baseURL: serverUrl,
  });

  // Interceptor to add the same auth token to every media server request
  mediaApi.interceptors.request.use(
    (config) => {
      const token = localStorage.getItem('jwt');
      if (token) {
        config.headers['Authorization'] = `Bearer ${token}`;
      }
      return config;
    },
    (error) => {
      return Promise.reject(error);
    }
  );

  // Add a response error interceptor for logging API errors
  mediaApi.interceptors.response.use(
    (response) => response,
    (error) => {
      if (error.response) {
        console.error(
          `[Media-Server-API-ERR] ${error.config.method?.toUpperCase()} ${error.config.url} →`,
          `status ${error.response.status}`,
          error.response.data
        );
      } else {
        console.error('[Media-Server-API-ERR] Network / CORS problem', error.message);
      }
      return Promise.reject(error);
    }
  );

  return mediaApi;
};

// NOTE: The previous API helper functions (e.g., getLocalSubtitles, saveProgress)
// have been removed from this file. API calls to a media server should now be made
// using the dynamic API instance created by `createMediaServerApi` and stored
// in the AuthContext.