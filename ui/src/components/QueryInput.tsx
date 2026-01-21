import { useState, useRef, useEffect } from 'react';
import { Search, Send, Square, Loader2 } from 'lucide-react';

interface QueryInputProps {
  onSubmit: (query: string) => void;
  onStop: () => void;
  isRunning: boolean;
}

export function QueryInput({ onSubmit, onStop, isRunning }: QueryInputProps) {
  const [query, setQuery] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim() && !isRunning) {
      onSubmit(query.trim());
    }
  };

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  return (
    <form onSubmit={handleSubmit} className="relative">
      <div className="flex items-center gap-2 bg-white border border-[#e7d7ce] rounded-full px-4 py-2 focus-within:border-[#f97066] focus-within:ring-2 focus-within:ring-[#f97066]/20 transition-all shadow-sm">
        <Search className="w-5 h-5 text-slate-400 flex-shrink-0" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask about any account..."
          className="flex-1 bg-transparent outline-none text-slate-800 placeholder:text-slate-400"
          disabled={isRunning}
        />
        {isRunning ? (
          <button
            type="button"
            onClick={onStop}
            className="flex items-center gap-2 px-4 py-1.5 bg-red-50 hover:bg-red-100 text-red-600 rounded-full transition-colors border border-red-200"
          >
            <Square className="w-4 h-4" />
            <span className="text-sm font-medium">Stop</span>
          </button>
        ) : (
          <button
            type="submit"
            disabled={!query.trim()}
            className="flex items-center gap-2 px-5 py-1.5 bg-[#f97066] hover:bg-[#e85a50] disabled:bg-slate-200 disabled:text-slate-400 text-white rounded-full transition-all font-medium shadow-sm"
          >
            {isRunning ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
            <span className="text-sm">Explore</span>
          </button>
        )}
      </div>
    </form>
  );
}
