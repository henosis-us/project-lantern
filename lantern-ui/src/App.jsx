import React from 'react';
import { createBrowserRouter, RouterProvider, Navigate, Outlet } from 'react-router-dom';
import { useAuth, AuthProvider } from './context/AuthContext';

// Import Pages
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import LibraryPage from './pages/LibraryPage';
import SeriesPage from './pages/SeriesPage';
import ClaimServerPage from './pages/ClaimServerPage'; // NEW
import OnboardingPage from './pages/OnboardingPage'; // NEW
import ServerSelectorPage from './pages/ServerSelectorPage'; // NEW
import SettingsPage from './pages/SettingsPage'; // NEW: Import the settings page

// A component to protect routes that require authentication
const ProtectedRoute = ({ children }) => {
  const { isAuthenticated } = useAuth();
  return isAuthenticated ? children : <Navigate to="/login" replace />;
};

// This component decides what to show authenticated users.
const AppLayout = () => {
  const { availableServers, activeServer } = useAuth();

  if (activeServer) {
    // A server is selected, show the main app content (Library, TV, etc.)
    return <Outlet />;
  }

  if (availableServers === null) {
    // Servers are still being fetched
    return <div className="auth-page"><h2>Loading...</h2></div>;
  }

  if (availableServers.length > 0) {
    return <ServerSelectorPage />;
  }

  return <OnboardingPage />;
};

const router = createBrowserRouter([
  // Public auth routes
  { path: '/login', element: <LoginPage /> },
  { path: '/register', element: <RegisterPage /> },
  // Protected routes
  {
    path: '/',
    element: <ProtectedRoute><AppLayout /></ProtectedRoute>,
    children: [
      { index: true, element: <LibraryPage /> }, // Main library view
      { path: 'tv', element: <SeriesPage /> },
      { path: 'settings', element: <SettingsPage /> }, // NEW: Add settings route
    ],
  },
  {
    path: '/claim',
    element: <ProtectedRoute><ClaimServerPage /></ProtectedRoute>,
  },
]);

function App() {
  return (
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  );
}

export default App;