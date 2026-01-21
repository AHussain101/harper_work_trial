import { motion, AnimatePresence } from 'framer-motion';
import { 
  AlertCircle, 
  Building2, 
  X, 
  Check, 
  ChevronRight,
  Users,
} from 'lucide-react';
import type { PendingConfirmation, AccountAlternative } from '../types/exploration';

interface ConfirmationModalProps {
  confirmation: PendingConfirmation;
  onConfirm: () => void;
  onCancel: () => void;
  onSelectAlternative?: (accountId: string, accountName: string) => void;
  isLoading?: boolean;
}

function AlternativeAccount({ 
  alternative, 
  onSelect 
}: { 
  alternative: AccountAlternative;
  onSelect: () => void;
}) {
  const scorePercent = Math.round(alternative.score * 100);
  
  return (
    <button
      onClick={onSelect}
      className="w-full flex items-center gap-3 p-3 rounded-lg border border-slate-200 hover:border-[#f97066] hover:bg-[#fdf0e9] transition-all group"
    >
      <div className="p-2 rounded-lg bg-slate-100 group-hover:bg-white">
        <Building2 className="w-4 h-4 text-slate-600" />
      </div>
      <div className="flex-1 text-left">
        <div className="font-medium text-slate-800 group-hover:text-[#f97066]">
          {alternative.name}
        </div>
        <div className="text-xs text-slate-500">
          ID: {alternative.account_id} • {scorePercent}% match
        </div>
      </div>
      <ChevronRight className="w-4 h-4 text-slate-400 group-hover:text-[#f97066]" />
    </button>
  );
}

export function ConfirmationModal({
  confirmation,
  onConfirm,
  onCancel,
  onSelectAlternative,
  isLoading = false,
}: ConfirmationModalProps) {
  const hasAlternatives = confirmation.alternatives && confirmation.alternatives.length > 0;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
        onClick={onCancel}
      >
        <motion.div
          initial={{ scale: 0.95, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.95, opacity: 0 }}
          transition={{ type: 'spring', duration: 0.3 }}
          className="bg-white rounded-2xl shadow-2xl max-w-md w-full overflow-hidden"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="p-6 border-b border-slate-100">
            <div className="flex items-start gap-4">
              <div className="p-3 rounded-full bg-amber-100">
                <AlertCircle className="w-6 h-6 text-amber-600" />
              </div>
              <div className="flex-1">
                <h2 className="text-lg font-semibold text-slate-800">
                  Account Not Found
                </h2>
                <p className="text-sm text-slate-600 mt-1">
                  {confirmation.message}
                </p>
              </div>
              <button
                onClick={onCancel}
                className="p-2 hover:bg-slate-100 rounded-lg transition-colors"
              >
                <X className="w-5 h-5 text-slate-400" />
              </button>
            </div>
          </div>

          {/* Alternatives Section */}
          {hasAlternatives && (
            <div className="p-6 border-b border-slate-100 bg-slate-50">
              <div className="flex items-center gap-2 mb-3">
                <Users className="w-4 h-4 text-slate-500" />
                <span className="text-sm font-medium text-slate-700">
                  Did you mean one of these?
                </span>
              </div>
              <div className="space-y-2">
                {confirmation.alternatives.slice(0, 3).map((alt) => (
                  <AlternativeAccount
                    key={alt.account_id}
                    alternative={alt}
                    onSelect={() => onSelectAlternative?.(alt.account_id, alt.name)}
                  />
                ))}
              </div>
            </div>
          )}

          {/* New Account Section */}
          <div className="p-6">
            <div className="flex items-center gap-3 p-4 rounded-xl bg-[#fdf0e9] border border-[#e7d7ce] mb-4">
              <Building2 className="w-5 h-5 text-[#f97066]" />
              <div>
                <div className="font-medium text-slate-800">
                  Create new account
                </div>
                <div className="text-sm text-slate-600">
                  "{confirmation.account_name}"
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="flex gap-3">
              <button
                onClick={onCancel}
                disabled={isLoading}
                className="flex-1 px-4 py-2.5 rounded-xl border border-slate-200 text-slate-700 font-medium hover:bg-slate-50 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={onConfirm}
                disabled={isLoading}
                className="flex-1 px-4 py-2.5 rounded-xl bg-[#f97066] text-white font-medium hover:bg-[#e85a50] transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {isLoading ? (
                  <motion.div
                    animate={{ rotate: 360 }}
                    transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
                    className="w-4 h-4 border-2 border-white border-t-transparent rounded-full"
                  />
                ) : (
                  <>
                    <Check className="w-4 h-4" />
                    Create Account
                  </>
                )}
              </button>
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}

interface ClarificationModalProps {
  message: string;
  suggestions?: string[];
  onSelectSuggestion: (suggestion: string) => void;
  onCancel: () => void;
}

export function ClarificationModal({
  message,
  suggestions = [],
  onSelectSuggestion,
  onCancel,
}: ClarificationModalProps) {
  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
        onClick={onCancel}
      >
        <motion.div
          initial={{ scale: 0.95, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.95, opacity: 0 }}
          transition={{ type: 'spring', duration: 0.3 }}
          className="bg-white rounded-2xl shadow-2xl max-w-md w-full overflow-hidden"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="p-6 border-b border-slate-100">
            <div className="flex items-start gap-4">
              <div className="p-3 rounded-full bg-blue-100">
                <AlertCircle className="w-6 h-6 text-blue-600" />
              </div>
              <div className="flex-1">
                <h2 className="text-lg font-semibold text-slate-800">
                  Need Clarification
                </h2>
                <p className="text-sm text-slate-600 mt-1">
                  {message}
                </p>
              </div>
              <button
                onClick={onCancel}
                className="p-2 hover:bg-slate-100 rounded-lg transition-colors"
              >
                <X className="w-5 h-5 text-slate-400" />
              </button>
            </div>
          </div>

          {/* Suggestions */}
          {suggestions.length > 0 && (
            <div className="p-6">
              <div className="text-sm font-medium text-slate-700 mb-3">
                Try one of these:
              </div>
              <div className="space-y-2">
                {suggestions.map((suggestion, idx) => (
                  <button
                    key={idx}
                    onClick={() => onSelectSuggestion(suggestion)}
                    className="w-full text-left p-3 rounded-lg border border-slate-200 hover:border-[#f97066] hover:bg-[#fdf0e9] transition-all text-sm text-slate-700"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Close button */}
          <div className="p-6 pt-0">
            <button
              onClick={onCancel}
              className="w-full px-4 py-2.5 rounded-xl border border-slate-200 text-slate-700 font-medium hover:bg-slate-50 transition-colors"
            >
              Close
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
