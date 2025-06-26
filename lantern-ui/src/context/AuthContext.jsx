import { createContext, useState, useContext, useEffect } from 'react';
import { identityApi, createMediaServerApi } from '../api/api';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [jwt, setJwt] = useState(localStorage.getItem('jwt'));
  const [user, setUser] = useState(null); // Will hold { username } from the JWT

  // New state for server management
  const [availableServers, setAvailableServers] = useState(null); // null = loading, [] = empty, [...] = list
  const [activeServer, setActiveServer] = useState(null);
  const [mediaServerApi, setMediaServerApi] = useState(null); // Axios instance for the active server

  useEffect(() => {
    // This effect runs when the JWT changes.
    const initializeAuth = async (token) => {
      localStorage.setItem('jwt', token);

      // Decode user from JWT (basic info)
      try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        setUser({ username: payload.sub });
      } catch (e) {
        console.error("Failed to decode JWT", e);
        logout();
        return;
      }

      // Fetch the list of servers this user can access
      try {
        const { data } = await identityApi.get('/me/servers');
        setAvailableServers(data);
      } catch (error) {
        console.error("Failed to fetch servers:", error);
        setAvailableServers([]); // Assume no servers on error
      }
    };

    if (jwt) {
      initializeAuth(jwt);
    } else {
      localStorage.removeItem('jwt');
      // Clear all state
      setUser(null);
      setAvailableServers(null);
      setActiveServer(null);
      setMediaServerApi(null);
    }
  }, [jwt]);

  const login = async (username, password) => {
    // The backend's /login endpoint expects form data
    const body = new URLSearchParams({ username, password });
    const { data } = await identityApi.post('/auth/login', body, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
    });
    setJwt(data.access_token);
  };

  const register = async (username, password) => {
    await identityApi.post('/auth/register', { username, password });
  };

  const logout = () => {
    setJwt(null);
  };

  const selectServer = (server) => {
    if (server && server.last_known_url) {
      setActiveServer(server);
      setMediaServerApi(() => createMediaServerApi(server.last_known_url));
    } else {
      console.error("Cannot select server without a known URL.", server);
    }
  };

  // Function to manually refresh the server list, e.g., after claiming a new one
  const refreshServers = async () => {
    if (!jwt) return []; // Return empty array if no JWT
    try {
      setAvailableServers(null); // Set to loading state
      const { data } = await identityApi.get('/me/servers');
      setAvailableServers(data);
      return data; // RETURN the new server list
    } catch (error) {
      console.error("Failed to refresh servers:", error);
      setAvailableServers([]); // Assume no servers on error
      return []; // RETURN empty on error
    }
  };

  const value = {
    jwt,
    user,
    isAuthenticated: !!jwt,
    isOwner: !!activeServer?.is_owner, // Add a convenience flag for ownership
    login,
    register,
    logout,
    availableServers,
    activeServer,
    mediaServerApi, // The dynamic API instance for the selected server
    selectServer,
    refreshServers,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => useContext(AuthContext);