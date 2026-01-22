// Types for the exploration visualization

export interface TreeNode {
  name: string;
  path: string;
  type: 'file' | 'directory';
  children?: TreeNode[];
}

export interface Budget {
  max_tool_calls: number;
  max_read_file: number;
  max_search: number;
}

// Response types from Starter Agent
export type ResponseType = 'success' | 'confirmation_required' | 'clarification_needed' | 'error';
export type IntentType = 'search' | 'update' | 'followup' | 'unclear';
export type AgentType = 'search_agent' | 'updater_agent' | 'followup_agent';

// Skill information
export interface SkillInfo {
  name: string;
  description: string;
  path: string;
}

// Account alternative for confirmation flow
export interface AccountAlternative {
  name: string;
  account_id: string;
  score: number;
}

// Change record from Updater Agent
export interface StateChange {
  field: string;
  old_value: string;
  new_value: string;
}

// Rich update details from Updater Agent
export interface UpdateDetails {
  account_id: string;
  account_name: string;
  files_modified: string[];
  qdrant_updated: boolean;
  new_description: string;
  state_file_path: string;
  history_file_path: string;
  previous_history_entry: string | null;
}

// Pending confirmation state
export interface PendingConfirmation {
  session_id: string;
  message: string;
  account_name: string;
  alternatives: AccountAlternative[];
  original_query: string;
}

export interface StartEvent {
  type: 'start';
  query: string;
  budget: Budget;
}

// New: Starter Agent routing event
export interface RoutingEvent {
  type: 'routing';
  intent: IntentType;
  confidence: number;
  account_name?: string;
  routed_to: AgentType;
  skill_loaded?: SkillInfo;
}

export interface ThinkingEvent {
  type: 'thinking';
  step: number;
  tool: string;
  args: Record<string, unknown>;
  reason: string;
  budget_status: string;
}

export interface ToolResultEvent {
  type: 'tool_result';
  step: number;
  tool: string;
  args: Record<string, unknown>;
  result: string | null;
  error: string | null;
  files_opened: string[];
  budget_status: string;
}

export interface FinalEvent {
  type: 'final';
  answer: string;
  citations: string[];
  notes: string;
  trace_summary: string[];
  trace?: TraceData;
  budget_exhausted?: boolean;
  // Multi-agent fields
  routed_to?: AgentType;
  changes?: StateChange[];
  history_entry_id?: string;
  // Rich update details
  account_id?: string;
  account_name?: string;
  files_modified?: string[];
  qdrant_updated?: boolean;
  new_description?: string;
  state_file_path?: string;
  history_file_path?: string;
  previous_history_entry?: string;
}

export interface ConfirmationEvent {
  type: 'confirmation_required';
  message: string;
  session_id: string;
  account_name: string;
  alternatives: AccountAlternative[];
}

export interface ClarificationEvent {
  type: 'clarification_needed';
  message: string;
  suggestions?: string[];
  extracted_account?: string;
}

// Clarification field for vague update forms
export interface ClarificationField {
  id: string;
  label: string;
  type: 'select' | 'multi-select' | 'text' | 'textarea';
  options?: string[];
  placeholder?: string;
  current_value?: string | string[];
}

// Vague update clarification event
export interface VagueUpdateClarificationEvent {
  type: 'vague_update_clarification';
  message: string;
  session_id: string;
  account_id: string;
  account_name: string;
  clarification_fields: ClarificationField[];
  original_query: string;
}

// Pending vague update clarification
export interface PendingVagueUpdateClarification {
  session_id: string;
  message: string;
  account_id: string;
  account_name: string;
  clarification_fields: ClarificationField[];
  original_query: string;
}

export interface ErrorEvent {
  type: 'error';
  message: string;
  trace?: TraceData;
}

export interface DoneEvent {
  type: 'done';
}

export type ExplorationEvent = 
  | StartEvent 
  | RoutingEvent
  | ThinkingEvent 
  | ToolResultEvent 
  | FinalEvent 
  | ConfirmationEvent
  | ClarificationEvent
  | VagueUpdateClarificationEvent
  | ErrorEvent 
  | DoneEvent;

export interface ToolCallData {
  tool: string;
  args: Record<string, unknown>;
  reason: string;
}

export interface TraceData {
  question: string;
  tool_calls: ToolCallData[];
  files_opened: string[];
  stop_reason: string;
  invalid_citations_removed: string[];
  budget_status: string;
}

export type NodeState = 'unexplored' | 'exploring' | 'listed' | 'read' | 'error';

export interface ExplorationStep {
  step: number;
  tool: string;
  args: Record<string, unknown>;
  reason: string;
  result?: string | null;
  error?: string | null;
  status: 'thinking' | 'executing' | 'completed' | 'error';
}

export interface ExplorationState {
  status: 'idle' | 'running' | 'completed' | 'error' | 'awaiting_confirmation' | 'awaiting_clarification' | 'awaiting_vague_update_clarification';
  query: string;
  steps: ExplorationStep[];
  currentStep: number;
  filesOpened: string[];
  filesListed: string[];
  answer?: string;
  citations?: string[];
  notes?: string;
  errorMessage?: string;
  // Multi-agent state
  intent?: IntentType;
  intentConfidence?: number;
  extractedAccount?: string;
  routedTo?: AgentType;
  skillLoaded?: SkillInfo;
  changes?: StateChange[];
  historyEntryId?: string;
  pendingConfirmation?: PendingConfirmation;
  clarificationMessage?: string;
  clarificationSuggestions?: string[];
  // Vague update clarification
  pendingVagueUpdateClarification?: PendingVagueUpdateClarification;
  // Rich update details
  updateDetails?: UpdateDetails;
  // Follow-up details
  followupDraft?: {
    channel: string;
    subject?: string;
    body: string;
  };
  followupSent?: boolean;
}

export interface FileContent {
  path: string;
  name: string;
  content: string;
  size: number;
  extension: string;
}
