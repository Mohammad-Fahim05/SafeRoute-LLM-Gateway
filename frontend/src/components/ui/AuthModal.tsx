import React, { useEffect, useState } from 'react';
import { KeyRound, AlertCircle, CheckCircle2, X, Shield, ShieldCheck } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

interface AuthModalProps {
  isOpen?: boolean;
  onClose?: () => void;
}

export const AuthModal: React.FC<AuthModalProps> = ({ isOpen: propIsOpen, onClose: propOnClose }) => {
  const {
    apiKey,
    login,
    logout,
    clientId,
    role,
    isAdmin,
    isAuthenticated,
    isAuthModalOpen,
    closeAuthModal,
  } = useAuth();

  const isOpen = propIsOpen !== undefined ? propIsOpen : isAuthModalOpen;
  const onClose = propOnClose !== undefined ? propOnClose : closeAuthModal;

  const [inputKey, setInputKey] = useState(apiKey);
  const [persist, setPersist] = useState(false);
  const [loading, setLoading] = useState(false);
  const [statusMsg, setStatusMsg] = useState<{ type: 'error' | 'success'; text: string } | null>(null);

  useEffect(() => {
    if (isOpen) {
      setInputKey(apiKey);
      setStatusMsg(null);
    }
  }, [isOpen, apiKey]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputKey.trim()) {
      setStatusMsg({ type: 'error', text: 'Please enter a valid API key.' });
      return;
    }
    setLoading(true);
    setStatusMsg(null);

    const res = await login(inputKey, persist);
    setLoading(false);

    if (res.success) {
      setStatusMsg({ type: 'success', text: 'Authentication verified successfully!' });
      setTimeout(() => {
        onClose();
        setStatusMsg(null);
      }, 700);
    } else {
      setStatusMsg({ type: 'error', text: res.error || 'Invalid API key.' });
    }
  };

  const handleSignOut = () => {
    logout();
    setInputKey('');
    setStatusMsg({ type: 'success', text: 'Signed out successfully.' });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#101726]/80 backdrop-blur-sm">
      <div className="w-full max-w-md bg-[#26364F] border border-[#3B4D66] rounded-2xl shadow-elevated p-6 relative">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-1.5 rounded-lg text-[#95A6BE] hover:text-[#F0F4FC] hover:bg-[#2D405B] transition-colors"
          title="Close modal"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="flex items-center gap-3 mb-5">
          <div className="p-2.5 rounded-xl bg-[#82A9FF]/15 text-[#82A9FF] border border-[#82A9FF]/25">
            <KeyRound className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-[16px] font-semibold text-[#F0F4FC]">Gateway Authentication</h3>
            <p className="text-[12px] text-[#95A6BE]">
              Enter client API key to authenticate console requests
            </p>
          </div>
        </div>

        {isAuthenticated && clientId && (
          <div className="mb-4 p-3 rounded-xl bg-[#1C2A40] border border-[#3B4D66] flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs text-[#63D6A7] font-medium">
                <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
                <span className="font-mono">{clientId}</span>
              </div>
              <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-medium uppercase flex items-center gap-1 ${
                isAdmin
                  ? 'bg-[#82A9FF]/15 text-[#82A9FF] border border-[#82A9FF]/30'
                  : 'bg-[#85B8F9]/15 text-[#85B8F9] border border-[#85B8F9]/30'
              }`}>
                {isAdmin ? <ShieldCheck className="w-3 h-3" /> : <Shield className="w-3 h-3" />}
                {role || (isAdmin ? 'admin' : 'client')}
              </span>
            </div>
            <div className="flex items-center justify-between pt-1 border-t border-[#33455E]">
              <span className="text-[11px] text-[#95A6BE]">
                {isAdmin ? 'Full administrative access enabled' : 'Tenant-scoped client access'}
              </span>
              <button
                type="button"
                onClick={handleSignOut}
                className="text-xs text-[#F18C9C] hover:underline transition-colors"
              >
                Sign out
              </button>
            </div>
          </div>
        )}

        {statusMsg && (
          <div
            className={`mb-4 p-2.5 rounded-lg text-xs flex items-center gap-2 border ${
              statusMsg.type === 'error'
                ? 'bg-[#F18C9C]/10 border-[#F18C9C]/30 text-[#F18C9C]'
                : 'bg-[#63D6A7]/10 border-[#63D6A7]/30 text-[#63D6A7]'
            }`}
          >
            {statusMsg.type === 'error' ? (
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
            ) : (
              <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
            )}
            <span>{statusMsg.text}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-[11px] font-medium text-[#C1CCDE] uppercase tracking-wider mb-1.5">
              Client API Key
            </label>
            <input
              type="password"
              placeholder="gw_test_..."
              value={inputKey}
              onChange={(e) => {
                setInputKey(e.target.value);
                if (statusMsg) setStatusMsg(null);
              }}
              className="w-full px-3 py-2 rounded-lg bg-[#1C2A40] border border-[#3B4D66] text-[#F0F4FC] placeholder:text-[#95A6BE]/50 text-xs focus:outline-none focus:border-[#82A9FF] transition-colors font-mono"
            />
            <p className="mt-1 text-[11px] text-[#95A6BE]">
              Standard gateway client key formatted as <code className="text-[#82A9FF] font-mono">gw_test_...</code>
            </p>
          </div>

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="persist"
              checked={persist}
              onChange={(e) => setPersist(e.target.checked)}
              className="rounded bg-[#1C2A40] border-[#3B4D66] text-[#82A9FF] focus:ring-0 cursor-pointer"
            />
            <label htmlFor="persist" className="text-xs text-[#C1CCDE] cursor-pointer">
              Remember across browser sessions (localStorage)
            </label>
          </div>

          <div className="flex gap-2.5 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-2 px-3.5 rounded-lg border border-[#3B4D66] text-[#C1CCDE] hover:text-[#F0F4FC] hover:bg-[#2D405B] text-xs font-medium transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 py-2 px-3.5 rounded-lg bg-[#82A9FF] hover:bg-[#A4BEFF] text-[#121A2B] text-xs font-semibold shadow-sm transition-all disabled:opacity-50"
            >
              {loading ? 'Verifying...' : 'Save & Authenticate'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
