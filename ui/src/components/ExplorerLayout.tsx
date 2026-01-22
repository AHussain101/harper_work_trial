import { useState, useMemo } from 'react';
import { motion } from 'framer-motion';
import { FileTree } from './FileTree';
import { ToolPanel } from './ToolPanel';
import { FilePreview } from './FilePreview';
import { QueryInput } from './QueryInput';
import { QuerySelector } from './QuerySelector';
import { ConfirmationModal, ClarificationModal, VagueUpdateClarificationModal } from './ConfirmationModal';
import type { NewAccountDetails } from './ConfirmationModal';
import { useExplorationStream } from '../hooks/useExplorationStream';
import { 
  RotateCcw,
  GitBranch,
  FileText,
  Activity,
  Eye,
  GitFork,
} from 'lucide-react';

export function ExplorerLayout() {
  const { state, startExploration, stop, reset, confirmAction, cancelConfirmation, submitVagueUpdateClarification } = useExplorationStream();
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'queries' | 'files'>('queries');
  const [isConfirming, setIsConfirming] = useState(false);
  const [isSubmittingClarification, setIsSubmittingClarification] = useState(false);

  // Get the current path being explored
  const currentPath = useMemo(() => {
    if (state.status !== 'running') return undefined;
    const latestStep = state.steps[state.steps.length - 1];
    if (!latestStep || latestStep.status !== 'thinking') return undefined;
    return latestStep.args?.path as string | undefined;
  }, [state.steps, state.status]);

  const handleFileClick = (path: string) => {
    setSelectedFile(path);
  };

  const handleClosePreview = () => {
    setSelectedFile(null);
  };

  const handleReset = () => {
    reset();
    setSelectedFile(null);
  };

  const handleSelectQuery = (query: string) => {
    startExploration(query);
    setActiveTab('files');
  };

  const handleConfirm = async (details?: NewAccountDetails) => {
    if (!state.pendingConfirmation) return;
    setIsConfirming(true);
    await confirmAction(state.pendingConfirmation.session_id, true, details);
    setIsConfirming(false);
  };

  const handleCancelConfirmation = () => {
    cancelConfirmation();
  };

  const handleVagueUpdateSubmit = async (data: Record<string, string | string[]>) => {
    if (!state.pendingVagueUpdateClarification) return;
    setIsSubmittingClarification(true);
    await submitVagueUpdateClarification(state.pendingVagueUpdateClarification.session_id, data);
    setIsSubmittingClarification(false);
  };

  const handleSelectAlternative = (accountId: string, accountName: string) => {
    // Re-run the query with the correct account name
    cancelConfirmation();
    const newQuery = state.pendingConfirmation?.original_query.replace(
      state.pendingConfirmation?.account_name || '',
      accountName
    ) || '';
    if (newQuery) {
      startExploration(newQuery);
    }
  };

  const handleSelectSuggestion = (suggestion: string) => {
    cancelConfirmation();
    startExploration(suggestion);
  };

  return (
    <div className="h-screen flex flex-col" style={{ backgroundColor: '#fdf0e9' }}>
      {/* Confirmation Modal */}
      {console.log('[Harper Debug] Modal check:', {
        status: state.status,
        hasPendingConfirmation: !!state.pendingConfirmation,
        pendingConfirmation: state.pendingConfirmation,
        answer: state.answer,
      })}
      {state.status === 'awaiting_confirmation' && state.pendingConfirmation && (
        <ConfirmationModal
          confirmation={state.pendingConfirmation}
          onConfirm={handleConfirm}
          onCancel={handleCancelConfirmation}
          onSelectAlternative={handleSelectAlternative}
          isLoading={isConfirming}
        />
      )}

      {/* Clarification Modal */}
      {state.status === 'awaiting_clarification' && state.clarificationMessage && (
        <ClarificationModal
          message={state.clarificationMessage}
          suggestions={state.clarificationSuggestions}
          onSelectSuggestion={handleSelectSuggestion}
          onCancel={handleCancelConfirmation}
        />
      )}

      {/* Vague Update Clarification Modal */}
      {state.status === 'awaiting_vague_update_clarification' && state.pendingVagueUpdateClarification && (
        <VagueUpdateClarificationModal
          clarification={state.pendingVagueUpdateClarification}
          onSubmit={handleVagueUpdateSubmit}
          onCancel={handleCancelConfirmation}
          isLoading={isSubmittingClarification}
        />
      )}

      {/* Top bar */}
      <header className="flex-shrink-0 border-b border-[#e7d7ce] bg-white/80 backdrop-blur-xl">
        <div className="flex items-center gap-4 px-6 py-4">
          {/* Logo/Title - Harper style */}
          <div className="flex items-center gap-3 flex-shrink-0">
            <h1 className="text-2xl font-light tracking-tight" style={{ color: '#0d9488' }}>
              Harper
            </h1>
            <span className="text-slate-300">|</span>
            <span className="text-slate-600 text-sm">Explorer</span>
          </div>

          {/* Search input */}
          <div className="flex-1 max-w-2xl mx-4">
            <QueryInput
              onSubmit={startExploration}
              onStop={stop}
              isRunning={state.status === 'running'}
            />
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              onClick={handleReset}
              className="flex items-center gap-2 px-4 py-2 hover:bg-slate-100 rounded-full transition-colors text-slate-600 hover:text-slate-900"
              title="Reset"
            >
              <RotateCcw className="w-4 h-4" />
              <span className="text-sm font-medium">Reset</span>
            </button>
          </div>
        </div>

        {/* Status bar */}
        {state.status !== 'idle' && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            className="px-6 py-3 border-t border-[#e7d7ce] flex items-center gap-6 text-sm bg-white/50"
          >
            <StatusIndicator status={state.status} />
            
            {state.routedTo && (
              <div className={`flex items-center gap-2 ${
                state.routedTo === 'search_agent' ? 'text-blue-600' : 
                state.routedTo === 'followup_agent' ? 'text-purple-600' : 
                'text-orange-600'
              }`}>
                <GitFork className="w-4 h-4" />
                <span className="font-medium">
                  {state.routedTo === 'search_agent' ? 'Search Agent' : 
                   state.routedTo === 'followup_agent' ? 'Follow-Up Agent' : 
                   'Updater Agent'}
                </span>
              </div>
            )}
            
            <div className="flex items-center gap-2 text-slate-500">
              <Activity className="w-4 h-4" />
              <span>{state.steps.length} steps</span>
            </div>
            
            <div className="flex items-center gap-2 text-slate-500">
              <Eye className="w-4 h-4" />
              <span>{state.filesOpened.length} files read</span>
            </div>
            
            {state.query && (
              <div className="flex-1 truncate text-slate-400 italic">
                "{state.query}"
              </div>
            )}
          </motion.div>
        )}
      </header>

      {/* Main content area */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left panel - Query Selector / File Tree */}
        <aside className="w-80 flex-shrink-0 border-r border-[#e7d7ce] bg-white flex flex-col overflow-hidden">
          {/* Tab switcher */}
          <div className="flex border-b border-[#e7d7ce] flex-shrink-0">
            <button
              onClick={() => setActiveTab('queries')}
              className={`
                flex-1 px-4 py-3 text-sm font-medium transition-colors
                flex items-center justify-center gap-2
                ${activeTab === 'queries' 
                  ? 'text-[#f97066] border-b-2 border-[#f97066] bg-[#fdf0e9]' 
                  : 'text-slate-500 hover:text-slate-700 hover:bg-slate-50'
                }
              `}
            >
              <GitBranch className="w-4 h-4" />
              Queries
            </button>
            <button
              onClick={() => setActiveTab('files')}
              className={`
                flex-1 px-4 py-3 text-sm font-medium transition-colors
                flex items-center justify-center gap-2
                ${activeTab === 'files' 
                  ? 'text-[#f97066] border-b-2 border-[#f97066] bg-[#fdf0e9]' 
                  : 'text-slate-500 hover:text-slate-700 hover:bg-slate-50'
                }
              `}
            >
              <FileText className="w-4 h-4" />
              Files
            </button>
          </div>
          
          {/* Tab content */}
          <div className="flex-1 overflow-hidden">
            {activeTab === 'queries' ? (
              <QuerySelector
                onSelectQuery={handleSelectQuery}
                isRunning={state.status === 'running'}
              />
            ) : (
              <FileTree
                filesOpened={state.filesOpened}
                filesListed={state.filesListed}
                currentPath={currentPath}
                onFileClick={handleFileClick}
              />
            )}
          </div>
        </aside>

        {/* Center panel - Tool calls / Agent journey */}
        <main className="flex-1 overflow-hidden" style={{ backgroundColor: '#fdf0e9' }}>
          <ToolPanel state={state} />
        </main>

        {/* Right panel - File Preview / Answer */}
        <aside className="w-96 flex-shrink-0 border-l border-[#e7d7ce] bg-white overflow-hidden">
          <FilePreview
            path={selectedFile}
            filesOpened={state.filesOpened}
            onClose={handleClosePreview}
            answer={state.answer}
            notes={state.notes}
            citations={state.citations}
            isComplete={state.status === 'completed'}
          />
        </aside>
      </div>
    </div>
  );
}

function StatusIndicator({ status }: { status: string }) {
  const statusConfig: Record<string, { color: string; bg: string; label: string }> = {
    idle: { color: 'text-slate-500', bg: 'bg-slate-400', label: 'Ready' },
    running: { color: 'text-[#f97066]', bg: 'bg-[#f97066]', label: 'Exploring' },
    completed: { color: 'text-emerald-600', bg: 'bg-emerald-500', label: 'Complete' },
    error: { color: 'text-red-600', bg: 'bg-red-500', label: 'Error' },
    awaiting_confirmation: { color: 'text-amber-600', bg: 'bg-amber-500', label: 'Awaiting Confirmation' },
    awaiting_clarification: { color: 'text-blue-600', bg: 'bg-blue-500', label: 'Need Clarification' },
    awaiting_vague_update_clarification: { color: 'text-orange-600', bg: 'bg-orange-500', label: 'What to Update?' },
  };

  const config = statusConfig[status] || statusConfig.idle;
  const isPulsing = status === 'running' || status === 'awaiting_confirmation' || status === 'awaiting_clarification' || status === 'awaiting_vague_update_clarification';

  return (
    <div className={`flex items-center gap-2 ${config.color}`}>
      <span className={`w-2 h-2 rounded-full ${config.bg} ${isPulsing ? 'animate-pulse' : ''}`} />
      <span className="font-medium">{config.label}</span>
    </div>
  );
}
