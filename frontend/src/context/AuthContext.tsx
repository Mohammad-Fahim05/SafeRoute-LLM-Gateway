import React, { createContext, useContext, useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api, clearStoredApiKey, getStoredApiKey, setStoredApiKey } from '../api/client';

interface AuthContextType {
  apiKey: string;
  setApiKey: (key: string) => void;
  clientId: string | null;
  role: string | null;
  isAdmin: boolean;
  authRequired: boolean;
  isAuthenticated: boolean;
  isValidating: boolean;
  isAuthModalOpen: boolean;
  openAuthModal: () => void;
  closeAuthModal: () => void;
  login: (key: string, persist?: boolean) => Promise<{ success: boolean; error?: string }>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const queryClient = useQueryClient();
  const [apiKey, setApiKey] = useState<string>(getStoredApiKey());
  const [clientId, setClientId] = useState<string | null>(null);
  const [role, setRole] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState<boolean>(false);
  const [authRequired, setAuthRequired] = useState<boolean>(true);
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [isValidating, setIsValidating] = useState<boolean>(true);
  const [isAuthModalOpen, setIsAuthModalOpen] = useState<boolean>(false);

  const openAuthModal = () => setIsAuthModalOpen(true);
  const closeAuthModal = () => setIsAuthModalOpen(false);

  // Check auth requirement from backend on mount
  useEffect(() => {
    let isMounted = true;
    async function checkAuth() {
      try {
        const status = await api.getAuthStatus();
        if (!isMounted) return;
        setAuthRequired(status.auth_enabled);

        if (!status.auth_enabled) {
          setIsAuthenticated(true);
          setClientId('anonymous_dev');
          setRole('admin');
          setIsAdmin(true);
          setIsValidating(false);
          return;
        }

        let stored = getStoredApiKey();
        if (!stored && import.meta.env.DEV) {
          try {
            const devRes = await fetch('/_dev/key');
            if (devRes.ok) {
              const devData = await devRes.json();
              if (devData.key) {
                stored = devData.key;
                setStoredApiKey(stored, true);
                setApiKey(stored);
              }
            }
          } catch {
            // Ignored
          }
        }

        if (stored) {
          try {
            const verifyRes = await api.verifyKey(stored);
            if (verifyRes.valid) {
              setIsAuthenticated(true);
              setClientId(verifyRes.client_id || 'authorized_client');
              setRole(verifyRes.role || (verifyRes.is_admin ? 'admin' : 'client'));
              setIsAdmin(!!verifyRes.is_admin);
            } else {
              setIsAuthenticated(false);
              clearStoredApiKey();
            }
          } catch {
            setIsAuthenticated(false);
          }
        }
      } catch (err) {
        console.warn('Could not check auth status:', err);
      } finally {
        if (isMounted) setIsValidating(false);
      }
    }
    checkAuth();
    return () => {
      isMounted = false;
    };
  }, []);

  const login = async (key: string, persist = false) => {
    setIsValidating(true);
    try {
      const res = await api.verifyKey(key.trim());
      if (res.valid) {
        setStoredApiKey(key.trim(), persist);
        setApiKey(key.trim());
        setIsAuthenticated(true);
        const resolvedClientId = res.client_id || 'client';
        const resolvedRole = res.role || (res.is_admin ? 'admin' : 'client');
        setClientId(resolvedClientId);
        setRole(resolvedRole);
        setIsAdmin(!!res.is_admin);
        setIsValidating(false);

        // Refresh/refetch all active queries immediately
        await queryClient.invalidateQueries();
        return { success: true };
      } else {
        setIsValidating(false);
        return { success: false, error: res.error || 'Invalid API key.' };
      }
    } catch (err: any) {
      setIsValidating(false);
      return { success: false, error: err.message || 'Connection failed.' };
    }
  };

  const logout = () => {
    clearStoredApiKey();
    setApiKey('');
    setIsAuthenticated(false);
    setClientId(null);
    setRole(null);
    setIsAdmin(false);
    queryClient.clear();
  };

  return (
    <AuthContext.Provider
      value={{
        apiKey,
        setApiKey,
        clientId,
        role,
        isAdmin,
        authRequired,
        isAuthenticated,
        isValidating,
        isAuthModalOpen,
        openAuthModal,
        closeAuthModal,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
