import { createContext, useState, useContext, useEffect } from 'react';
import { identityApi, createMediaServerApi } from '../api/api';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [jwt, setJwt] = useState(localStorage.getItem('jwt'));
  const [user, setUser] = useState(null);

  const [availableServers, setAvailableServers] = useState(null);
  const [activeServer, setActiveServer] = useState(null);
  const [mediaServerApi, setMediaServerApi] = useState(null);

  useEffect(() => {
    const initializeAuth = async (token) => {
      localStorage.setItem('jwt', token);
      try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        setUser({ username: payload.sub });
      } catch (e) {
        console.error("Failed to decode JWT", e);
        logout();
        return;
      }
      try {
        const { data } = await identityApi.get('/me/servers');
        setAvailableServers(data);
      } catch (error) {
        console.error("Failed to fetch servers:", error);
        setAvailableServers([]);
      }
    };

    if (jwt) {
      initializeAuth(jwt);
    } else {
      localStorage.removeItem('jwt');
      setUser(null);
      setAvailableServers(null);
      setActiveServer(null);
      setMediaServerApi(null);
    }
  }, [jwt]);

  const login = async (username, password) => {
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

  // MODIFIED: This function is now much simpler.
  // It uses the gateway URL provided directly by the server object.
  const selectServer = (server) => {
    if (!server || !server.last_known_url) {
      console.error("Cannot select server: server object is invalid or has no URL.", server);
      alert("Could not connect to the server. The server might be offline or a network error occurred.");
      return;
    }

    console.log(`Connecting to media server via secure gateway: ${server.last_known_url}`);

    // The 'last_known_url' is now the gateway URL.
    // We use it to create the media server API client.
    setActiveServer(server);
    setMediaServerApi(() => createMediaServerApi(server.last_known_url));
  };

  const refreshServers = async () => {
    if (!jwt) return [];
    try {
      setAvailableServers(null);
      const { data } = await identityApi.get('/me/servers');
      setAvailableServers(data);
      return data;
    } catch (error) {
      console.error("Failed to refresh servers:", error);
      setAvailableServers([]);
      return [];
    }
  };

  const value = {
    jwt,
    user,
    isAuthenticated: !!jwt,
    isOwner: !!activeServer?.is_owner,
    login,
    register,
    logout,
    availableServers,
    activeServer,
    mediaServerApi,
    selectServer,
    refreshServers,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => useContext(AuthContext);