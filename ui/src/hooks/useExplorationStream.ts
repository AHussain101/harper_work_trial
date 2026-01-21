import { useState, useCallback, useRef } from 'react';
import type { 
  ExplorationState, 
  ExplorationEvent, 
  ExplorationStep,
  PendingConfirmation,
} from '../types/exploration';

const API_BASE = '/api';

const initialState: ExplorationState = {
  status: 'idle',
  query: '',
  steps: [],
  currentStep: 0,
  filesOpened: [],
  filesListed: [],
};

export function useExplorationStream() {
  const [state, setState] = useState<ExplorationState>(initialState);
  const abortControllerRef = useRef<AbortController | null>(null);
  const currentQueryRef = useRef<string>('');

  const reset = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    currentQueryRef.current = '';
    setState(initialState);
  }, []);

  const startExploration = useCallback(async (query: string) => {
    // Cancel any existing request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    // Create new abort controller
    abortControllerRef.current = new AbortController();
    currentQueryRef.current = query;

    setState({
      ...initialState,
      status: 'running',
      query,
    });

    try {
      const response = await fetch(`${API_BASE}/query/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ query }),
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error('No response body');
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        
        // Process complete SSE events
        const lines = buffer.split('\n');
        buffer = lines.pop() || ''; // Keep incomplete line in buffer

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const jsonStr = line.slice(6);
            try {
              const event: ExplorationEvent = JSON.parse(jsonStr);
              processEvent(event, setState, currentQueryRef.current);
            } catch {
              console.warn('Failed to parse SSE event:', jsonStr);
            }
          }
        }
      }
    } catch (error) {
      if ((error as Error).name === 'AbortError') {
        console.log('Exploration aborted');
        return;
      }
      
      setState(prev => ({
        ...prev,
        status: 'error',
        errorMessage: (error as Error).message,
      }));
    }
  }, []);

  const stop = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      setState(prev => ({
        ...prev,
        status: 'completed',
      }));
    }
  }, []);

  // Handle confirmation for new account creation
  const confirmAction = useCallback(async (sessionId: string, confirmed: boolean) => {
    setState(prev => ({
      ...prev,
      status: 'running',
    }));

    try {
      const response = await fetch(`${API_BASE}/confirm`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ session_id: sessionId, confirmed }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      
      if (data.type === 'success') {
        setState(prev => ({
          ...prev,
          status: 'completed',
          answer: data.answer || data.message,
          pendingConfirmation: undefined,
          routedTo: data.routed_to,
          changes: data.changes,
          historyEntryId: data.history_entry_id,
          // Rich update details
          updateDetails: data.account_id ? {
            account_id: data.account_id,
            account_name: data.account_name || '',
            files_modified: data.files_modified || [],
            qdrant_updated: data.qdrant_updated || false,
            new_description: data.new_description || '',
            state_file_path: data.state_file_path || '',
            history_file_path: data.history_file_path || '',
            previous_history_entry: data.previous_history_entry || null,
          } : undefined,
        }));
      } else if (data.type === 'error') {
        setState(prev => ({
          ...prev,
          status: 'error',
          errorMessage: data.message,
          pendingConfirmation: undefined,
        }));
      }
    } catch (error) {
      setState(prev => ({
        ...prev,
        status: 'error',
        errorMessage: (error as Error).message,
        pendingConfirmation: undefined,
      }));
    }
  }, []);

  // Cancel confirmation and reset
  const cancelConfirmation = useCallback(() => {
    setState(prev => ({
      ...prev,
      status: 'idle',
      pendingConfirmation: undefined,
      clarificationMessage: undefined,
      clarificationSuggestions: undefined,
    }));
  }, []);

  return {
    state,
    startExploration,
    stop,
    reset,
    confirmAction,
    cancelConfirmation,
  };
}

function processEvent(
  event: ExplorationEvent,
  setState: React.Dispatch<React.SetStateAction<ExplorationState>>,
  originalQuery: string
) {
  switch (event.type) {
    case 'start':
      setState(prev => ({
        ...prev,
        status: 'running',
        query: event.query,
      }));
      break;

    case 'routing':
      setState(prev => ({
        ...prev,
        intent: event.intent,
        intentConfidence: event.confidence,
        extractedAccount: event.account_name,
        routedTo: event.routed_to,
        skillLoaded: event.skill_loaded,
      }));
      break;

    case 'thinking': {
      const newStep: ExplorationStep = {
        step: event.step,
        tool: event.tool,
        args: event.args,
        reason: event.reason,
        status: 'thinking',
      };

      setState(prev => {
        // Extract listed files from list_files args
        let filesListed = prev.filesListed;
        if (event.tool === 'list_files') {
          const path = event.args.path as string;
          if (path && !filesListed.includes(path)) {
            filesListed = [...filesListed, path];
          }
        }

        return {
          ...prev,
          steps: [...prev.steps, newStep],
          currentStep: event.step,
          filesListed,
        };
      });
      break;
    }

    case 'tool_result': {
      setState(prev => {
        const updatedSteps = prev.steps.map(step => {
          if (step.step === event.step) {
            return {
              ...step,
              result: event.result,
              error: event.error,
              status: event.error ? 'error' : 'completed',
            } as ExplorationStep;
          }
          return step;
        });

        // Track listed directories from list_files results
        let filesListed = prev.filesListed;
        if (event.tool === 'list_files' && event.result && !event.error) {
          const path = event.args.path as string;
          if (path && !filesListed.includes(path)) {
            filesListed = [...filesListed, path];
          }
        }

        return {
          ...prev,
          steps: updatedSteps,
          filesOpened: event.files_opened,
          filesListed,
        };
      });
      break;
    }

    case 'final':
      setState(prev => ({
        ...prev,
        status: 'completed',
        answer: event.answer,
        citations: event.citations,
        notes: event.notes,
        routedTo: event.routed_to,
        changes: event.changes,
        historyEntryId: event.history_entry_id,
        // Rich update details
        updateDetails: event.account_id ? {
          account_id: event.account_id,
          account_name: event.account_name || '',
          files_modified: event.files_modified || [],
          qdrant_updated: event.qdrant_updated || false,
          new_description: event.new_description || '',
          state_file_path: event.state_file_path || '',
          history_file_path: event.history_file_path || '',
          previous_history_entry: event.previous_history_entry || null,
        } : undefined,
      }));
      break;

    case 'confirmation_required':
      setState(prev => ({
        ...prev,
        status: 'awaiting_confirmation',
        pendingConfirmation: {
          session_id: event.session_id,
          message: event.message,
          account_name: event.account_name,
          alternatives: event.alternatives || [],
          original_query: originalQuery,
        },
      }));
      break;

    case 'clarification_needed':
      setState(prev => ({
        ...prev,
        status: 'awaiting_clarification',
        clarificationMessage: event.message,
        clarificationSuggestions: event.suggestions,
      }));
      break;

    case 'error':
      setState(prev => ({
        ...prev,
        status: 'error',
        errorMessage: event.message,
      }));
      break;

    case 'done':
      setState(prev => ({
        ...prev,
        status: prev.status === 'running' ? 'completed' : prev.status,
      }));
      break;
  }
}
