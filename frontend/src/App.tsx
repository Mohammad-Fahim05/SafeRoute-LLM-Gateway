import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './context/AuthContext';
import { AppShell } from './components/layout/AppShell';

// Route-level dynamic code splitting
const Overview = lazy(() => import('./pages/Overview').then(m => ({ default: m.Overview })));
const Requests = lazy(() => import('./pages/Requests').then(m => ({ default: m.Requests })));
const Playground = lazy(() => import('./pages/Playground').then(m => ({ default: m.Playground })));
const Providers = lazy(() => import('./pages/Providers').then(m => ({ default: m.Providers })));
const Cache = lazy(() => import('./pages/Cache').then(m => ({ default: m.Cache })));
const Usage = lazy(() => import('./pages/Usage').then(m => ({ default: m.Usage })));
const Database = lazy(() => import('./pages/Database').then(m => ({ default: m.Database })));
const Reliability = lazy(() => import('./pages/Reliability').then(m => ({ default: m.Reliability })));
const Health = lazy(() => import('./pages/Health').then(m => ({ default: m.Health })));
const Security = lazy(() => import('./pages/Security').then(m => ({ default: m.Security })));
const Config = lazy(() => import('./pages/Config').then(m => ({ default: m.Config })));

const PageFallback: React.FC = () => (
  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '360px', color: '#9AAEC7' }}>
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px' }}>
      <div style={{
        width: '28px',
        height: '28px',
        border: '3px solid #3B4D66',
        borderTopColor: '#38BDF8',
        borderRadius: '50%',
        animation: 'spin 0.8s linear infinite',
      }} />
      <span style={{ fontSize: '13px', letterSpacing: '0.02em' }}>Loading view...</span>
    </div>
  </div>
);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 1000 * 10, // 10 seconds
      retry: 1,
    },
  },
});

export const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <AppShell>
            <Suspense fallback={<PageFallback />}>
              <Routes>
                <Route path="/" element={<Overview />} />
                <Route path="/requests" element={<Requests />} />
                <Route path="/playground" element={<Playground />} />
                <Route path="/providers" element={<Providers />} />
                <Route path="/cache" element={<Cache />} />
                <Route path="/usage" element={<Usage />} />
                <Route path="/database" element={<Database />} />
                <Route path="/reliability" element={<Reliability />} />
                <Route path="/health" element={<Health />} />
                <Route path="/security" element={<Security />} />
                <Route path="/config" element={<Config />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </Suspense>
          </AppShell>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
};

export default App;
