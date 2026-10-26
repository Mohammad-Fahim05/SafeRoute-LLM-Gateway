import React, { useState } from 'react';
import { Check, Copy } from 'lucide-react';

interface JsonViewerProps {
  data: any;
  maxHeight?: string;
  className?: string;
}

export const JsonViewer: React.FC<JsonViewerProps> = ({
  data,
  maxHeight = 'max-h-96',
  className = '',
}) => {
  const [copied, setCopied] = useState(false);
  const formatted = typeof data === 'string' ? data : JSON.stringify(data, null, 2);

  const handleCopy = () => {
    navigator.clipboard.writeText(formatted);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className={`relative rounded-lg bg-[#1C2A40] border border-[#33455E] overflow-hidden group ${className}`}>
      <button
        onClick={handleCopy}
        className="absolute top-2.5 right-2.5 flex items-center gap-1.5 px-2.5 py-1 text-[11px] rounded-md bg-[#2D405B] hover:bg-[#354D6E] text-[#95A6BE] hover:text-[#F0F4FC] border border-[#3B4D66] transition-colors shadow-sm"
        title="Copy JSON to clipboard"
      >
        {copied ? (
          <>
            <Check className="w-3.5 h-3.5 text-[#63D6A7]" />
            <span className="text-[#63D6A7] font-medium">Copied</span>
          </>
        ) : (
          <>
            <Copy className="w-3.5 h-3.5" />
            <span>Copy</span>
          </>
        )}
      </button>

      <pre
        className={`p-4 font-mono text-[12px] text-[#A4BEFF] overflow-auto ${maxHeight} leading-relaxed selection:bg-[#82A9FF]/30`}
      >
        <code>{formatted}</code>
      </pre>
    </div>
  );
};
