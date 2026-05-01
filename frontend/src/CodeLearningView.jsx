import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Light as SyntaxHighlighter } from 'react-syntax-highlighter';
import { docco } from 'react-syntax-highlighter/dist/esm/styles/hljs';
import { dark } from 'react-syntax-highlighter/dist/esm/styles/hljs';
import { Lightbulb, RefreshCw, FileCode, ChevronRight, FolderOpen, Loader2, Home, Clock, Search, X, ArrowRight } from 'lucide-react';
import ReactMarkdown from 'react-markdown';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

// Language display names and colors
const LANG_META = {
  python: { label: 'Python', color: 'bg-blue-100 text-blue-700' },
  javascript: { label: 'JavaScript', color: 'bg-yellow-100 text-yellow-700' },
  typescript: { label: 'TypeScript', color: 'bg-indigo-100 text-indigo-700' },
  go: { label: 'Go', color: 'bg-cyan-100 text-cyan-700' },
  java: { label: 'Java', color: 'bg-orange-100 text-orange-700' },
  rust: { label: 'Rust', color: 'bg-purple-100 text-purple-700' },
};

function getLangBadge(language) {
  const meta = LANG_META[language] || { label: language, color: 'bg-gray-100 text-gray-600' };
  return (
    <span className={`inline-block text-xs px-2 py-0.5 rounded-full font-medium ${meta.color}`}>
      {meta.label}
    </span>
  );
}

const CodeLearningView = () => {
  // Project state
  const [projects, setProjects] = useState([]);
  const [selectedProjectId, setSelectedProjectId] = useState(null);
  const [project, setProject] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedFile, setSelectedFile] = useState(null);
  const [selectedFunc, setSelectedFunc] = useState(null);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [error, setError] = useState(null);
  const [viewMode, setViewMode] = useState('functions');
  const [overview, setOverview] = useState(null);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [analysisProgress, setAnalysisProgress] = useState(null);
  const [pollingInterval, setPollingInterval] = useState(null);
  const [analysisMode, setAnalysisMode] = useState('ai');
  const [isSwitchingMode, setIsSwitchingMode] = useState(false);

  // Project creation state
  const [repoUrl, setRepoUrl] = useState('');
  const [projectName, setProjectName] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState(null);
  const [creatingTaskId, setCreatingTaskId] = useState(null);
  const [newAnalysisMode, setNewAnalysisMode] = useState('ai');

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showSearchResults, setShowSearchResults] = useState(false);
  const [searchFilterLang, setSearchFilterLang] = useState('');
  const searchInputRef = useRef(null);

  // Load projects list
  useEffect(() => {
    const loadProjects = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/projects`);
        if (!res.ok) throw new Error('Failed to load projects');
        const data = await res.json();
        setProjects(data);
        if (data.length > 0) {
          setSelectedProjectId(data[0].id);
        } else {
          setLoading(false);
        }
      } catch (err) {
        setError(err.message);
        setLoading(false);
      }
    };
    loadProjects();
  }, []);

  // Load project file tree
  const loadProject = async (projectId) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/files`);
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      const data = await response.json();
      setProject(data);
      if (data.analysis_mode) setAnalysisMode(data.analysis_mode);

      if (data.files && data.files.length > 0) {
        const firstFile = data.files[0];
        setSelectedFile(firstFile);
        if (firstFile.functions && firstFile.functions.length > 0) {
          setSelectedFunc(firstFile.functions[0]);
        }
      }

      if (data.analysis_status === 'running' || data.analysis_status === 'pending') {
        startProgressPolling(projectId);
      } else {
        stopProgressPolling();
        setAnalysisProgress(null);
      }
    } catch (err) {
      console.error('Failed to load project:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (selectedProjectId) {
      loadProject(selectedProjectId);
    }
  }, [selectedProjectId]);

  const startProgressPolling = (projectId) => {
    if (pollingInterval) clearInterval(pollingInterval);
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/projects/${projectId}/progress`);
        if (!res.ok) throw new Error('Progress fetch failed');
        const data = await res.json();
        setAnalysisProgress(data);

        if (data.status === 'completed' || data.status === 'failed') {
          stopProgressPolling();
          if (data.status === 'completed') {
            const refreshRes = await fetch(`${API_BASE_URL}/api/projects/${projectId}/files`);
            if (refreshRes.ok) {
              const newData = await refreshRes.json();
              setProject(newData);
              if (selectedFile) {
                const updatedFile = newData.files.find(f => f.id === selectedFile.id);
                if (updatedFile) setSelectedFile(updatedFile);
              }
            }
          }
        }
      } catch (err) {
        console.error('Progress polling error', err);
      }
    }, 2000);
    setPollingInterval(interval);
  };

  const stopProgressPolling = () => {
    if (pollingInterval) {
      clearInterval(pollingInterval);
      setPollingInterval(null);
    }
  };

  const pollTaskStatus = (taskId) => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/analyze/${taskId}/status`);
        if (!res.ok) throw new Error('Status query failed');
        const data = await res.json();
        if (data.status === 'completed') {
          clearInterval(interval);
          setIsCreating(false);
          setCreatingTaskId(null);
          setRepoUrl('');
          setProjectName('');
          const projectsRes = await fetch(`${API_BASE_URL}/api/projects`);
          if (projectsRes.ok) {
            const newProjects = await projectsRes.json();
            setProjects(newProjects);
            if (newProjects.length > 0) {
              setSelectedProjectId(newProjects[0].id);
            }
          }
        } else if (data.status === 'failed') {
          clearInterval(interval);
          setIsCreating(false);
          setCreatingTaskId(null);
          setCreateError(data.error_message || 'Analysis failed');
        }
      } catch (err) {
        console.error('Polling error', err);
      }
    }, 2000);
  };

  const handleCreateProject = async (e) => {
    e.preventDefault();
    if (!repoUrl.trim()) return;
    setIsCreating(true);
    setCreateError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/api/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repo_url: repoUrl,
          name: projectName.trim() || undefined,
          mode: newAnalysisMode
        })
      });
      if (!res.ok) throw new Error('Create task failed');
      const data = await res.json();
      setCreatingTaskId(data.task_id);
      pollTaskStatus(data.task_id);
    } catch (err) {
      setCreateError(err.message);
      setIsCreating(false);
    }
  };

  // Load overview
  useEffect(() => {
    if (viewMode === 'overview' && selectedProjectId) {
      setOverviewLoading(true);
      fetch(`${API_BASE_URL}/api/projects/${selectedProjectId}/overview`)
        .then(res => res.json())
        .then(data => setOverview(data.overview))
        .catch(err => console.error(err))
        .finally(() => setOverviewLoading(false));
    }
  }, [viewMode, selectedProjectId]);

  // Search handler
  const handleSearch = useCallback(async (query) => {
    const q = (query || searchQuery).trim();
    if (!q) return;
    setIsSearching(true);
    setShowSearchResults(true);
    try {
      let url = `${API_BASE_URL}/api/search?q=${encodeURIComponent(q)}&limit=30`;
      if (searchFilterLang) url += `&language=${searchFilterLang}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error('Search failed');
      const data = await res.json();
      setSearchResults(data.results || []);
    } catch (err) {
      console.error('Search error:', err);
      setSearchResults([]);
    } finally {
      setIsSearching(false);
    }
  }, [searchQuery, searchFilterLang]);

  const handleSearchKeyDown = (e) => {
    if (e.key === 'Enter') {
      handleSearch();
    } else if (e.key === 'Escape') {
      setShowSearchResults(false);
      setSearchQuery('');
      setSearchResults([]);
    }
  };

  const handleSelectSearchResult = (func) => {
    setShowSearchResults(false);
    setSearchQuery('');
    setViewMode('functions');
    // Navigate to the function's project
    if (func.project_id !== selectedProjectId) {
      setSelectedProjectId(func.project_id);
    }
    // We need to find the file and function in the loaded project
    // For now, navigate by setting selected function directly
    setSelectedFunc(func);
    setSelectedFile({ id: func.file_id, path: func.file_path, functions: [] });
  };

  const handleSelectFile = (file) => {
    setSelectedFile(file);
    setViewMode('functions');
    if (file.functions && file.functions.length > 0) {
      setSelectedFunc(file.functions[0]);
    } else {
      setSelectedFunc(null);
    }
  };

  const handleModeChange = async (newMode) => {
    if (!selectedProjectId || newMode === analysisMode) return;
    setIsSwitchingMode(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/projects/${selectedProjectId}/mode?mode=${newMode}`, {
        method: 'PUT',
      });
      if (!res.ok) throw new Error('Mode switch failed');
      const data = await res.json();
      setAnalysisMode(newMode);
      // Reload project to get mode-specific content
      await loadProject(selectedProjectId);
    } catch (err) {
      console.error('Mode switch error:', err);
      setError(err.message);
    } finally {
      setIsSwitchingMode(false);
    }
  };

  const handleRegenerate = async () => {
    if (!selectedFunc) return;
    setIsRegenerating(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/functions/${selectedFunc.id}/regenerate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      const updatedFunc = await response.json();
      setSelectedFunc(prev => ({
        ...prev,
        explanation_simple: updatedFunc.explanation_simple,
        explanation_logic: updatedFunc.explanation_logic,
      }));
      if (project && selectedFile) {
        const updatedFiles = project.files.map(file => {
          if (file.id === selectedFile.id) {
            return {
              ...file,
              functions: file.functions.map(fn =>
                fn.id === selectedFunc.id ? { ...fn, ...updatedFunc } : fn
              ),
            };
          }
          return file;
        });
        setProject({ ...project, files: updatedFiles });
      }
    } catch (err) {
      console.error('Regenerate failed:', err);
      setError(err.message);
    } finally {
      setIsRegenerating(false);
    }
  };

  // Render: File tree in sidebar
  const renderFileTree = () => {
    if (!project) return null;
    return (
      <div className="space-y-1">
        <div
          className={`flex items-center px-2 py-2 rounded-md cursor-pointer transition-colors ${
            viewMode === 'overview'
              ? 'bg-blue-100 text-blue-700'
              : 'hover:bg-gray-100 text-gray-700'
          }`}
          onClick={() => setViewMode('overview')}
        >
          <Home size={18} className="mr-2" />
          <span className="font-medium">Project Overview</span>
        </div>
        <div className="border-t border-gray-200 my-1" />
        {project.files.map(file => (
          <div key={file.id}>
            <div
              className={`flex items-center px-2 py-1.5 text-sm rounded-md cursor-pointer transition-colors ${
                viewMode === 'functions' && selectedFile?.id === file.id
                  ? 'bg-blue-100 text-blue-700'
                  : 'hover:bg-gray-100 text-gray-700'
              }`}
              onClick={() => handleSelectFile(file)}
            >
              <ChevronRight size={16} className="mr-1 text-gray-400" />
              <FileCode size={16} className="mr-2 flex-shrink-0" />
              <span className="truncate text-xs">{file.path}</span>
            </div>
            {viewMode === 'functions' && selectedFile?.id === file.id && file.functions && (
              <div className="ml-6 space-y-0.5 mt-0.5">
                {file.functions.map(func => (
                  <div
                    key={func.id}
                    className={`flex items-center px-2 py-1 text-sm rounded-md cursor-pointer transition-colors ${
                      selectedFunc?.id === func.id
                        ? 'bg-blue-50 text-blue-600 border-l-2 border-blue-500'
                        : 'hover:bg-gray-50 text-gray-600'
                    }`}
                    onClick={() => setSelectedFunc(func)}
                  >
                    <span className="font-mono text-xs">def </span>
                    <span className="ml-1 font-medium text-xs">{func.name}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    );
  };

  // Render: Search results panel
  const renderSearchResults = () => {
    return (
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="bg-white border-b border-gray-200 px-6 py-3 flex items-center shadow-sm">
          <Search size={18} className="text-blue-500 mr-2" />
          <span className="text-sm font-medium text-gray-700">
            Search results for "{searchQuery}"
          </span>
          <span className="ml-2 text-xs text-gray-400">({searchResults.length} results)</span>
          <button
            onClick={() => { setShowSearchResults(false); setSearchResults([]); }}
            className="ml-auto text-gray-400 hover:text-gray-600"
          >
            <X size={18} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {isSearching ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 size={24} className="animate-spin text-blue-500" />
              <span className="ml-2 text-gray-500">Searching...</span>
            </div>
          ) : searchResults.length === 0 ? (
            <div className="text-center py-20 text-gray-400">
              <Search size={40} className="mx-auto mb-3 opacity-50" />
              <p>No results found for "{searchQuery}"</p>
              <p className="text-sm mt-1">Try different keywords or browse projects directly</p>
            </div>
          ) : (
            searchResults.map((r, i) => (
              <div
                key={r.id || i}
                className="bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md hover:border-blue-200 transition-all cursor-pointer"
                onClick={() => handleSelectSearchResult(r)}
              >
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center space-x-2 min-w-0">
                    <span className="font-mono font-semibold text-sm text-blue-700 truncate">
                      {r.name}
                    </span>
                    {r.language && getLangBadge(r.language)}
                    <span className="text-xs text-gray-400">
                      {r.score > 0 ? `(${(r.score * 100).toFixed(0)}%)` : ''}
                    </span>
                  </div>
                  <ArrowRight size={14} className="text-gray-300 flex-shrink-0" />
                </div>
                <div className="text-xs text-gray-500 mb-2">
                  <span className="font-mono">{r.file_path}</span>
                  <span className="mx-1">·</span>
                  <span>{r.project_name}</span>
                  {r.signature && (
                    <>
                      <span className="mx-1">·</span>
                      <span className="font-mono">{r.signature}</span>
                    </>
                  )}
                </div>
                {r.explanation_simple && (
                  <p className="text-sm text-gray-600 line-clamp-2">
                    {r.explanation_simple}
                  </p>
                )}
                {r.code_snippet && (
                  <div className="mt-2 bg-gray-50 rounded p-2 overflow-hidden max-h-20">
                    <pre className="text-xs text-gray-500 truncate-multiline">
                      {r.code_snippet.split('\n').slice(0, 3).join('\n')}
                    </pre>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    );
  };

  // Render: Progress bar
  const renderProgressBar = () => {
    if (!analysisProgress || analysisProgress.status !== 'running') return null;
    const percent = analysisProgress.progress || 0;
    const step = analysisProgress.current_step || 'Analyzing...';
    return (
      <div className="bg-white border-b border-gray-200 px-4 py-2 shadow-sm">
        <div className="flex items-center text-sm text-gray-600 mb-1">
          <Clock size={14} className="mr-1" />
          <span className="truncate">{step}</span>
          <span className="ml-auto font-mono">{percent}%</span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-2">
          <div
            className="bg-blue-500 h-2 rounded-full transition-all duration-300"
            style={{ width: `${percent}%` }}
          />
        </div>
      </div>
    );
  };

  // Loading state
  if (error) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="text-center text-red-600 p-6 bg-white rounded-lg shadow-md">
          <p className="text-lg font-semibold">Load Failed</p>
          <p className="text-sm">{error}</p>
          <button
            onClick={() => window.location.reload()}
            className="mt-4 px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (loading && projects.length === 0 && !isCreating) {
    return (
      <div className="flex h-screen bg-gray-50">
        <div className="w-80 bg-white border-r border-gray-200 p-4 space-y-3">
          <div className="h-6 bg-gray-200 rounded animate-pulse w-1/2" />
          <div className="h-10 bg-gray-100 rounded animate-pulse" />
          <div className="h-10 bg-gray-100 rounded animate-pulse" />
        </div>
        <div className="flex-1 p-6 space-y-4">
          <div className="h-8 bg-gray-200 rounded animate-pulse w-3/4" />
          <div className="flex h-96 space-x-4">
            <div className="w-1/2 bg-gray-100 rounded animate-pulse" />
            <div className="w-1/2 bg-gray-100 rounded animate-pulse" />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-gray-50 font-sans text-gray-800">
      {/* Left sidebar */}
      <aside className="w-80 bg-white border-r border-gray-200 flex flex-col shadow-sm">
        {/* Search bar */}
        <div className="p-3 border-b border-gray-200">
          <div className="relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              ref={searchInputRef}
              type="text"
              placeholder="Search all code... (e.g. rate limit)"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={handleSearchKeyDown}
              className="w-full pl-9 pr-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent"
            />
            {searchQuery && (
              <button
                onClick={() => { setSearchQuery(''); setSearchResults([]); }}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-300 hover:text-gray-500"
              >
                <X size={14} />
              </button>
            )}
          </div>
          <div className="flex items-center mt-2 space-x-2">
            <button
              onClick={() => handleSearch()}
              disabled={isSearching || !searchQuery.trim()}
              className="flex-1 text-xs bg-blue-500 text-white py-1.5 rounded-md hover:bg-blue-600 disabled:opacity-50 transition-colors"
            >
              {isSearching ? 'Searching...' : 'Search'}
            </button>
            <select
              value={searchFilterLang}
              onChange={(e) => setSearchFilterLang(e.target.value)}
              className="text-xs border rounded px-2 py-1.5 bg-white text-gray-600"
            >
              <option value="">All langs</option>
              <option value="python">Python</option>
              <option value="javascript">JavaScript</option>
              <option value="typescript">TypeScript</option>
              <option value="go">Go</option>
              <option value="java">Java</option>
              <option value="rust">Rust</option>
            </select>
          </div>
        </div>

        {/* Project selector */}
        <div className="p-3 border-b border-gray-200">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm font-semibold text-blue-600 flex items-center">
              <FolderOpen size={16} className="mr-1.5" />
              Projects
            </h2>
            {projects.length > 0 && (
              <select
                value={selectedProjectId || ''}
                onChange={(e) => setSelectedProjectId(Number(e.target.value))}
                className="text-xs border rounded px-1.5 py-1 bg-white max-w-[140px]"
              >
                {projects.map(p => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            )}
          </div>
          {projects.length > 0 && selectedProjectId && (
            <div className="flex items-center space-x-1 mt-1">
              <span className="text-xs text-gray-400">Mode:</span>
              <select
                value={analysisMode}
                onChange={(e) => handleModeChange(e.target.value)}
                disabled={isSwitchingMode}
                className="text-xs border rounded px-1 py-0.5 bg-white flex-1"
              >
                <option value="ai">AI</option>
                <option value="beginner">Beginner</option>
                <option value="expert">Expert</option>
              </select>
              {isSwitchingMode && <Loader2 size={12} className="animate-spin text-blue-500" />}
            </div>
          )}
        </div>

        {/* New task form */}
        <div className="p-3 border-b border-gray-200 bg-gray-50">
          <h3 className="text-xs font-semibold mb-1.5 text-gray-500 uppercase tracking-wider">
            New Analysis
          </h3>
          <form onSubmit={handleCreateProject}>
            <input
              type="text"
              placeholder="GitHub URL (https://github.com/...)"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              className="w-full p-1.5 text-xs border rounded mb-1.5"
              required
              disabled={isCreating}
            />
            <input
              type="text"
              placeholder="Project name (optional)"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              className="w-full p-1.5 text-xs border rounded mb-1.5"
              disabled={isCreating}
            />
            <select
              value={newAnalysisMode}
              onChange={(e) => setNewAnalysisMode(e.target.value)}
              className="w-full p-1.5 text-xs border rounded mb-1.5 bg-white"
              disabled={isCreating}
            >
              <option value="ai">AI Mode (default)</option>
              <option value="beginner">Beginner Mode</option>
              <option value="expert">Expert Mode</option>
            </select>
            <button
              type="submit"
              disabled={isCreating || !repoUrl.trim()}
              className="w-full bg-blue-500 text-white p-1.5 rounded text-xs hover:bg-blue-600 disabled:opacity-50 transition-colors"
            >
              {isCreating ? 'Analyzing...' : 'Start Analysis'}
            </button>
            {createError && <p className="text-red-500 text-xs mt-1">{createError}</p>}
            {isCreating && creatingTaskId && (
              <p className="text-gray-400 text-xs mt-1">Task: {creatingTaskId.slice(0, 8)}...</p>
            )}
          </form>
        </div>

        {/* File tree */}
        <div className="flex-1 overflow-y-auto p-2">
          {project ? renderFileTree() : (
            <div className="text-center text-gray-400 py-8 text-sm">
              {projects.length === 0 ? 'No projects yet. Add one above.' : 'Select a project'}
            </div>
          )}
        </div>
      </aside>

      {/* Main content area */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {renderProgressBar()}

        {/* Search results view */}
        {showSearchResults ? (
          renderSearchResults()
        ) : viewMode === 'overview' ? (
          /* Overview view */
          <div className="flex-1 overflow-y-auto p-6">
            <div className="bg-white rounded-2xl shadow-xl p-6 max-w-4xl mx-auto">
              <h1 className="text-2xl font-bold mb-4 flex items-center">
                <Home size={24} className="mr-2 text-blue-500" />
                Project Overview
              </h1>
              {overviewLoading ? (
                <div className="animate-pulse space-y-2">
                  <div className="h-4 bg-gray-200 rounded w-3/4" />
                  <div className="h-4 bg-gray-200 rounded w-full" />
                  <div className="h-4 bg-gray-200 rounded w-5/6" />
                </div>
              ) : (
                <ReactMarkdown className="prose max-w-none">
                  {overview || 'No overview yet. Please wait for analysis to complete.'}
                </ReactMarkdown>
              )}
            </div>
          </div>
        ) : (
          /* Code + Explanation split view */
          <>
            {selectedFile && (
              <div className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between shadow-sm">
                <div className="flex items-center space-x-3 min-w-0">
                  <FileCode size={18} className="text-blue-500 flex-shrink-0" />
                  <span className="text-sm font-mono text-gray-600 truncate">{selectedFile.path}</span>
                </div>
                <div className="flex items-center space-x-2 text-xs text-gray-500 flex-shrink-0">
                  <span>Functions: {selectedFile.functions?.length || 0}</span>
                </div>
              </div>
            )}
            <div className="flex-1 flex overflow-hidden">
              {/* Code panel */}
              <div className="w-1/2 overflow-y-auto border-r border-gray-200 bg-white">
                <div className="sticky top-0 bg-gray-50 px-4 py-2 text-xs font-mono text-gray-500 border-b z-10 flex items-center justify-between">
                  <span>Source Code</span>
                  {selectedFunc?.language && getLangBadge(selectedFunc.language)}
                </div>
                {selectedFunc ? (
                  <SyntaxHighlighter
                    language={selectedFunc.language === 'typescript' ? 'typescript' : selectedFunc.language === 'javascript' || !selectedFunc.language ? 'javascript' : selectedFunc.language}
                    style={docco}
                    customStyle={{ margin: 0, padding: '1rem', background: '#fff', fontSize: '0.8rem' }}
                    showLineNumbers
                  >
                    {selectedFunc.code_snippet}
                  </SyntaxHighlighter>
                ) : (
                  <div className="p-6 text-center text-gray-400 text-sm">Select a function from the left panel</div>
                )}
              </div>
              {/* Explanation panel - mode-aware */}
              <div className="w-1/2 overflow-y-auto bg-gradient-to-br from-blue-50 to-indigo-50 p-6">
                {selectedFunc ? (
                  <div className="bg-white rounded-2xl shadow-xl border border-blue-100 overflow-hidden transition-all hover:shadow-2xl">
                    <div className="bg-gradient-to-r from-blue-500 to-indigo-600 px-6 py-4 flex items-center justify-between">
                      <div className="flex items-center text-white">
                        <Lightbulb size={22} className="mr-2" />
                        <h2 className="text-lg font-bold">
                          {analysisMode === 'ai' ? 'AI Data' : analysisMode === 'expert' ? 'Expert Analysis' : 'AI Tutor'}
                        </h2>
                      </div>
                      <span className="bg-white/20 px-3 py-1 rounded-full text-sm font-mono">
                        {selectedFunc.name}()
                      </span>
                    </div>
                    <div className="p-6 space-y-5">

                      {/* === AI MODE === */}
                      {analysisMode === 'ai' && (
                        <>
                          <div>
                            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Purpose</h3>
                            <div className="text-gray-800 bg-gray-50 p-3 rounded-lg text-sm font-mono">
                              {isRegenerating ? (
                                <span className="flex items-center text-blue-500"><Loader2 size={14} className="animate-spin mr-2" />Regenerating...</span>
                              ) : (
                                selectedFunc.ai_purpose || 'No AI purpose yet'
                              )}
                            </div>
                          </div>
                          {selectedFunc.ai_inputs && selectedFunc.ai_inputs.length > 0 && (
                            <div>
                              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Inputs</h3>
                              <div className="space-y-1">
                                {(typeof selectedFunc.ai_inputs === 'string' ? JSON.parse(selectedFunc.ai_inputs) : selectedFunc.ai_inputs).map((inp, i) => (
                                  <div key={i} className="bg-gray-50 p-2 rounded text-xs font-mono">
                                    <span className="text-blue-600">{inp.name}</span>
                                    <span className="text-gray-400 mx-1">:</span>
                                    <span className="text-purple-600">{inp.type}</span>
                                    <span className="text-gray-400 ml-2">{inp.description}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                          {selectedFunc.ai_outputs && (
                            <div>
                              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Outputs</h3>
                              <div className="bg-gray-50 p-2 rounded text-xs font-mono">
                                <span className="text-green-600">{(typeof selectedFunc.ai_outputs === 'string' ? JSON.parse(selectedFunc.ai_outputs) : selectedFunc.ai_outputs).type}</span>
                                <span className="text-gray-400 ml-2">{(typeof selectedFunc.ai_outputs === 'string' ? JSON.parse(selectedFunc.ai_outputs) : selectedFunc.ai_outputs).description}</span>
                              </div>
                            </div>
                          )}
                          {selectedFunc.ai_side_effects && ((typeof selectedFunc.ai_side_effects === 'string' ? JSON.parse(selectedFunc.ai_side_effects) : selectedFunc.ai_side_effects)).length > 0 && (
                            <div>
                              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Side Effects</h3>
                              <ul className="list-disc list-inside space-y-0.5">
                                {(typeof selectedFunc.ai_side_effects === 'string' ? JSON.parse(selectedFunc.ai_side_effects) : selectedFunc.ai_side_effects).map((se, i) => (
                                  <li key={i} className="text-xs text-gray-600">{se}</li>
                                ))}
                              </ul>
                            </div>
                          )}
                        </>
                      )}

                      {/* === BEGINNER MODE === */}
                      {analysisMode === 'beginner' && (
                        <>
                          <div>
                            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
                              In Plain English
                            </h3>
                            <div className="text-lg text-gray-800 leading-relaxed font-medium bg-blue-50/50 p-4 rounded-lg border-l-4 border-blue-400">
                              {isRegenerating ? (
                                <span className="flex items-center text-blue-500">
                                  <Loader2 size={18} className="animate-spin mr-2" />
                                  AI is rethinking...
                                </span>
                              ) : (
                                selectedFunc.explanation_simple || 'No explanation yet'
                              )}
                            </div>
                          </div>
                          <div>
                            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
                              Step-by-Step
                            </h3>
                            <div className="prose prose-blue max-w-none text-gray-600 bg-gray-50 p-4 rounded-lg text-sm">
                              {isRegenerating ? (
                                <div className="space-y-2 animate-pulse">
                                  <div className="h-3 bg-gray-200 rounded w-3/4" />
                                  <div className="h-3 bg-gray-200 rounded w-full" />
                                  <div className="h-3 bg-gray-200 rounded w-5/6" />
                                </div>
                              ) : (
                                <ReactMarkdown>{selectedFunc.explanation_logic || 'No step-by-step yet'}</ReactMarkdown>
                              )}
                            </div>
                          </div>
                        </>
                      )}

                      {/* === EXPERT MODE === */}
                      {analysisMode === 'expert' && (
                        <>
                          <div>
                            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Purpose</h3>
                            <div className="text-gray-800 bg-gray-50 p-3 rounded-lg text-sm font-mono">
                              {isRegenerating ? (
                                <span className="flex items-center text-blue-500"><Loader2 size={14} className="animate-spin mr-2" />Regenerating...</span>
                              ) : (
                                selectedFunc.expert_purpose || selectedFunc.ai_purpose || 'No expert analysis yet'
                              )}
                            </div>
                          </div>
                          {(selectedFunc.expert_tech_details || selectedFunc.ai_purpose) && (
                            <div>
                              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Tech Details</h3>
                              <div className="text-gray-700 bg-gray-50 p-3 rounded-lg text-sm">
                                {selectedFunc.expert_tech_details || 'Analysis pending mode switch'}
                              </div>
                            </div>
                          )}
                          {selectedFunc.expert_error_handling && (
                            <div>
                              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Error Handling</h3>
                              <div className="text-gray-700 bg-red-50 p-3 rounded-lg text-sm">
                                {selectedFunc.expert_error_handling}
                              </div>
                            </div>
                          )}
                          {selectedFunc.expert_concurrency && (
                            <div>
                              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Concurrency</h3>
                              <div className="text-gray-700 bg-yellow-50 p-3 rounded-lg text-sm">
                                {selectedFunc.expert_concurrency}
                              </div>
                            </div>
                          )}
                          {selectedFunc.expert_tradeoffs && (
                            <div>
                              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Trade-offs</h3>
                              <div className="text-gray-700 bg-orange-50 p-3 rounded-lg text-sm">
                                {selectedFunc.expert_tradeoffs}
                              </div>
                            </div>
                          )}
                        </>
                      )}

                      {/* Regenerate button */}
                      <div className="flex justify-end pt-1">
                        <button
                          onClick={handleRegenerate}
                          disabled={isRegenerating}
                          className="inline-flex items-center px-4 py-2 bg-white border border-gray-300 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 hover:text-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          <RefreshCw
                            size={16}
                            className={`mr-2 ${isRegenerating ? 'animate-spin' : ''}`}
                          />
                          {analysisMode === 'ai' ? 'Regenerate AI Data' : analysisMode === 'expert' ? 'Reanalyze' : "Don't get it? Rephrase"}
                        </button>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-center justify-center h-full text-gray-400">
                    <div className="text-center">
                      <Lightbulb size={48} className="mx-auto mb-3 opacity-50" />
                      <p className="text-sm">Select a function to view analysis</p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
};

export default CodeLearningView;
