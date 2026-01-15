import { useState, useEffect, useCallback } from 'react';
import { getAuthStatus, login as apiLogin, logout as apiLogout } from '../api/client';
import type { User } from '../api/types';

interface UseAuthReturn {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: () => void;
  logout: () => Promise<void>;
}

export function useAuth(): UseAuthReturn {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let mounted = true;

    async function checkAuth() {
      try {
        const status = await getAuthStatus();
        if (mounted) {
          if (status.authenticated && status.user) {
            setUser(status.user);
          } else {
            setUser(null);
          }
        }
      } catch (error) {
        console.error('Auth check failed:', error);
        if (mounted) {
          setUser(null);
        }
      } finally {
        if (mounted) {
          setIsLoading(false);
        }
      }
    }

    checkAuth();

    return () => {
      mounted = false;
    };
  }, []);

  const login = useCallback(() => {
    apiLogin();
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
      setUser(null);
    } catch (error) {
      console.error('Logout failed:', error);
      // Still clear user on client side even if logout fails
      setUser(null);
    }
  }, []);

  return {
    user,
    isLoading,
    isAuthenticated: user !== null,
    login,
    logout,
  };
}
