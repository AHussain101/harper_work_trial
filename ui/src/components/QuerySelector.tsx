import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  ChevronRight,
  Play,
  User,
  Users,
  FileSearch,
  MessageSquare,
  AlertCircle,
  Compass,
  Sparkles,
  Edit3,
  PlusCircle,
} from 'lucide-react';

interface QuerySelectorProps {
  onSelectQuery: (query: string) => void;
  isRunning: boolean;
}

interface QueryCategory {
  name: string;
  icon: React.ReactNode;
  color: string;
  bgColor: string;
  description: string;
  queries: string[];
}

const QUERY_CATEGORIES: QueryCategory[] = [
  {
    name: "Updates & Actions",
    icon: <Edit3 className="w-4 h-4" />,
    color: "text-orange-600",
    bgColor: "bg-orange-50",
    description: "State changes and account updates (Updater Agent)",
    queries: [
      "Mark Maple Avenue Dental as Quoted",
      "Add note to Maple Avenue Dental: Client prefers email contact",
      "Update Maple Avenue Dental to Application Received stage",
      "Add Workers Comp coverage type to Maple Avenue Dental",
      "Mark that dental practice as needing follow-up",
    ],
  },
  {
    name: "New Accounts",
    icon: <PlusCircle className="w-4 h-4" />,
    color: "text-green-600",
    bgColor: "bg-green-50",
    description: "Create new accounts (triggers confirmation)",
    queries: [
      "Add a note to ABC Insurance Corp",
      "What is the status of New Company LLC?",
      "Mark XYZ Security Services as a new lead",
      "Update Acme Industries to Quoted stage",
    ],
  },
  {
    name: "Level 1: Single Account",
    icon: <User className="w-4 h-4" />,
    color: "text-blue-600",
    bgColor: "bg-blue-50",
    description: "Basic queries about one account",
    queries: [
      "What is the current status of Maple Avenue Dental?",
      "When did we last communicate with Maple Avenue Dental?",
      "What coverage types does Maple Avenue Dental have?",
      "What documents are we waiting for from Maple Avenue Dental?",
      "Who is the primary contact at Maple Avenue Dental?",
    ],
  },
  {
    name: "Level 2: Multi-Source",
    icon: <FileSearch className="w-4 h-4" />,
    color: "text-teal-600",
    bgColor: "bg-teal-50",
    description: "Cross-channel synthesis with source attribution",
    queries: [
      "Summarize all communication with Maple Avenue Dental about their coverage.",
      "What did the customer say in the call versus what's in the emails?",
      "Give me a complete picture of where we are with Maple Avenue Dental.",
      "Are there any inconsistencies in the data for Maple Avenue Dental?",
      "Show me the evidence for Maple Avenue Dental's current stage.",
    ],
  },
  {
    name: "Level 3: Cross-Account",
    icon: <Users className="w-4 h-4" />,
    color: "text-purple-600",
    bgColor: "bg-purple-50",
    description: "Brokerage-level and implicit resolution",
    queries: [
      "Which accounts in the application phase need follow-up?",
      "What's the oldest outstanding document request we have?",
      "How many accounts are submitted to underwriter?",
      "That dental practice - where are they in the process?",
      "The account that needs follow-up",
    ],
  },
  {
    name: "Follow-Up Actions",
    icon: <MessageSquare className="w-4 h-4" />,
    color: "text-[#f97066]",
    bgColor: "bg-[#fdf0e9]",
    description: "Action drafting and channel recommendations",
    queries: [
      "What follow-up should we do for Maple Avenue Dental?",
      "Which accounts need follow-up today?",
      "Draft an email to the underwriter requesting a quote.",
      "Write a follow-up SMS about pending documents.",
      "Should we call or email about background check documents?",
    ],
  },
  {
    name: "Edge Cases",
    icon: <AlertCircle className="w-4 h-4" />,
    color: "text-amber-600",
    bgColor: "bg-amber-50",
    description: "Ambiguous and temporal queries",
    queries: [
      "What's happening with the dental practice?",
      "Tell me about the home care company",
      "What changed recently?",
      "What do we NOT know that we should?",
    ],
  },
  {
    name: "Data Exploration",
    icon: <Compass className="w-4 h-4" />,
    color: "text-cyan-600",
    bgColor: "bg-cyan-50",
    description: "Pipeline and aggregate queries",
    queries: [
      "What industries are represented in our accounts?",
      "How many accounts do we have in each stage?",
      "What carriers have provided quotes?",
      "Which accounts have phone call transcripts?",
      "What are the quote amounts we've received?",
    ],
  },
];

function CategoryCard({ 
  category, 
  isExpanded, 
  onToggle, 
  onSelectQuery,
  isRunning,
}: { 
  category: QueryCategory;
  isExpanded: boolean;
  onToggle: () => void;
  onSelectQuery: (query: string) => void;
  isRunning: boolean;
}) {
  return (
    <div className="query-category overflow-hidden">
      {/* Header */}
      <button
        onClick={onToggle}
        className="w-full p-4 flex items-center gap-3 text-left hover:bg-slate-50 transition-colors"
      >
        <div className={`p-2 rounded-lg ${category.bgColor} ${category.color}`}>
          {category.icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-medium text-slate-800 flex items-center gap-2">
            {category.name}
            <span className="text-xs text-slate-400 font-normal">
              ({category.queries.length})
            </span>
          </div>
          <div className="text-xs text-slate-500 truncate">
            {category.description}
          </div>
        </div>
        <motion.div
          animate={{ rotate: isExpanded ? 90 : 0 }}
          transition={{ duration: 0.2 }}
          className="text-slate-400"
        >
          <ChevronRight className="w-5 h-5" />
        </motion.div>
      </button>

      {/* Query list */}
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="border-t border-slate-100"
          >
            <div className="p-2 space-y-1">
              {category.queries.map((query, idx) => (
                <button
                  key={idx}
                  onClick={() => !isRunning && onSelectQuery(query)}
                  disabled={isRunning}
                  className={`
                    w-full text-left px-3 py-2.5 rounded-lg text-sm
                    flex items-center gap-2 group transition-all
                    ${isRunning 
                      ? 'opacity-50 cursor-not-allowed' 
                      : 'hover:bg-[#fdf0e9] hover:text-[#f97066]'
                    }
                    text-slate-600
                  `}
                >
                  <Play className={`
                    w-3 h-3 flex-shrink-0 opacity-0 group-hover:opacity-100 
                    transition-opacity text-[#f97066]
                    ${isRunning ? 'hidden' : ''}
                  `} />
                  <span className="line-clamp-2">{query}</span>
                </button>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function QuerySelector({ onSelectQuery, isRunning }: QuerySelectorProps) {
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(
    new Set([QUERY_CATEGORIES[0].name])
  );

  const toggleCategory = (name: string) => {
    setExpandedCategories(prev => {
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
  };

  const expandAll = () => {
    setExpandedCategories(new Set(QUERY_CATEGORIES.map(c => c.name)));
  };

  const collapseAll = () => {
    setExpandedCategories(new Set());
  };

  return (
    <div className="h-full flex flex-col overflow-hidden bg-white">
      {/* Header */}
      <div className="p-4 border-b border-slate-100 flex-shrink-0">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-[#f97066]" />
            Sample Queries
          </h2>
          <div className="flex gap-2">
            <button
              onClick={expandAll}
              className="text-xs text-slate-500 hover:text-[#f97066] transition-colors"
            >
              Expand all
            </button>
            <span className="text-slate-300">|</span>
            <button
              onClick={collapseAll}
              className="text-xs text-slate-500 hover:text-[#f97066] transition-colors"
            >
              Collapse
            </button>
          </div>
        </div>
        <p className="text-xs text-slate-500">
          Click any query to explore
        </p>
      </div>

      {/* Categories */}
      <div className="flex-1 overflow-auto p-3 space-y-2">
        {QUERY_CATEGORIES.map((category) => (
          <CategoryCard
            key={category.name}
            category={category}
            isExpanded={expandedCategories.has(category.name)}
            onToggle={() => toggleCategory(category.name)}
            onSelectQuery={onSelectQuery}
            isRunning={isRunning}
          />
        ))}
      </div>
    </div>
  );
}
