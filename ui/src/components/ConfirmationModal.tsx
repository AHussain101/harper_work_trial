import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  AlertCircle, 
  Building2, 
  X, 
  Check, 
  ChevronRight,
  Users,
  Plus,
  ChevronDown,
} from 'lucide-react';
import type { PendingConfirmation, AccountAlternative } from '../types/exploration';

// Account details for new account creation
export interface NewAccountDetails {
  industry?: string;
  location?: string;
  primary_email?: string;
  primary_phone?: string;
  insurance_types?: string[];
  notes?: string;
}

interface ConfirmationModalProps {
  confirmation: PendingConfirmation;
  onConfirm: (details?: NewAccountDetails) => void;
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

const INDUSTRY_OPTIONS = [
  'Healthcare',
  'Construction',
  'Manufacturing',
  'Retail',
  'Technology',
  'Professional Services',
  'Restaurant & Hospitality',
  'Transportation',
  'Real Estate',
  'Education',
  'Other',
];

const INSURANCE_TYPE_OPTIONS = [
  "Workers' Compensation",
  'General Liability',
  'Commercial Auto',
  'Property',
  'Professional Liability',
  'Cyber Liability',
  'Business Owners Policy (BOP)',
  'Umbrella/Excess',
];

export function ConfirmationModal({
  confirmation,
  onConfirm,
  onCancel,
  onSelectAlternative,
  isLoading = false,
}: ConfirmationModalProps) {
  const hasAlternatives = confirmation.alternatives && confirmation.alternatives.length > 0;
  const [showDetailsForm, setShowDetailsForm] = useState(false);
  const [details, setDetails] = useState<NewAccountDetails>({
    industry: '',
    location: '',
    primary_email: '',
    primary_phone: '',
    insurance_types: [],
    notes: '',
  });

  const handleInsuranceTypeToggle = (type: string) => {
    setDetails(prev => ({
      ...prev,
      insurance_types: prev.insurance_types?.includes(type)
        ? prev.insurance_types.filter(t => t !== type)
        : [...(prev.insurance_types || []), type]
    }));
  };

  const handleConfirm = () => {
    // Only pass details if the form was shown and has data
    const hasDetails = showDetailsForm && (
      details.industry || 
      details.location || 
      details.primary_email || 
      details.primary_phone || 
      (details.insurance_types && details.insurance_types.length > 0) ||
      details.notes
    );
    onConfirm(hasDetails ? details : undefined);
  };

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
          className="bg-white rounded-2xl shadow-2xl max-w-lg w-full overflow-hidden max-h-[90vh] flex flex-col"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="p-6 border-b border-slate-100 flex-shrink-0">
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

          {/* Scrollable content */}
          <div className="overflow-y-auto flex-1">
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
                <div className="flex-1">
                  <div className="font-medium text-slate-800">
                    Create new account
                  </div>
                  <div className="text-sm text-slate-600">
                    "{confirmation.account_name}"
                  </div>
                </div>
              </div>

              {/* Toggle for details form */}
              <button
                onClick={() => setShowDetailsForm(!showDetailsForm)}
                className="w-full flex items-center gap-2 p-3 rounded-lg border border-slate-200 hover:bg-slate-50 transition-colors mb-4 text-sm"
              >
                <Plus className="w-4 h-4 text-slate-500" />
                <span className="flex-1 text-left text-slate-700 font-medium">
                  Add account details (optional)
                </span>
                <ChevronDown className={`w-4 h-4 text-slate-400 transition-transform ${showDetailsForm ? 'rotate-180' : ''}`} />
              </button>

              {/* Details Form */}
              <AnimatePresence>
                {showDetailsForm && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="space-y-4 mb-4 overflow-hidden"
                  >
                    {/* Industry */}
                    <div>
                      <label className="block text-sm font-medium text-slate-700 mb-1.5">
                        Industry
                      </label>
                      <select
                        value={details.industry}
                        onChange={(e) => setDetails(prev => ({ ...prev, industry: e.target.value }))}
                        className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#f97066]/20 focus:border-[#f97066]"
                      >
                        <option value="">Select an industry...</option>
                        {INDUSTRY_OPTIONS.map(opt => (
                          <option key={opt} value={opt}>{opt}</option>
                        ))}
                      </select>
                    </div>

                    {/* Location */}
                    <div>
                      <label className="block text-sm font-medium text-slate-700 mb-1.5">
                        Location
                      </label>
                      <input
                        type="text"
                        value={details.location}
                        onChange={(e) => setDetails(prev => ({ ...prev, location: e.target.value }))}
                        placeholder="City, State"
                        className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#f97066]/20 focus:border-[#f97066]"
                      />
                    </div>

                    {/* Contact Info */}
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-sm font-medium text-slate-700 mb-1.5">
                          Email
                        </label>
                        <input
                          type="email"
                          value={details.primary_email}
                          onChange={(e) => setDetails(prev => ({ ...prev, primary_email: e.target.value }))}
                          placeholder="contact@company.com"
                          className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#f97066]/20 focus:border-[#f97066]"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-slate-700 mb-1.5">
                          Phone
                        </label>
                        <input
                          type="tel"
                          value={details.primary_phone}
                          onChange={(e) => setDetails(prev => ({ ...prev, primary_phone: e.target.value }))}
                          placeholder="(555) 123-4567"
                          className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#f97066]/20 focus:border-[#f97066]"
                        />
                      </div>
                    </div>

                    {/* Insurance Types */}
                    <div>
                      <label className="block text-sm font-medium text-slate-700 mb-2">
                        Insurance Types Interested In
                      </label>
                      <div className="flex flex-wrap gap-2">
                        {INSURANCE_TYPE_OPTIONS.map(type => (
                          <button
                            key={type}
                            type="button"
                            onClick={() => handleInsuranceTypeToggle(type)}
                            className={`
                              px-3 py-1.5 rounded-full text-xs font-medium transition-colors
                              ${details.insurance_types?.includes(type)
                                ? 'bg-[#f97066] text-white'
                                : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                              }
                            `}
                          >
                            {type}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Notes */}
                    <div>
                      <label className="block text-sm font-medium text-slate-700 mb-1.5">
                        Notes
                      </label>
                      <textarea
                        value={details.notes}
                        onChange={(e) => setDetails(prev => ({ ...prev, notes: e.target.value }))}
                        placeholder="Any additional notes about this account..."
                        rows={3}
                        className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#f97066]/20 focus:border-[#f97066] resize-none"
                      />
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

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
                  onClick={handleConfirm}
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

// Vague Update Clarification Modal
import type { PendingVagueUpdateClarification, ClarificationField } from '../types/exploration';

interface VagueUpdateClarificationModalProps {
  clarification: PendingVagueUpdateClarification;
  onSubmit: (data: Record<string, string | string[]>) => void;
  onCancel: () => void;
  isLoading?: boolean;
}

export function VagueUpdateClarificationModal({
  clarification,
  onSubmit,
  onCancel,
  isLoading = false,
}: VagueUpdateClarificationModalProps) {
  const [formData, setFormData] = useState<Record<string, string | string[]>>({});

  const handleFieldChange = (field: ClarificationField, value: string | string[]) => {
    setFormData(prev => ({ ...prev, [field.id]: value }));
  };

  const handleMultiSelectToggle = (field: ClarificationField, option: string) => {
    const current = (formData[field.id] as string[]) || [];
    const updated = current.includes(option)
      ? current.filter(v => v !== option)
      : [...current, option];
    setFormData(prev => ({ ...prev, [field.id]: updated }));
  };

  const handleSubmit = () => {
    onSubmit(formData);
  };

  const hasChanges = Object.values(formData).some(v => 
    Array.isArray(v) ? v.length > 0 : v && v.trim() !== ''
  );

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
          className="bg-white rounded-2xl shadow-2xl max-w-lg w-full overflow-hidden max-h-[90vh] flex flex-col"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="p-6 border-b border-slate-100 flex-shrink-0">
            <div className="flex items-start gap-4">
              <div className="p-3 rounded-full bg-orange-100">
                <AlertCircle className="w-6 h-6 text-orange-600" />
              </div>
              <div className="flex-1">
                <h2 className="text-lg font-semibold text-slate-800">
                  What would you like to update?
                </h2>
                <p className="text-sm text-slate-600 mt-1">
                  {clarification.message}
                </p>
                <div className="mt-2 inline-flex items-center gap-2 px-2 py-1 rounded-lg bg-slate-100 text-xs text-slate-600">
                  <Building2 className="w-3 h-3" />
                  {clarification.account_name}
                </div>
              </div>
              <button
                onClick={onCancel}
                className="p-2 hover:bg-slate-100 rounded-lg transition-colors"
              >
                <X className="w-5 h-5 text-slate-400" />
              </button>
            </div>
          </div>

          {/* Scrollable form content */}
          <div className="overflow-y-auto flex-1 p-6">
            <div className="space-y-5">
              {clarification.clarification_fields.map((field) => (
                <div key={field.id}>
                  <label className="block text-sm font-medium text-slate-700 mb-2">
                    {field.label}
                    {field.current_value && (
                      <span className="ml-2 text-xs text-slate-400 font-normal">
                        Current: {Array.isArray(field.current_value) ? field.current_value.join(', ') : field.current_value}
                      </span>
                    )}
                  </label>

                  {field.type === 'select' && (
                    <select
                      value={(formData[field.id] as string) || ''}
                      onChange={(e) => handleFieldChange(field, e.target.value)}
                      className="w-full px-3 py-2.5 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#f97066]/20 focus:border-[#f97066]"
                    >
                      <option value="">{field.placeholder || 'Select an option...'}</option>
                      {field.options?.map(opt => (
                        <option key={opt} value={opt}>{opt}</option>
                      ))}
                    </select>
                  )}

                  {field.type === 'multi-select' && (
                    <div className="flex flex-wrap gap-2">
                      {field.options?.map(opt => {
                        const selected = ((formData[field.id] as string[]) || []).includes(opt);
                        return (
                          <button
                            key={opt}
                            type="button"
                            onClick={() => handleMultiSelectToggle(field, opt)}
                            className={`
                              px-3 py-1.5 rounded-full text-xs font-medium transition-colors
                              ${selected
                                ? 'bg-[#f97066] text-white'
                                : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                              }
                            `}
                          >
                            {opt}
                          </button>
                        );
                      })}
                    </div>
                  )}

                  {field.type === 'text' && (
                    <input
                      type="text"
                      value={(formData[field.id] as string) || ''}
                      onChange={(e) => handleFieldChange(field, e.target.value)}
                      placeholder={field.placeholder}
                      className="w-full px-3 py-2.5 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#f97066]/20 focus:border-[#f97066]"
                    />
                  )}

                  {field.type === 'textarea' && (
                    <textarea
                      value={(formData[field.id] as string) || ''}
                      onChange={(e) => handleFieldChange(field, e.target.value)}
                      placeholder={field.placeholder}
                      rows={3}
                      className="w-full px-3 py-2.5 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#f97066]/20 focus:border-[#f97066] resize-none"
                    />
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Actions */}
          <div className="p-6 border-t border-slate-100 flex-shrink-0">
            <div className="flex gap-3">
              <button
                onClick={onCancel}
                disabled={isLoading}
                className="flex-1 px-4 py-2.5 rounded-xl border border-slate-200 text-slate-700 font-medium hover:bg-slate-50 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={isLoading || !hasChanges}
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
                    Apply Update
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
