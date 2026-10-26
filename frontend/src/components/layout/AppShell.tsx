import React, { useState, useEffect } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  ListOrdered,
  Sparkles,
  Server,
  Zap,
  BarChart3,
  Database,
  AlertTriangle,
  Activity,
  ShieldCheck,
  Settings,
  Menu,
  X,
  RefreshCw,
  KeyRound,
  Radio,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { AuthModal } from '../ui/AuthModal';

interface AppShellProps {
  children: React.ReactNode;
  onRefresh?: () => void;
  isRefreshing?: boolean;
  healthStatus?: 'healthy' | 'degraded' | 'unavailable' | 'unknown';
}

const navItems = [
  { path: '/', label: 'Overview', icon: LayoutDashboard },
  { path: '/requests', label: 'Request Explorer', icon: ListOrdered },
  { path: '/playground', label: 'LLM Playground', icon: Sparkles },
  { path: '/providers', label: 'Providers & Routing', icon: Server },
  { path: '/cache', label: 'Cache Monitor', icon: Zap },
  { path: '/usage', label: 'Usage & Costs', icon: BarChart3 },
  { path: '/database', label: 'Database Explorer', icon: Database },
  { path: '/reliability', label: 'Errors & Reliability', icon: AlertTriangle },
  { path: '/health', label: 'System Health', icon: Activity },
  { path: '/security', label: 'Security & Guardrails', icon: ShieldCheck },
  { path: '/config', label: 'Configuration', icon: Settings },
];

export const AppShell: React.FC<AppShellProps> = ({
  children,
  onRefresh,
  isRefreshing = false,
  healthStatus = 'healthy',
}) => {
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState<boolean>(() => {
    return localStorage.getItem('saferoute_sidebar_collapsed') === 'true';
  });
  const [lastRefreshedAt, setLastRefreshedAt] = useState<Date>(() => new Date());

  const { isAuthenticated, clientId, isAdmin, authRequired, openAuthModal } = useAuth();
  const location = useLocation();

  useEffect(() => {
    localStorage.setItem('saferoute_sidebar_collapsed', String(isCollapsed));
  }, [isCollapsed]);

  const toggleCollapse = () => setIsCollapsed((prev) => !prev);

  const handleRefresh = () => {
    if (onRefresh) {
      onRefresh();
      setLastRefreshedAt(new Date());
    }
  };

  const currentNav = navItems.find((item) => item.path === location.pathname) || {
    label: 'Console',
  };

  const statusIndicator = {
    healthy: { dot: 'bg-[#63D6A7]', text: 'text-[#63D6A7]', label: 'Healthy' },
    degraded: { dot: 'bg-[#F2C777]', text: 'text-[#F2C777]', label: 'Degraded' },
    unavailable: { dot: 'bg-[#F18C9C]', text: 'text-[#F18C9C]', label: 'Unavailable' },
    unknown: { dot: 'bg-[#95A6BE]', text: 'text-[#95A6BE]', label: 'Checking' },
  }[healthStatus];

  return (
    <div className="min-h-screen bg-[#172033] text-[#F0F4FC] flex flex-col font-sans">
      {/* Mobile Drawer Backdrop Overlay */}
      {mobileDrawerOpen && (
        <div
          className="fixed inset-0 z-50 bg-[#101726]/80 backdrop-blur-sm lg:hidden transition-opacity"
          onClick={() => setMobileDrawerOpen(false)}
        />
      )}

      {/* Mobile Slide-out Drawer */}
      <div
        className={`fixed inset-y-0 left-0 z-50 w-[260px] bg-[#1D2940] border-r border-[#3B4D66] flex flex-col transform transition-transform duration-300 ease-in-out lg:hidden ${
          mobileDrawerOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="h-16 flex items-center justify-between px-5 border-b border-[#3B4D66] bg-[#202E46]">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-[#82A9FF] flex items-center justify-center flex-shrink-0 shadow-sm">
              <ShieldCheck className="w-5 h-5 text-[#121A2B]" />
            </div>
            <div>
              <span className="font-bold text-[15px] tracking-tight text-[#F0F4FC] block leading-tight">
                SafeRoute
              </span>
              <span className="text-[10px] text-[#61C7B2] font-mono tracking-wider font-semibold">
                LLM GATEWAY
              </span>
            </div>
          </div>
          <button
            onClick={() => setMobileDrawerOpen(false)}
            className="p-1.5 rounded-lg text-[#95A6BE] hover:text-[#F0F4FC] hover:bg-[#2D405B]"
            aria-label="Close navigation"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = location.pathname === item.path;
            return (
              <NavLink
                key={item.path}
                to={item.path}
                onClick={() => setMobileDrawerOpen(false)}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-[13px] font-medium transition-colors ${
                  isActive
                    ? 'bg-[#2D405B] text-[#F0F4FC] border border-[#3B4D66]'
                    : 'text-[#C1CCDE] hover:text-[#F0F4FC] hover:bg-[#26364F]'
                }`}
              >
                <Icon
                  className={`w-4 h-4 flex-shrink-0 ${
                    isActive ? 'text-[#82A9FF]' : 'text-[#95A6BE]'
                  }`}
                />
                <span className="truncate">{item.label}</span>
              </NavLink>
            );
          })}
        </nav>
      </div>

      {/* Main Layout Container (Sidebar + Content Side-by-Side) */}
      <div className="flex flex-1 min-h-screen">
        {/* Desktop Sidebar (Permanent, Sticky, Non-Overlapping) */}
        <aside
          className={`hidden lg:flex sticky top-0 h-screen bg-[#1D2940] border-r border-[#3B4D66] flex-col flex-shrink-0 z-30 transition-all duration-200 ease-in-out ${
            isCollapsed ? 'w-[72px]' : 'w-[250px]'
          }`}
        >
          {/* Brand header */}
          <div className="h-16 flex items-center justify-between px-4 border-b border-[#3B4D66] bg-[#202E46]">
            <div className="flex items-center gap-3 overflow-hidden">
              <div className="w-8 h-8 rounded-lg bg-[#82A9FF] flex items-center justify-center flex-shrink-0 shadow-sm">
                <ShieldCheck className="w-5 h-5 text-[#121A2B]" />
              </div>
              {!isCollapsed && (
                <div className="min-w-0">
                  <span className="font-bold text-[15px] tracking-tight text-[#F0F4FC] block leading-tight">
                    SafeRoute
                  </span>
                  <span className="text-[10px] text-[#61C7B2] font-mono tracking-wider font-semibold">
                    LLM GATEWAY
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Navigation Items list */}
          <nav className="flex-1 overflow-y-auto px-2.5 py-4 space-y-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = location.pathname === item.path;
              return (
                <NavLink
                  key={item.path}
                  to={item.path}
                  title={isCollapsed ? item.label : undefined}
                  className={`flex items-center gap-3 px-3 py-2 rounded-lg text-[13px] font-medium transition-colors relative group ${
                    isActive
                      ? 'bg-[#2D405B] text-[#F0F4FC] border border-[#3B4D66]'
                      : 'text-[#C1CCDE] hover:text-[#F0F4FC] hover:bg-[#26364F]'
                  } ${isCollapsed ? 'justify-center px-0' : ''}`}
                >
                  {/* Subtle active left indicator bar */}
                  {isActive && (
                    <span className="absolute left-0 top-1.5 bottom-1.5 w-1 bg-[#82A9FF] rounded-r-full" />
                  )}

                  <Icon
                    className={`w-4 h-4 flex-shrink-0 ${
                      isActive ? 'text-[#82A9FF]' : 'text-[#95A6BE] group-hover:text-[#C1CCDE]'
                    }`}
                  />
                  {!isCollapsed && <span className="truncate">{item.label}</span>}

                  {/* Tooltip on collapsed state */}
                  {isCollapsed && (
                    <div className="absolute left-full ml-3 px-2.5 py-1 rounded-md bg-[#26364F] border border-[#3B4D66] text-xs font-medium text-[#F0F4FC] whitespace-nowrap shadow-dropdown opacity-0 pointer-events-none group-hover:opacity-100 transition-opacity z-50">
                      {item.label}
                    </div>
                  )}
                </NavLink>
              );
            })}
          </nav>

          {/* Local Provider Runtime Card */}
          <div className="p-3 border-t border-[#3B4D66] bg-[#223149]">
            {!isCollapsed ? (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="font-semibold text-[#95A6BE] uppercase tracking-wider">Runtime</span>
                  <span className="flex items-center gap-1.5 text-[#63D6A7] font-mono font-medium">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#63D6A7] animate-pulse" />
                    Ollama Local
                  </span>
                </div>
                <p className="text-[11px] text-[#C1CCDE] leading-tight">
                  Zero cloud dependency. SQLite & Redis persistence.
                </p>
              </div>
            ) : (
              <div className="flex justify-center" title="Runtime: Ollama Local">
                <Radio className="w-4 h-4 text-[#63D6A7] animate-pulse" />
              </div>
            )}
          </div>

          {/* Desktop Collapse Toggle Button */}
          <div className="flex items-center justify-between px-3 py-2.5 border-t border-[#3B4D66] bg-[#1D2940]">
            {!isCollapsed && (
              <span className="text-[11px] text-[#95A6BE] font-medium">Collapse Sidebar</span>
            )}
            <button
              onClick={toggleCollapse}
              className={`p-1.5 rounded-lg text-[#95A6BE] hover:text-[#F0F4FC] hover:bg-[#2D405B] transition-colors ${
                isCollapsed ? 'mx-auto' : ''
              }`}
              title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              {isCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
            </button>
          </div>
        </aside>

        {/* Main Application Area (Flexible, Non-Overlapped) */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Sticky Top Header */}
          <header className="h-16 bg-[#202E46] border-b border-[#3B4D66] px-4 sm:px-6 lg:px-8 flex items-center justify-between sticky top-0 z-20 flex-shrink-0">
            {/* Left Header items */}
            <div className="flex items-center gap-3 min-w-0">
              <button
                onClick={() => setMobileDrawerOpen(true)}
                className="lg:hidden p-2 text-[#95A6BE] hover:text-[#F0F4FC] rounded-lg hover:bg-[#2D405B]"
                aria-label="Open navigation menu"
              >
                <Menu className="w-5 h-5" />
              </button>

              <div className="min-w-0">
                <div className="flex items-center gap-2 text-xs text-[#95A6BE] font-medium truncate">
                  <span>Console</span>
                  <span className="text-[#3B4D66]">/</span>
                  <span className="text-[#82A9FF] font-semibold truncate">{currentNav.label}</span>
                </div>
              </div>
            </div>

            {/* Right Header items */}
            <div className="flex items-center gap-2.5 sm:gap-3 flex-shrink-0">
              {/* Gateway Health Indicator */}
              <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#26364F] border border-[#3B4D66] text-xs">
                <span className={`w-2 h-2 rounded-full ${statusIndicator.dot}`} />
                <span className="text-[#95A6BE] text-[11px] font-medium uppercase">Gateway:</span>
                <span className={`font-mono text-[11px] font-medium ${statusIndicator.text}`}>
                  {statusIndicator.label}
                </span>
              </div>

              {/* Refresh Button with Timestamp */}
              {onRefresh && (
                <button
                  onClick={handleRefresh}
                  disabled={isRefreshing}
                  className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#26364F] hover:bg-[#2D405B] border border-[#3B4D66] text-xs text-[#C1CCDE] hover:text-[#F0F4FC] transition-colors disabled:opacity-50"
                  title={`Refreshed: ${lastRefreshedAt.toLocaleTimeString()}`}
                >
                  <RefreshCw className={`w-3.5 h-3.5 text-[#82A9FF] ${isRefreshing ? 'animate-spin' : ''}`} />
                  <span className="hidden md:inline text-[11px]">Refresh</span>
                </button>
              )}

              {/* Client Auth Status Trigger */}
              <button
                onClick={openAuthModal}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                  isAuthenticated
                    ? 'bg-[#63D6A7]/10 border-[#63D6A7]/30 text-[#63D6A7] hover:bg-[#63D6A7]/20'
                    : authRequired
                    ? 'bg-[#F18C9C]/10 border-[#F18C9C]/30 text-[#F18C9C] hover:bg-[#F18C9C]/20 animate-pulse'
                    : 'bg-[#26364F] border-[#3B4D66] text-[#C1CCDE] hover:text-[#F0F4FC]'
                }`}
                title={
                  isAuthenticated
                    ? `Authenticated as ${clientId} (${isAdmin ? 'Admin' : 'Client'})`
                    : 'Enter client API key'
                }
              >
                <KeyRound className="w-3.5 h-3.5" />
                <span className="hidden sm:inline font-mono">
                  {isAuthenticated
                    ? `${clientId} (${isAdmin ? 'Admin' : 'Client'})`
                    : authRequired
                    ? 'Authenticate'
                    : 'Dev Key'}
                </span>
              </button>
            </div>
          </header>

          {/* Main Content Body with Natural Vertical Scroll */}
          <main className="flex-1 bg-[#172033] min-h-[calc(100vh-64px)]">
            <div className="max-w-[1440px] mx-auto w-full px-5 sm:px-8 py-8 space-y-7">
              {/* Authentication Required Alert Banner */}
              {authRequired && !isAuthenticated && (
                <div className="p-4 rounded-xl bg-[#26364F] border border-[#F18C9C]/30 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 shadow-card">
                  <div className="flex items-center gap-3">
                    <div className="p-2 rounded-lg bg-[#F18C9C]/10 border border-[#F18C9C]/20 text-[#F18C9C] flex-shrink-0">
                      <KeyRound className="w-5 h-5" />
                    </div>
                    <div>
                      <h4 className="text-[14px] font-semibold text-[#F0F4FC]">
                        Dashboard Authentication Required
                      </h4>
                      <p className="text-[12px] text-[#C1CCDE] mt-0.5">
                        Protected management endpoints require a client key. Enter your key to load live telemetry.
                      </p>
                    </div>
                  </div>
                  <button
                    onClick={openAuthModal}
                    className="px-4 py-2 rounded-lg bg-[#82A9FF] hover:bg-[#A4BEFF] text-[#121A2B] text-xs font-semibold shadow-sm transition-colors flex items-center gap-2 flex-shrink-0"
                  >
                    <KeyRound className="w-3.5 h-3.5" />
                    Enter Client Key
                  </button>
                </div>
              )}

              {children}
            </div>
          </main>
        </div>
      </div>

      {/* Global Auth Modal */}
      <AuthModal />
    </div>
  );
};
