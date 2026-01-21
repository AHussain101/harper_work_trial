import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import ReactMarkdown from 'react-markdown';
import { FileText, X, Loader2, CheckCircle, MessageSquare } from 'lucide-react';
import type { FileContent } from '../types/exploration';

interface FilePreviewProps {
  path: string | null;
  filesOpened: string[];
  onClose: () => void;
  answer?: string;
  notes?: string;
  citations?: string[];
  isComplete?: boolean;
}

export function FilePreview({ path, filesOpened, onClose, answer, notes, citations, isComplete }: FilePreviewProps) {
  const [content, setContent] = useState<FileContent | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!path) {
      setContent(null);
      return;
    }

    const currentPath = path;

    async function fetchContent() {
      setLoading(true);
      setError(null);
      
      try {
        const response = await fetch(`/api/file?path=${encodeURIComponent(currentPath)}`);
        if (!response.ok) {
          throw new Error('Failed to fetch file');
        }
        const data: FileContent = await response.json();
        setContent(data);
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setLoading(false);
      }
    }

    fetchContent();
  }, [path]);

  const isRead = path ? filesOpened.includes(path) : false;
  const isMarkdown = content?.extension === '.md';

  // If there's an answer and no file selected, show the answer
  if (!path && isComplete && answer) {
    return (
      <div className="h-full flex flex-col overflow-hidden bg-white">
        {/* Header */}
        <div className="p-4 border-b border-[#e7d7ce] flex items-center gap-2 flex-shrink-0 bg-emerald-50">
          <div className="p-1.5 rounded-lg bg-emerald-500">
            <CheckCircle className="w-4 h-4 text-white" />
          </div>
          <span className="font-semibold text-emerald-700">Answer</span>
        </div>

        {/* Answer content */}
        <div className="flex-1 overflow-auto p-5">
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-slate-700 leading-relaxed"
          >
            <ReactMarkdown
              components={{
                strong: ({ children }) => <span className="font-semibold text-slate-800">{children}</span>,
                p: ({ children }) => <p className="mb-3">{children}</p>,
                ul: ({ children }) => <ul className="list-disc list-inside mb-3 space-y-1">{children}</ul>,
                li: ({ children }) => <li className="text-slate-600">{children}</li>,
              }}
            >
              {answer}
            </ReactMarkdown>
          </motion.div>
          
          {notes && (
            <div className="mt-4 pt-4 border-t border-slate-200 text-sm text-slate-500 italic">
              {notes}
            </div>
          )}

          {citations && citations.length > 0 && (
            <div className="mt-4 pt-4 border-t border-slate-200">
              <div className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-2">Sources</div>
              <div className="space-y-1">
                {citations.map((citation, idx) => (
                  <div key={idx} className="text-xs text-slate-600 font-mono bg-slate-50 px-2 py-1 rounded">
                    {citation}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  // If no file and no answer, show empty state with message icon
  if (!path) {
    return (
      <div className="h-full flex items-center justify-center bg-white">
        <div className="text-center px-6">
          <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-[#fdf0e9] flex items-center justify-center border border-[#e7d7ce]">
            <MessageSquare className="w-8 h-8 text-[#f97066]/40" />
          </div>
          <p className="text-slate-500 text-sm">Answer will appear here when exploration completes</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden bg-white">
      {/* Header */}
      <div className="p-3 border-b border-[#e7d7ce] flex items-center gap-2 flex-shrink-0 bg-slate-50">
        <FileText className="w-4 h-4 text-slate-400" />
        <span className="text-sm font-mono text-slate-600 truncate flex-1">
          {path}
        </span>
        {isRead && (
          <span className="flex items-center gap-1 text-xs text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200">
            <CheckCircle className="w-3 h-3" />
            Agent read
          </span>
        )}
        <button
          onClick={onClose}
          className="p-1 hover:bg-slate-200 rounded transition-colors"
        >
          <X className="w-4 h-4 text-slate-400" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-4">
        {loading && (
          <div className="flex items-center justify-center h-full">
            <Loader2 className="w-6 h-6 animate-spin text-[#f97066]" />
          </div>
        )}

        {error && (
          <div className="text-red-600 text-center">
            Error: {error}
          </div>
        )}

        {content && !loading && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
          >
            {isMarkdown ? (
              <div className="prose prose-sm max-w-none">
                <ReactMarkdown
                  components={{
                    strong: ({ children }) => <span className="font-semibold text-slate-800">{children}</span>,
                  }}
                >
                  {content.content}
                </ReactMarkdown>
              </div>
            ) : (
              <pre className="text-sm text-slate-700 whitespace-pre-wrap break-words bg-slate-50 p-4 rounded-lg border border-slate-200">
                {content.content}
              </pre>
            )}
          </motion.div>
        )}
      </div>

      {/* Footer with file info */}
      {content && (
        <div className="p-2 border-t border-[#e7d7ce] flex-shrink-0 text-xs text-slate-500 bg-slate-50">
          <span>{Math.round(content.size / 1024 * 10) / 10} KB</span>
          <span className="mx-2">•</span>
          <span>{content.extension || 'no extension'}</span>
        </div>
      )}
    </div>
  );
}
