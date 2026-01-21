import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Folder, 
  FolderOpen, 
  FileText, 
  ChevronRight,
  Loader2,
} from 'lucide-react';
import type { TreeNode, NodeState } from '../types/exploration';

interface FileTreeProps {
  filesOpened: string[];
  filesListed: string[];
  currentPath?: string;
  onFileClick: (path: string) => void;
}

interface TreeNodeProps {
  node: TreeNode;
  depth: number;
  filesOpened: string[];
  filesListed: string[];
  currentPath?: string;
  onFileClick: (path: string) => void;
  expandedPaths: Set<string>;
  onToggle: (path: string) => void;
}

function getNodeState(
  path: string,
  filesOpened: string[],
  filesListed: string[],
  currentPath?: string
): NodeState {
  if (currentPath === path) return 'exploring';
  if (filesOpened.includes(path)) return 'read';
  if (filesListed.some(f => path.startsWith(f) || f.startsWith(path))) return 'listed';
  return 'unexplored';
}

function TreeNodeComponent({
  node,
  depth,
  filesOpened,
  filesListed,
  currentPath,
  onFileClick,
  expandedPaths,
  onToggle,
}: TreeNodeProps) {
  const isExpanded = expandedPaths.has(node.path);
  const isDirectory = node.type === 'directory';
  const hasChildren = isDirectory && node.children && node.children.length > 0;
  
  const state = getNodeState(node.path, filesOpened, filesListed, currentPath);
  
  const stateStyles: Record<NodeState, { text: string; bg: string }> = {
    unexplored: { text: 'text-slate-500', bg: '' },
    exploring: { text: 'text-[#f97066]', bg: 'bg-[#fdf0e9]' },
    listed: { text: 'text-amber-600', bg: 'bg-amber-50' },
    read: { text: 'text-emerald-600', bg: 'bg-emerald-50' },
    error: { text: 'text-red-600', bg: 'bg-red-50' },
  };

  const styles = stateStyles[state];

  const handleClick = () => {
    if (isDirectory) {
      onToggle(node.path);
    } else {
      onFileClick(node.path);
    }
  };

  return (
    <div>
      <motion.div
        initial={{ opacity: 0, x: -10 }}
        animate={{ opacity: 1, x: 0 }}
        className={`
          flex items-center gap-1.5 py-1.5 px-2 rounded-lg cursor-pointer
          hover:bg-slate-50 transition-all group
          ${styles.text} ${styles.bg}
          ${state === 'exploring' ? 'ring-1 ring-[#f97066]/30' : ''}
        `}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={handleClick}
      >
        {isDirectory && hasChildren && (
          <motion.span 
            className="w-4 h-4 flex items-center justify-center"
            animate={{ rotate: isExpanded ? 90 : 0 }}
            transition={{ duration: 0.15 }}
          >
            <ChevronRight className="w-3 h-3" />
          </motion.span>
        )}
        {isDirectory && !hasChildren && <span className="w-4" />}
        
        {isDirectory ? (
          isExpanded ? (
            <FolderOpen className="w-4 h-4 flex-shrink-0" />
          ) : (
            <Folder className="w-4 h-4 flex-shrink-0" />
          )
        ) : (
          <FileText className="w-4 h-4 flex-shrink-0" />
        )}
        
        <span className="text-sm truncate flex-1">{node.name}</span>
        
        {state === 'read' && (
          <motion.span
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            className="w-2 h-2 rounded-full bg-emerald-500"
          />
        )}
        {state === 'exploring' && (
          <motion.span
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            className="w-2 h-2 rounded-full bg-[#f97066] animate-pulse"
          />
        )}
      </motion.div>
      
      <AnimatePresence>
        {isExpanded && hasChildren && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            {node.children!.map((child) => (
              <TreeNodeComponent
                key={child.path}
                node={child}
                depth={depth + 1}
                filesOpened={filesOpened}
                filesListed={filesListed}
                currentPath={currentPath}
                onFileClick={onFileClick}
                expandedPaths={expandedPaths}
                onToggle={onToggle}
              />
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function FileTree({ 
  filesOpened, 
  filesListed, 
  currentPath, 
  onFileClick 
}: FileTreeProps) {
  const [tree, setTree] = useState<TreeNode | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set(['mem']));

  // Auto-expand paths that have been accessed
  useEffect(() => {
    const pathsToExpand = new Set(expandedPaths);
    
    [...filesOpened, ...filesListed].forEach(path => {
      // Expand all parent directories
      const parts = path.split('/');
      let current = '';
      for (const part of parts.slice(0, -1)) {
        current = current ? `${current}/${part}` : part;
        pathsToExpand.add(current);
      }
    });
    
    if (pathsToExpand.size !== expandedPaths.size) {
      setExpandedPaths(pathsToExpand);
    }
  }, [filesOpened, filesListed]);

  useEffect(() => {
    async function fetchTree() {
      try {
        const response = await fetch('/api/tree?max_depth=5');
        if (!response.ok) throw new Error('Failed to fetch tree');
        const data = await response.json();
        setTree(data.tree);
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setLoading(false);
      }
    }

    fetchTree();
  }, []);

  const handleToggle = (path: string) => {
    setExpandedPaths(prev => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400">
        <Loader2 className="w-6 h-6 animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 text-red-600 text-sm">
        Error loading tree: {error}
      </div>
    );
  }

  if (!tree) {
    return (
      <div className="p-4 text-slate-500 text-sm">
        No files found
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto p-3 bg-white">
      {/* Legend */}
      <div className="mb-4 px-2 flex flex-wrap gap-3 text-xs">
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-emerald-500" />
          <span className="text-slate-500">Read</span>
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-amber-500" />
          <span className="text-slate-500">Listed</span>
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-[#f97066] animate-pulse" />
          <span className="text-slate-500">Exploring</span>
        </span>
      </div>
      
      <TreeNodeComponent
        node={tree}
        depth={0}
        filesOpened={filesOpened}
        filesListed={filesListed}
        currentPath={currentPath}
        onFileClick={onFileClick}
        expandedPaths={expandedPaths}
        onToggle={handleToggle}
      />
    </div>
  );
}
