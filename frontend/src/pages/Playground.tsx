import React, { useState, useRef, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { PageHeader } from '../components/ui/PageHeader';
import { SectionCard } from '../components/ui/SectionCard';
import { StatusBadge } from '../components/ui/StatusBadge';
import { Button } from '../components/ui/Button';
import {
  Play,
  Square,
  Trash2,
  Copy,
  Check,
  Sparkles,
  Sliders,
  Clock,
  Zap,
  Server,
  AlertCircle,
  KeyRound,
  CornerDownLeft,
} from 'lucide-react';
import type { ProvidersStatus } from '../types';

interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export const Playground: React.FC = () => {
  const { authRequired, isAuthenticated, openAuthModal } = useAuth();
  const [model, setModel] = useState('llama3.2:1b');
  const [systemPrompt, setSystemPrompt] = useState('You are a helpful and concise AI assistant running locally via SafeRoute LLM Gateway.');
  const [userPrompt, setUserPrompt] = useState('Explain why an LLM Gateway with Redis caching and SQLite audit logging is useful in 3 bullet points.');
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(512);
  const [stream, setStream] = useState(true);

  const [conversation, setConversation] = useState<ChatMessage[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [currentAssistantResponse, setCurrentAssistantResponse] = useState('');
  const [responseMeta, setResponseMeta] = useState<{
    durationMs?: number;
    tokens?: number;
    cacheStatus?: string;
    requestId?: string;
    servingModel?: string;
  } | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const abortControllerRef = useRef<AbortController | null>(null);
  const responseEndRef = useRef<HTMLDivElement>(null);

  // Fetch available providers and pulled models
  const { data: providersData } = useQuery<ProvidersStatus>({
    queryKey: ['providersStatus'],
    queryFn: () => api.getProvidersStatus(),
    enabled: !authRequired || isAuthenticated,
  });

  const availableModels = providersData?.ollama?.pulled_models?.length
    ? providersData.ollama.pulled_models
    : ['llama3.2:1b', 'qwen2.5-coder:7b-instruct-q4_K_M', 'mock-model'];

  useEffect(() => {
    if (providersData?.ollama?.pulled_models?.length && !providersData.ollama.pulled_models.includes(model)) {
      setModel(providersData.ollama.pulled_models[0]);
    }
  }, [providersData, model]);

  useEffect(() => {
    responseEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [currentAssistantResponse, conversation]);

  const handleSend = async () => {
    if (authRequired && !isAuthenticated) {
      openAuthModal();
      setErrorMessage('Please authenticate with a client API key before issuing playground requests.');
      return;
    }

    if (!userPrompt.trim() || isGenerating) return;

    setErrorMessage(null);
    setIsGenerating(true);
    setCurrentAssistantResponse('');
    setResponseMeta(null);

    const messages: ChatMessage[] = [];
    if (systemPrompt.trim()) {
      messages.push({ role: 'system', content: systemPrompt.trim() });
    }
    messages.push(...conversation);
    messages.push({ role: 'user', content: userPrompt.trim() });

    // Update conversation with user message
    const updatedHistory: ChatMessage[] = [...conversation, { role: 'user', content: userPrompt.trim() }];
    setConversation(updatedHistory);
    setUserPrompt('');

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      let accumulated = '';
      const meta = await api.sendChatCompletion(
        {
          model,
          messages,
          temperature,
          max_tokens: maxTokens,
          stream,
        },
        (chunk) => {
          accumulated += chunk;
          setCurrentAssistantResponse((prev) => prev + chunk);
        },
        controller.signal
      );

      setResponseMeta({
        durationMs: meta.durationMs,
        cacheStatus: meta.cacheStatus,
        requestId: meta.id,
        servingModel: meta.model || model,
      });

      // Commit assistant response to conversation history
      setConversation((prev) => [
        ...prev,
        { role: 'assistant', content: accumulated || currentAssistantResponse },
      ]);
      setCurrentAssistantResponse('');
    } catch (err: any) {
      if (err.name === 'AbortError') {
        setErrorMessage('Generation stopped by user.');
      } else {
        setErrorMessage(err.message || 'Gateway completion request failed.');
      }
    } finally {
      setIsGenerating(false);
      abortControllerRef.current = null;
    }
  };

  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
  };

  const handleClear = () => {
    setConversation([]);
    setCurrentAssistantResponse('');
    setResponseMeta(null);
    setErrorMessage(null);
  };

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (authRequired && !isAuthenticated) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="LLM Playground"
          subtitle="Test real-time chat completions directly through the SafeRoute Gateway with guardrails, caching, and token accounting."
          breadcrumbs={[{ label: 'SafeRoute' }, { label: 'Playground' }]}
        />
        <div className="p-8 sm:p-12 rounded-xl bg-[#26364F] border border-[#3B4D66] text-center max-w-lg mx-auto my-12 shadow-card">
          <div className="w-12 h-12 rounded-xl bg-[#82A9FF]/10 text-[#82A9FF] flex items-center justify-center mx-auto mb-4 border border-[#82A9FF]/20">
            <KeyRound className="w-6 h-6" />
          </div>
          <h3 className="text-base font-semibold text-[#F0F4FC]">Authentication Required</h3>
          <p className="text-sm text-[#C1CCDE] mt-1.5 mb-6">
            Enter a valid client key to execute completions through the LLM playground.
          </p>
          <Button onClick={openAuthModal} variant="primary" icon={KeyRound}>
            Authenticate Console
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-7">
      {/* Page Header */}
      <PageHeader
        title="LLM Playground"
        subtitle="Test real-time chat completions directly through the SafeRoute Gateway with guardrails, caching, and token accounting."
        breadcrumbs={[{ label: 'SafeRoute' }, { label: 'Playground' }]}
        actions={
          isGenerating ? (
            <Button onClick={handleStop} variant="danger" size="md" icon={Square}>
              Stop Generation
            </Button>
          ) : (
            <Button
              onClick={handleSend}
              disabled={!userPrompt.trim()}
              variant="primary"
              size="md"
              icon={Play}
            >
              Run Completion
            </Button>
          )
        }
      />

      {/* Main Grid: Parameters on Left (4 cols), Chat on Right (8 cols) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Settings Panel */}
        <div className="lg:col-span-4 space-y-4">
          <SectionCard
            title="Inference Controls"
            subtitle="Configure model, hyperparameters, and persona"
            icon={Sliders}
          >
            <div className="space-y-4">
              {/* Model Selection */}
              <div>
                <label className="block text-xs font-medium text-[#C1CCDE] mb-1.5">
                  Target Model
                </label>
                <select
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  className="w-full px-3 py-2 bg-[#1C2A40] border border-[#3B4D66] rounded-lg text-xs text-[#F0F4FC] font-mono focus:outline-none focus:border-[#82A9FF] transition-colors"
                >
                  {availableModels.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </div>

              {/* Temperature Slider */}
              <div>
                <div className="flex justify-between text-xs font-medium text-[#C1CCDE] mb-1.5">
                  <span>Temperature</span>
                  <span className="font-mono text-[#F0F4FC] font-semibold">{temperature.toFixed(2)}</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="2"
                  step="0.05"
                  value={temperature}
                  onChange={(e) => setTemperature(parseFloat(e.target.value))}
                  className="w-full accent-[#82A9FF] cursor-pointer h-1.5 bg-[#1C2A40] rounded-lg appearance-none"
                />
                <div className="flex justify-between text-[11px] text-[#95A6BE] mt-1">
                  <span>Deterministic (0.0)</span>
                  <span>Creative (2.0)</span>
                </div>
              </div>

              {/* Max Tokens */}
              <div>
                <label className="block text-xs font-medium text-[#C1CCDE] mb-1.5">
                  Max Output Tokens
                </label>
                <input
                  type="number"
                  min="1"
                  max="4096"
                  value={maxTokens}
                  onChange={(e) => setMaxTokens(parseInt(e.target.value) || 256)}
                  className="w-full px-3 py-2 bg-[#1C2A40] border border-[#3B4D66] rounded-lg text-xs text-[#F0F4FC] font-mono focus:outline-none focus:border-[#82A9FF] transition-colors"
                />
              </div>

              {/* Streaming Toggle */}
              <div className="flex items-center justify-between p-3 bg-[#1C2A40] rounded-lg border border-[#33455E]">
                <div>
                  <span className="text-xs font-medium text-[#F0F4FC] block">Stream Tokens</span>
                  <span className="text-[11px] text-[#95A6BE]">Receive SSE chunks in real-time</span>
                </div>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={stream}
                    onChange={(e) => setStream(e.target.checked)}
                    className="sr-only peer"
                  />
                  <div className="w-9 h-5 bg-[#2D405B] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-[#82A9FF]"></div>
                </label>
              </div>

              {/* System Prompt */}
              <div>
                <label className="block text-xs font-medium text-[#C1CCDE] mb-1.5">
                  System Persona
                </label>
                <textarea
                  rows={3}
                  value={systemPrompt}
                  onChange={(e) => setSystemPrompt(e.target.value)}
                  placeholder="Optional system instruction..."
                  className="w-full p-2.5 bg-[#1C2A40] border border-[#3B4D66] rounded-lg text-xs text-[#F0F4FC] placeholder:text-[#95A6BE]/50 focus:outline-none focus:border-[#82A9FF] transition-colors resize-none"
                />
              </div>

              {/* Active Provider Info */}
              <div className="pt-3 border-t border-[#33455E] text-xs text-[#95A6BE] space-y-1.5">
                <div className="flex justify-between">
                  <span>Runtime:</span>
                  <span className="text-[#63D6A7] font-medium">Local Ollama</span>
                </div>
                <div className="flex justify-between">
                  <span>Guardrails:</span>
                  <span className="text-[#61C7B2] font-medium">Active (PII + Injection)</span>
                </div>
                <div className="flex justify-between">
                  <span>Cache Policy:</span>
                  <span className="text-[#82A9FF] font-medium">Exact Hash SHA-256</span>
                </div>
              </div>
            </div>
          </SectionCard>
        </div>

        {/* Right Chat and Response Area */}
        <div className="lg:col-span-8 flex flex-col space-y-4">
          {/* Messages Container inside SectionCard */}
          <SectionCard
            title="Conversation Session"
            subtitle={`${conversation.length} exchange${conversation.length === 1 ? '' : 's'} recorded`}
            actions={
              conversation.length > 0 ? (
                <button
                  onClick={handleClear}
                  className="flex items-center gap-1.5 text-xs text-[#95A6BE] hover:text-[#F18C9C] transition-colors"
                >
                  <Trash2 className="w-3.5 h-3.5" /> Clear Session
                </button>
              ) : undefined
            }
          >
            <div className="min-h-[400px] max-h-[520px] overflow-y-auto space-y-4 flex flex-col pr-1">
              {conversation.length === 0 && !currentAssistantResponse ? (
                <div className="flex-1 flex flex-col items-center justify-center text-center p-8 text-[#95A6BE]">
                  <div className="w-12 h-12 rounded-xl bg-[#82A9FF]/10 text-[#82A9FF] flex items-center justify-center mb-3 border border-[#82A9FF]/20">
                    <Sparkles className="w-6 h-6" />
                  </div>
                  <h4 className="text-sm font-semibold text-[#F0F4FC]">Interactive Gateway Session</h4>
                  <p className="text-xs max-w-sm mt-1 text-[#95A6BE] leading-relaxed">
                    Type your prompt below to benchmark local Ollama performance, observe cache hits, or test guardrail redactions.
                  </p>
                </div>
              ) : (
                conversation.map((msg, idx) => (
                  <div
                    key={idx}
                    className={`flex flex-col ${
                      msg.role === 'user' ? 'items-end' : 'items-start'
                    }`}
                  >
                    <div className="text-[10px] uppercase font-mono tracking-wider text-[#95A6BE] mb-1 px-1">
                      {msg.role === 'user' ? 'You' : `Assistant (${model})`}
                    </div>
                    <div
                      className={`max-w-[85%] rounded-xl px-4 py-3 text-xs leading-relaxed whitespace-pre-wrap ${
                        msg.role === 'user'
                          ? 'bg-[#2D405B] border border-[#82A9FF]/40 text-[#F0F4FC] rounded-tr-none'
                          : 'bg-[#1C2A40] border border-[#3B4D66] text-[#F0F4FC] rounded-tl-none'
                      }`}
                    >
                      {msg.content}
                    </div>
                  </div>
                ))
              )}

              {/* Currently Streaming Assistant Response */}
              {currentAssistantResponse && (
                <div className="flex flex-col items-start">
                  <div className="text-[10px] uppercase font-mono text-[#61C7B2] mb-1 px-1 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#61C7B2] animate-pulse" />
                    Streaming Response ({model})...
                  </div>
                  <div className="max-w-[85%] bg-[#1C2A40] border border-[#3B4D66] text-[#F0F4FC] rounded-xl rounded-tl-none px-4 py-3 text-xs leading-relaxed whitespace-pre-wrap">
                    {currentAssistantResponse}
                  </div>
                </div>
              )}

              <div ref={responseEndRef} />
            </div>

            {/* Response Telemetry Strip */}
            {responseMeta && (
              <div className="mt-4 pt-3.5 border-t border-[#33455E] flex flex-wrap items-center justify-between gap-3 text-xs">
                <div className="flex items-center gap-4 text-[#95A6BE]">
                  <span className="flex items-center gap-1.5 font-mono">
                    <Clock className="w-3.5 h-3.5 text-[#61C7B2]" />
                    Latency: <span className="text-[#F0F4FC] font-semibold">{responseMeta.durationMs} ms</span>
                  </span>
                  <span className="flex items-center gap-1.5 font-mono">
                    <Zap className="w-3.5 h-3.5 text-[#82A9FF]" />
                    Cache: <StatusBadge status={responseMeta.cacheStatus || 'MISS'} size="sm" />
                  </span>
                  <span className="flex items-center gap-1.5 font-mono">
                    <Server className="w-3.5 h-3.5 text-[#85B8F9]" />
                    Model: <span className="text-[#F0F4FC]">{responseMeta.servingModel}</span>
                  </span>
                </div>
                {conversation.length > 0 && (
                  <button
                    onClick={() => handleCopy(conversation[conversation.length - 1].content)}
                    className="flex items-center gap-1 text-[#82A9FF] hover:text-[#A4BEFF] text-xs font-medium transition-colors"
                  >
                    {copied ? <Check className="w-3.5 h-3.5 text-[#63D6A7]" /> : <Copy className="w-3.5 h-3.5" />}
                    {copied ? 'Copied' : 'Copy'}
                  </button>
                )}
              </div>
            )}
          </SectionCard>

          {/* Error Alert */}
          {errorMessage && (
            <div className="bg-[#F18C9C]/10 border border-[#F18C9C]/30 text-[#F18C9C] p-3 rounded-xl flex items-center gap-2 text-xs">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              <span>{errorMessage}</span>
            </div>
          )}

          {/* User Input & Action Controls inside SectionCard */}
          <SectionCard noPadding>
            <div className="p-3.5 space-y-2">
              <textarea
                rows={3}
                value={userPrompt}
                onChange={(e) => setUserPrompt(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                placeholder="Ask anything or test prompt injection / PII redaction... (Press Ctrl+Enter to send)"
                className="w-full p-3 bg-[#1C2A40] border border-[#3B4D66] rounded-lg text-xs text-[#F0F4FC] placeholder:text-[#95A6BE]/50 focus:outline-none focus:border-[#82A9FF] transition-colors resize-none"
              />
              <div className="flex items-center justify-between pt-1">
                <span className="text-[11px] text-[#95A6BE] flex items-center gap-1 font-mono">
                  <CornerDownLeft className="w-3 h-3" /> Ctrl + Enter to send
                </span>
                <Button
                  onClick={handleSend}
                  disabled={!userPrompt.trim() || isGenerating}
                  variant="primary"
                  size="sm"
                  icon={Play}
                >
                  Run
                </Button>
              </div>
            </div>
          </SectionCard>
        </div>
      </div>
    </div>
  );
};
