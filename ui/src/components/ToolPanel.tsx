import { motion, AnimatePresence } from 'framer-motion';
import { 
  Search, 
  FolderOpen, 
  FileText, 
  Users, 
  FileSearch,
  Loader2,
  CheckCircle,
  XCircle,
  Brain,
  Sparkles,
  ChevronDown,
  ChevronRight,
  GitFork,
  Edit3,
  ArrowRight,
  History,
  Database,
  File,
  Link,
  Hash,
  Compass,
  Target,
  Zap,
  BookOpen,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import type { ExplorationStep, ExplorationState, StateChange, UpdateDetails, SkillInfo, IntentType, AgentType } from '../types/exploration';
import { useState } from 'react';

interface ToolPanelProps {
  state: ExplorationState;
}

const toolConfig: Record<string, { icon: React.ReactNode; color: string; bgColor: string; label: string }> = {
  list_files: { 
    icon: <FolderOpen className="w-4 h-4" />, 
    color: 'text-amber-700',
    bgColor: 'bg-amber-100',
    label: 'List Files'
  },
  read_file: { 
    icon: <FileText className="w-4 h-4" />, 
    color: 'text-emerald-700',
    bgColor: 'bg-emerald-100',
    label: 'Read File'
  },
  search_files: { 
    icon: <Search className="w-4 h-4" />, 
    color: 'text-purple-700',
    bgColor: 'bg-purple-100',
    label: 'Search'
  },
  lookup_account: { 
    icon: <Users className="w-4 h-4" />, 
    color: 'text-blue-700',
    bgColor: 'bg-blue-100',
    label: 'Lookup Account'
  },
  search_descriptions: { 
    icon: <FileSearch className="w-4 h-4" />, 
    color: 'text-cyan-700',
    bgColor: 'bg-cyan-100',
    label: 'Search Descriptions'
  },
};

function ToolStepCard({ step, isLatest }: { step: ExplorationStep; isLatest: boolean }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const config = toolConfig[step.tool] || { 
    icon: <Brain className="w-4 h-4" />, 
    color: 'text-slate-700',
    bgColor: 'bg-slate-100',
    label: step.tool
  };
  
  const statusIcon = {
    thinking: <Loader2 className="w-4 h-4 animate-spin text-[#f97066]" />,
    executing: <Loader2 className="w-4 h-4 animate-spin text-amber-500" />,
    completed: <CheckCircle className="w-4 h-4 text-emerald-500" />,
    error: <XCircle className="w-4 h-4 text-red-500" />,
  };

  // Format args for display
  const formatArgs = (args: Record<string, unknown>) => {
    return Object.entries(args)
      .map(([key, value]) => {
        const strValue = typeof value === 'string' ? value : JSON.stringify(value);
        const truncated = strValue.length > 50 ? strValue.slice(0, 50) + '...' : strValue;
        return { key, value: truncated };
      });
  };

  // Truncate result for preview
  const getResultPreview = (result: string | null | undefined) => {
    if (!result) return null;
    const lines = result.split('\n');
    if (lines.length <= 4) return result;
    return lines.slice(0, 4).join('\n') + '\n...';
  };

  const showResult = step.result && (isExpanded || (isLatest && step.status === 'completed'));

  return (
    <motion.div
      initial={{ opacity: 0, y: 20, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.3, ease: 'easeOut' }}
      className={`
        tool-card overflow-hidden
        ${isLatest && step.status === 'thinking' ? 'ring-2 ring-[#f97066]/30 shadow-lg' : ''}
      `}
    >
      <div 
        className="p-4 cursor-pointer"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        {/* Header */}
        <div className="flex items-center gap-3">
          <span className="text-slate-400 text-sm font-mono w-6">#{step.step}</span>
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full ${config.bgColor} ${config.color}`}>
            {config.icon}
            <span className="text-sm font-medium">{config.label}</span>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {statusIcon[step.status]}
            <motion.div
              animate={{ rotate: isExpanded ? 180 : 0 }}
              transition={{ duration: 0.2 }}
              className="text-slate-400"
            >
              <ChevronDown className="w-4 h-4" />
            </motion.div>
          </div>
        </div>
        
        {/* Arguments */}
        <div className="mt-3 flex flex-wrap gap-2">
          {formatArgs(step.args).map(({ key, value }) => (
            <div key={key} className="text-xs bg-slate-50 rounded-lg px-2 py-1 border border-slate-200">
              <span className="text-slate-500">{key}:</span>{' '}
              <span className="text-slate-700 font-mono">{value}</span>
            </div>
          ))}
        </div>
        
        {/* Reason/Thinking */}
        {step.reason && (
          <div className="mt-3 flex items-start gap-2 text-sm text-slate-600 bg-blue-50 rounded-lg p-3 border border-blue-100">
            <Brain className="w-4 h-4 text-blue-500 flex-shrink-0 mt-0.5" />
            <span className="italic">
              <ReactMarkdown
                components={{
                  p: ({ children }) => <span>{children}</span>,
                  strong: ({ children }) => <span className="font-semibold">{children}</span>,
                }}
              >
                {`"${step.reason}"`}
              </ReactMarkdown>
            </span>
          </div>
        )}
      </div>
      
      {/* Expandable result section */}
      <AnimatePresence>
        {showResult && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="border-t border-slate-100 bg-slate-50"
          >
            <div className="p-4">
              <div className="text-xs text-slate-500 mb-2 flex items-center gap-1">
                <ChevronRight className="w-3 h-3" />
                Result
              </div>
              <pre className="text-xs text-slate-700 whitespace-pre-wrap break-words max-h-64 overflow-auto bg-white rounded-lg p-3 border border-slate-200">
                {isExpanded ? step.result : getResultPreview(step.result)}
              </pre>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      
      {/* Error display */}
      {step.error && (
        <div className="border-t border-red-200 bg-red-50 p-4">
          <div className="text-sm text-red-600 flex items-start gap-2">
            <XCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            {step.error}
          </div>
        </div>
      )}
    </motion.div>
  );
}

function UpdateResultCard({ 
  changes, 
  historyEntryId,
  updateDetails 
}: { 
  changes: StateChange[]; 
  historyEntryId?: string;
  updateDetails?: UpdateDetails;
}) {
  const [showDetails, setShowDetails] = useState(false);
  
  return (
    <motion.div
      initial={{ opacity: 0, y: 20, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.3, ease: 'easeOut' }}
      className="tool-card overflow-hidden border-2 border-emerald-200 bg-emerald-50"
    >
      <div className="p-4">
        {/* Header */}
        <div className="flex items-center gap-3 mb-4">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-100 text-emerald-700">
            <Edit3 className="w-4 h-4" />
            <span className="text-sm font-medium">Changes Applied</span>
          </div>
          <CheckCircle className="w-5 h-5 text-emerald-500 ml-auto" />
        </div>
        
        {/* Account Info */}
        {updateDetails && (
          <div className="mb-4 p-3 bg-white rounded-lg border border-emerald-200">
            <div className="flex items-center gap-2 text-sm">
              <Hash className="w-4 h-4 text-slate-400" />
              <span className="text-slate-500">Account ID:</span>
              <span className="font-mono font-medium text-slate-700">{updateDetails.account_id}</span>
              <span className="text-slate-300 mx-2">|</span>
              <span className="text-slate-700 font-medium">{updateDetails.account_name}</span>
            </div>
          </div>
        )}
        
        {/* Changes list */}
        <div className="space-y-2 mb-4">
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-2">
            State Changes (old → new)
          </div>
          {changes.map((change, idx) => (
            <div key={idx} className="flex items-center gap-2 text-sm bg-white rounded-lg p-3 border border-emerald-200">
              <span className="font-medium text-slate-700 capitalize min-w-[80px]">{change.field}:</span>
              <span className="text-red-500 line-through">{change.old_value || '(empty)'}</span>
              <ArrowRight className="w-4 h-4 text-emerald-500 flex-shrink-0" />
              <span className="text-emerald-700 font-medium">{change.new_value}</span>
            </div>
          ))}
        </div>
        
        {/* Files Modified */}
        {updateDetails && updateDetails.files_modified.length > 0 && (
          <div className="mb-4">
            <div className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-2">
              Files Modified
            </div>
            <div className="space-y-1">
              {updateDetails.files_modified.map((file, idx) => (
                <div key={idx} className="flex items-center gap-2 text-xs bg-white rounded p-2 border border-slate-200">
                  <File className="w-3 h-3 text-blue-500" />
                  <span className="font-mono text-slate-600">{file}</span>
                  <CheckCircle className="w-3 h-3 text-emerald-500 ml-auto" />
                </div>
              ))}
            </div>
          </div>
        )}
        
        {/* Qdrant Update Status */}
        {updateDetails && (
          <div className="mb-4">
            <div className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-2">
              Vector Database (Qdrant)
            </div>
            <div className={`flex items-center gap-2 text-sm p-3 rounded-lg border ${
              updateDetails.qdrant_updated 
                ? 'bg-emerald-50 border-emerald-200' 
                : 'bg-amber-50 border-amber-200'
            }`}>
              <Database className={`w-4 h-4 ${updateDetails.qdrant_updated ? 'text-emerald-500' : 'text-amber-500'}`} />
              <span className={updateDetails.qdrant_updated ? 'text-emerald-700' : 'text-amber-700'}>
                {updateDetails.qdrant_updated ? 'Description vector updated' : 'Qdrant update skipped'}
              </span>
              {updateDetails.qdrant_updated && <CheckCircle className="w-4 h-4 text-emerald-500 ml-auto" />}
            </div>
            {updateDetails.qdrant_updated && updateDetails.new_description && (
              <div 
                className="mt-2 text-xs text-slate-500 bg-white p-2 rounded border border-slate-200 cursor-pointer hover:bg-slate-50"
                onClick={() => setShowDetails(!showDetails)}
              >
                <div className="flex items-center gap-1 font-medium mb-1">
                  <ChevronRight className={`w-3 h-3 transition-transform ${showDetails ? 'rotate-90' : ''}`} />
                  New description
                </div>
                {showDetails && (
                  <div className="mt-1 font-mono text-slate-600 break-words">
                    {updateDetails.new_description}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
        
        {/* History Chain */}
        <div className="border-t border-emerald-200 pt-4">
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-2">
            History Chain
          </div>
          <div className="bg-white rounded-lg p-3 border border-slate-200">
            {updateDetails?.previous_history_entry && (
              <div className="flex items-center gap-2 text-xs text-slate-500 mb-2">
                <Link className="w-3 h-3" />
                <span>Previous entry:</span>
                <span className="font-mono text-slate-600">{updateDetails.previous_history_entry}</span>
              </div>
            )}
            {historyEntryId && (
              <div className="flex items-center gap-2 text-sm">
                <History className="w-4 h-4 text-emerald-500" />
                <span className="text-slate-600">New entry:</span>
                <span className="font-mono font-medium text-emerald-700">{historyEntryId}</span>
              </div>
            )}
            {updateDetails?.history_file_path && (
              <div className="flex items-center gap-2 text-xs text-slate-400 mt-2">
                <File className="w-3 h-3" />
                <span className="font-mono">{updateDetails.history_file_path}</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </motion.div>
  );
}

function AgentRoutingIndicator({ routedTo }: { routedTo: 'search_agent' | 'updater_agent' }) {
  const isSearch = routedTo === 'search_agent';
  
  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      className={`
        inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium
        ${isSearch ? 'bg-blue-100 text-blue-700' : 'bg-orange-100 text-orange-700'}
      `}
    >
      <GitFork className="w-4 h-4" />
      <span>{isSearch ? 'Search Agent' : 'Updater Agent'}</span>
    </motion.div>
  );
}

// New: Starter Agent thinking card
function StarterAgentCard({ 
  intent, 
  confidence, 
  extractedAccount, 
  routedTo, 
  skillLoaded 
}: { 
  intent?: IntentType; 
  confidence?: number; 
  extractedAccount?: string;
  routedTo?: AgentType;
  skillLoaded?: SkillInfo;
}) {
  const [isExpanded, setIsExpanded] = useState(true);
  
  if (!intent && !routedTo) return null;
  
  const intentConfig = {
    search: { color: 'text-blue-700', bg: 'bg-blue-100', label: 'Search (read-only)' },
    update: { color: 'text-orange-700', bg: 'bg-orange-100', label: 'Update (write)' },
    unclear: { color: 'text-amber-700', bg: 'bg-amber-100', label: 'Unclear' },
  };
  
  const config = intent ? intentConfig[intent] : intentConfig.search;
  const confidencePercent = confidence ? Math.round(confidence * 100) : 0;
  
  return (
    <motion.div
      initial={{ opacity: 0, y: 20, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.3, ease: 'easeOut' }}
      className="tool-card overflow-hidden border-2 border-purple-200 bg-purple-50"
    >
      <div 
        className="p-4 cursor-pointer"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        {/* Header */}
        <div className="flex items-center gap-3 mb-3">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-purple-100 text-purple-700">
            <Compass className="w-4 h-4" />
            <span className="text-sm font-medium">Starter Agent</span>
          </div>
          <span className="text-xs text-purple-500 font-medium">Intent Classification & Routing</span>
          <CheckCircle className="w-4 h-4 text-purple-500 ml-auto" />
        </div>
        
        <AnimatePresence>
          {isExpanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="space-y-3"
            >
              {/* Intent Classification */}
              <div className="bg-white rounded-lg p-3 border border-purple-200">
                <div className="flex items-center gap-2 text-xs font-medium text-slate-500 uppercase tracking-wide mb-2">
                  <Target className="w-3 h-3" />
                  Intent Classification
                </div>
                <div className="flex items-center gap-3">
                  <div className={`px-2 py-1 rounded-full text-xs font-medium ${config.bg} ${config.color}`}>
                    {config.label}
                  </div>
                  {confidence !== undefined && (
                    <div className="flex items-center gap-2 text-xs text-slate-500">
                      <div className="w-20 h-1.5 bg-slate-200 rounded-full overflow-hidden">
                        <div 
                          className="h-full bg-purple-500 rounded-full transition-all"
                          style={{ width: `${confidencePercent}%` }}
                        />
                      </div>
                      <span>{confidencePercent}% confident</span>
                    </div>
                  )}
                </div>
                {extractedAccount && (
                  <div className="mt-2 text-sm text-slate-600">
                    <span className="text-slate-400">Account:</span>{' '}
                    <span className="font-medium">"{extractedAccount}"</span>
                  </div>
                )}
              </div>
              
              {/* Routing Decision */}
              {routedTo && (
                <div className="bg-white rounded-lg p-3 border border-purple-200">
                  <div className="flex items-center gap-2 text-xs font-medium text-slate-500 uppercase tracking-wide mb-2">
                    <GitFork className="w-3 h-3" />
                    Routing Decision
                  </div>
                  <div className="flex items-center gap-2">
                    <ArrowRight className="w-4 h-4 text-purple-500" />
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                      routedTo === 'search_agent' ? 'bg-blue-100 text-blue-700' : 'bg-orange-100 text-orange-700'
                    }`}>
                      {routedTo === 'search_agent' ? 'Search Agent' : 'Updater Agent'}
                    </span>
                  </div>
                </div>
              )}
              
              {/* Skill Loaded */}
              {skillLoaded && (
                <div className="bg-white rounded-lg p-3 border border-purple-200">
                  <div className="flex items-center gap-2 text-xs font-medium text-slate-500 uppercase tracking-wide mb-2">
                    <BookOpen className="w-3 h-3" />
                    Skill Loaded
                  </div>
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <Zap className="w-4 h-4 text-amber-500" />
                      <span className="font-medium text-slate-700">{skillLoaded.name}</span>
                    </div>
                    <p className="text-xs text-slate-500 pl-6">{skillLoaded.description}</p>
                    <div className="text-xs font-mono text-slate-400 pl-6">{skillLoaded.path}</div>
                  </div>
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

export function ToolPanel({ state }: ToolPanelProps) {
  const { 
    status, 
    query, 
    steps, 
    routedTo, 
    changes, 
    historyEntryId, 
    updateDetails,
    intent,
    intentConfidence,
    extractedAccount,
    skillLoaded,
  } = state;

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="p-5 border-b border-[#e7d7ce] flex-shrink-0 bg-white/50">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold text-slate-800 flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-[#f97066]" />
            Agent Journey
          </h2>
          {routedTo && <AgentRoutingIndicator routedTo={routedTo} />}
        </div>
        {query && (
          <p className="text-sm text-slate-500 mt-1">
            Exploring: <span className="text-slate-700">"{query}"</span>
          </p>
        )}
      </div>
      
      {/* Steps list */}
      <div className="flex-1 overflow-auto p-5 space-y-4">
        {status === 'idle' && (
          <div className="text-center py-16">
            <div className="w-20 h-20 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-[#fdf0e9] to-[#f5e6dd] flex items-center justify-center border border-[#e7d7ce]">
              <Brain className="w-10 h-10 text-[#f97066]/50" />
            </div>
            <h3 className="text-lg font-medium text-slate-700 mb-2">Ready to Explore</h3>
            <p className="text-slate-500 text-sm max-w-sm mx-auto">
              Enter a query above or select one from the sample queries to watch the agent explore your data.
            </p>
          </div>
        )}
        
        {/* Starter Agent routing card */}
        {(intent || routedTo) && (
          <StarterAgentCard
            intent={intent}
            confidence={intentConfidence}
            extractedAccount={extractedAccount}
            routedTo={routedTo}
            skillLoaded={skillLoaded}
          />
        )}
        
        {/* Tool call steps */}
        {steps.map((step, index) => (
          <ToolStepCard 
            key={step.step} 
            step={step} 
            isLatest={index === steps.length - 1}
          />
        ))}
        
        {/* Show update results if this was an update operation */}
        {status === 'completed' && changes && changes.length > 0 && (
          <UpdateResultCard 
            changes={changes} 
            historyEntryId={historyEntryId} 
            updateDetails={updateDetails}
          />
        )}
        
        {status === 'running' && steps.length === 0 && (
          <div className="text-center py-16">
            <Loader2 className="w-10 h-10 mx-auto mb-4 animate-spin text-[#f97066]" />
            <p className="text-slate-500">Starting exploration...</p>
          </div>
        )}
        
        {status === 'awaiting_confirmation' && (
          <div className="text-center py-16">
            <div className="w-20 h-20 mx-auto mb-4 rounded-2xl bg-amber-100 flex items-center justify-center border border-amber-200">
              <Brain className="w-10 h-10 text-amber-600" />
            </div>
            <h3 className="text-lg font-medium text-slate-700 mb-2">Awaiting Confirmation</h3>
            <p className="text-slate-500 text-sm max-w-sm mx-auto">
              Please respond to the confirmation dialog.
            </p>
          </div>
        )}
        
        {status === 'awaiting_clarification' && (
          <div className="text-center py-16">
            <div className="w-20 h-20 mx-auto mb-4 rounded-2xl bg-blue-100 flex items-center justify-center border border-blue-200">
              <Brain className="w-10 h-10 text-blue-600" />
            </div>
            <h3 className="text-lg font-medium text-slate-700 mb-2">Need Clarification</h3>
            <p className="text-slate-500 text-sm max-w-sm mx-auto">
              {state.clarificationMessage}
            </p>
          </div>
        )}
      </div>
      
      {/* Error section */}
      {status === 'error' && state.errorMessage && (
        <div className="border-t border-red-200 bg-red-50 p-5 flex-shrink-0">
          <div className="flex items-center gap-2 mb-2">
            <XCircle className="w-5 h-5 text-red-500" />
            <span className="font-semibold text-red-700">Error</span>
          </div>
          <div className="text-sm text-red-600">
            {state.errorMessage}
          </div>
        </div>
      )}
    </div>
  );
}
