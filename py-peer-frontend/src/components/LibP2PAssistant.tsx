import { useEffect, useRef, useState, useCallback } from 'react'
import {
  SparklesIcon, XMarkIcon, PaperAirplaneIcon,
  ChevronDownIcon, ArrowUpTrayIcon, DocumentPlusIcon,
  CheckCircleIcon, ExclamationCircleIcon, TrashIcon,
  DocumentTextIcon,
} from '@heroicons/react/24/solid'
import Spinner from './Spinner'
import { BASE } from '../api/client'

interface Message {
  role: 'user' | 'assistant'
  content: string
  sources?: string[]
}

interface IngestResult {
  filename: string
  chunks_added: number
  doc_count: number
}

interface RAGFile {
  filename: string
  chunks: number
}

async function askQuestion(question: string): Promise<{ answer: string; sources: string[] }> {
  const res = await fetch(`${BASE}/rag/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
  const data = await res.json()
  if (!data.success) throw new Error(data.error ?? 'Unknown error')
  return { answer: data.answer, sources: data.sources ?? [] }
}

async function ingestFile(file: File): Promise<IngestResult> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE}/rag/ingest`, { method: 'POST', body: form })
  const data = await res.json()
  if (!data.success) throw new Error(data.error ?? 'Ingest failed')
  return { filename: data.filename, chunks_added: data.chunks_added, doc_count: data.doc_count }
}

async function fetchRAGFiles(): Promise<RAGFile[]> {
  const res = await fetch(`${BASE}/rag/files`)
  const data = await res.json()
  if (!data.success) throw new Error(data.error ?? 'Failed to load files')
  return data.files as RAGFile[]
}

async function deleteRAGFile(filename: string): Promise<number> {
  const res = await fetch(`${BASE}/rag/files`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename }),
  })
  const data = await res.json()
  if (!data.success) throw new Error(data.error ?? 'Delete failed')
  return data.chunks_deleted as number
}

// ── Upload Modal ─────────────────────────────────────────────────────────────

interface UploadModalProps {
  onClose: () => void
}

function UploadModal({ onClose }: UploadModalProps) {
  const [tab, setTab]             = useState<'upload' | 'files'>('upload')
  const [dragging, setDragging]   = useState(false)
  const [uploading, setUploading] = useState(false)
  const [result, setResult]       = useState<IngestResult | null>(null)
  const [uploadError, setUploadError] = useState('')

  const [files, setFiles]         = useState<RAGFile[]>([])
  const [filesLoading, setFilesLoading] = useState(false)
  const [filesError, setFilesError]     = useState('')
  const [deletingFile, setDeletingFile] = useState<string | null>(null)
  const [deleteMsg, setDeleteMsg]       = useState('')

  const fileRef = useRef<HTMLInputElement>(null)

  const loadFiles = useCallback(async () => {
    setFilesLoading(true)
    setFilesError('')
    try {
      setFiles(await fetchRAGFiles())
    } catch (e: unknown) {
      setFilesError(e instanceof Error ? e.message : 'Failed to load files')
    } finally {
      setFilesLoading(false)
    }
  }, [])

  // Load file list when switching to that tab
  useEffect(() => {
    if (tab === 'files') loadFiles()
  }, [tab, loadFiles])

  async function handleFiles(fileList: FileList | null) {
    if (!fileList || fileList.length === 0) return
    setUploading(true)
    setUploadError('')
    setResult(null)
    try {
      const r = await ingestFile(fileList[0])
      setResult(r)
    } catch (e: unknown) {
      setUploadError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  async function handleDelete(filename: string) {
    setDeletingFile(filename)
    setDeleteMsg('')
    setFilesError('')
    try {
      const deleted = await deleteRAGFile(filename)
      setDeleteMsg(`Removed "${filename}" (${deleted} chunks deleted)`)
      setFiles((prev) => prev.filter((f) => f.filename !== filename))
    } catch (e: unknown) {
      setFilesError(e instanceof Error ? e.message : 'Delete failed')
    } finally {
      setDeletingFile(null)
    }
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-80 sm:w-96 rounded-xl bg-white shadow-2xl border border-gray-200 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between bg-indigo-600 px-4 py-3">
          <div className="flex items-center gap-2">
            <DocumentPlusIcon className="h-4 w-4 text-white" />
            <span className="text-sm font-semibold text-white">RAG Knowledge Base</span>
          </div>
          <button onClick={onClose} className="text-white/80 hover:text-white">
            <XMarkIcon className="h-4 w-4" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-200 bg-gray-50">
          {(['upload', 'files'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`flex-1 py-2 text-xs font-medium transition
                ${tab === t
                  ? 'border-b-2 border-indigo-600 text-indigo-700 bg-white'
                  : 'text-gray-500 hover:text-gray-700'}`}
            >
              {t === 'upload' ? '⬆ Upload File' : '📂 Manage Files'}
            </button>
          ))}
        </div>

        {/* ── Upload tab ───────────────────────────────────────────── */}
        {tab === 'upload' && (
          <div className="p-4 space-y-4">
            <div
              onClick={() => !uploading && fileRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault()
                setDragging(false)
                handleFiles(e.dataTransfer.files)
              }}
              className={`flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 cursor-pointer transition
                ${dragging ? 'border-indigo-500 bg-indigo-50' : 'border-gray-300 hover:border-indigo-400 hover:bg-gray-50'}
                ${uploading ? 'opacity-60 cursor-not-allowed' : ''}`}
            >
              {uploading ? (
                <>
                  <Spinner className="h-6 w-6 text-indigo-500" />
                  <p className="text-xs text-gray-500">Embedding & storing…</p>
                </>
              ) : (
                <>
                  <ArrowUpTrayIcon className="h-7 w-7 text-indigo-400" />
                  <p className="text-xs font-medium text-gray-700">Click or drag a file here</p>
                  <p className="text-[10px] text-gray-400 text-center">
                    .pdf .txt .md .py .js .ts .json .yaml .rst .csv .html and more
                  </p>
                </>
              )}
            </div>
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              onChange={(e) => handleFiles(e.target.files)}
              accept=".pdf,.txt,.md,.py,.js,.ts,.tsx,.jsx,.json,.yaml,.yml,.rst,.csv,.html,.xml,.toml,.cfg,.ini,.sh,.go,.rs,.c,.cpp,.h,.java,.rb,.php,.swift,.kt"
            />

            {result && (
              <div className="flex items-start gap-2 rounded-lg bg-green-50 border border-green-200 px-3 py-2.5">
                <CheckCircleIcon className="h-4 w-4 text-green-500 flex-shrink-0 mt-0.5" />
                <div className="text-xs text-green-800 space-y-0.5">
                  <p className="font-medium">{result.filename} ingested</p>
                  <p className="text-green-600">{result.chunks_added} chunks added · {result.doc_count} total docs</p>
                </div>
              </div>
            )}

            {uploadError && (
              <div className="flex items-start gap-2 rounded-lg bg-red-50 border border-red-200 px-3 py-2.5">
                <ExclamationCircleIcon className="h-4 w-4 text-red-500 flex-shrink-0 mt-0.5" />
                <p className="text-xs text-red-700">{uploadError}</p>
              </div>
            )}

            <p className="text-[10px] text-gray-400 text-center">
              Files are chunked, embedded with nomic-embed-text, and stored locally in ChromaDB.
            </p>
          </div>
        )}

        {/* ── Files tab ────────────────────────────────────────────── */}
        {tab === 'files' && (
          <div className="p-4 space-y-3">
            {deleteMsg && (
              <div className="flex items-start gap-2 rounded-lg bg-green-50 border border-green-200 px-3 py-2">
                <CheckCircleIcon className="h-4 w-4 text-green-500 flex-shrink-0 mt-0.5" />
                <p className="text-xs text-green-700">{deleteMsg}</p>
              </div>
            )}

            {filesError && (
              <div className="flex items-start gap-2 rounded-lg bg-red-50 border border-red-200 px-3 py-2">
                <ExclamationCircleIcon className="h-4 w-4 text-red-500 flex-shrink-0 mt-0.5" />
                <p className="text-xs text-red-700">{filesError}</p>
              </div>
            )}

            {filesLoading ? (
              <div className="flex justify-center py-6">
                <Spinner className="h-5 w-5 text-indigo-500" />
              </div>
            ) : files.length === 0 ? (
              <p className="text-xs text-gray-400 text-center py-6">
                No files in the knowledge base yet.
              </p>
            ) : (
              <ul className="divide-y divide-gray-100 max-h-64 overflow-y-auto rounded-lg border border-gray-200">
                {files.map((f) => (
                  <li key={f.filename} className="flex items-center gap-2 px-3 py-2 hover:bg-gray-50">
                    <DocumentTextIcon className="h-4 w-4 text-indigo-400 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-gray-800 truncate" title={f.filename}>
                        {f.filename}
                      </p>
                      <p className="text-[10px] text-gray-400">{f.chunks} chunks</p>
                    </div>
                    <button
                      onClick={() => handleDelete(f.filename)}
                      disabled={deletingFile === f.filename}
                      title={`Remove ${f.filename}`}
                      className="flex-shrink-0 rounded-md p-1 text-gray-400 hover:bg-red-50 hover:text-red-500 disabled:opacity-40 transition"
                    >
                      {deletingFile === f.filename
                        ? <Spinner className="h-3.5 w-3.5 text-red-400" />
                        : <TrashIcon className="h-3.5 w-3.5" />}
                    </button>
                  </li>
                ))}
              </ul>
            )}

            <button
              onClick={loadFiles}
              disabled={filesLoading}
              className="w-full rounded-lg border border-gray-200 py-1.5 text-xs text-gray-500 hover:bg-gray-50 disabled:opacity-40 transition"
            >
              ↻ Refresh
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function LibP2PAssistant() {
  const [open, setOpen]           = useState(false)
  const [input, setInput]         = useState('')
  const [messages, setMessages]   = useState<Message[]>([])
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState('')
  const [showUpload, setShowUpload] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  async function handleAsk() {
    const question = input.trim()
    if (!question || loading) return
    setInput('')
    setError('')
    setMessages((prev) => [...prev, { role: 'user', content: question }])
    setLoading(true)
    try {
      const { answer, sources } = await askQuestion(question)
      setMessages((prev) => [...prev, { role: 'assistant', content: answer, sources }])
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Could not reach the assistant.'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  function handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleAsk()
    }
  }

  return (
    <>
      {/* ── Upload modal (rendered outside the chat panel so it overlays everything) */}
      {showUpload && <UploadModal onClose={() => setShowUpload(false)} />}

      <div className="fixed bottom-5 right-5 z-50 flex flex-col items-end gap-2">
        {/* ── Chat panel ──────────────────────────────────────────────── */}
        {open && (
          <div className="w-80 sm:w-96 flex flex-col rounded-xl border border-gray-200 bg-white shadow-2xl overflow-hidden"
               style={{ maxHeight: '520px' }}>
            {/* Header */}
            <div className="flex items-center justify-between bg-indigo-600 px-4 py-3">
              <div className="flex items-center gap-2">
                <SparklesIcon className="h-4 w-4 text-white" />
                <span className="text-sm font-semibold text-white">py-libp2p Assistant</span>
              </div>
              <div className="flex items-center gap-1">
                {/* Upload button */}
                <button
                  onClick={() => setShowUpload(true)}
                  title="Add file to knowledge base"
                  className="flex items-center gap-1 rounded-md bg-white/20 hover:bg-white/30 px-2 py-1 text-white transition"
                >
                  <ArrowUpTrayIcon className="h-3.5 w-3.5" />
                  <span className="text-[11px] font-medium">Add file</span>
                </button>
                <button onClick={() => setOpen(false)} className="ml-1 text-white/80 hover:text-white">
                  <XMarkIcon className="h-4 w-4" />
                </button>
              </div>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3 bg-gray-50"
                 style={{ minHeight: '280px', maxHeight: '360px' }}>
              {messages.length === 0 && !loading && (
                <p className="text-xs text-gray-400 text-center pt-6">
                  Ask anything about py-libp2p APIs, DHT, PubSub protocols, or debugging connection issues.
                </p>
              )}
              {messages.map((msg, i) => (
                <div key={i} className={`flex flex-col gap-1 ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                  <div className={`max-w-[85%] rounded-xl px-3 py-2 text-xs leading-relaxed whitespace-pre-wrap ${
                    msg.role === 'user'
                      ? 'bg-indigo-600 text-white rounded-br-sm'
                      : 'bg-white border border-gray-200 text-gray-800 rounded-bl-sm shadow-sm'
                  }`}>
                    {msg.content}
                  </div>
                  {msg.sources && msg.sources.length > 0 && (
                    <details className="max-w-[85%] text-[10px] text-gray-400">
                      <summary className="cursor-pointer hover:text-gray-600 flex items-center gap-1">
                        <ChevronDownIcon className="h-2.5 w-2.5" />
                        {msg.sources.length} source{msg.sources.length > 1 ? 's' : ''}
                      </summary>
                      <ul className="mt-1 space-y-0.5 pl-2">
                        {msg.sources.map((s, j) => (
                          <li key={j} className="truncate font-mono">{s.replace(/.*\/(py-libp2p|specs)\//, '$1/')}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              ))}
              {loading && (
                <div className="flex items-start gap-2">
                  <div className="bg-white border border-gray-200 rounded-xl rounded-bl-sm px-3 py-2 text-xs text-gray-500 flex items-center gap-1.5 shadow-sm">
                    <Spinner className="h-3 w-3 text-indigo-500" /> Thinking…
                  </div>
                </div>
              )}
              {error && (
                <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-600">
                  {error}
                </div>
              )}
              <div ref={bottomRef} />
            </div>

            {/* Input */}
            <div className="border-t border-gray-200 bg-white px-3 py-2 flex items-end gap-2">
              <textarea
                rows={1}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKey}
                placeholder="Ask about py-libp2p…"
                disabled={loading}
                className="flex-1 resize-none rounded-lg border border-gray-300 px-2.5 py-1.5 text-xs placeholder-gray-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:bg-gray-50"
              />
              <button
                onClick={handleAsk}
                disabled={loading || !input.trim()}
                className="flex-shrink-0 flex items-center justify-center rounded-lg bg-indigo-600 p-1.5 text-white hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition"
              >
                {loading
                  ? <Spinner className="h-3.5 w-3.5 text-white" />
                  : <PaperAirplaneIcon className="h-3.5 w-3.5" />}
              </button>
            </div>
          </div>
        )}

        {/* ── Toggle button ────────────────────────────────────────────── */}
        <button
          onClick={() => setOpen((o) => !o)}
          title={open ? 'Close assistant' : 'Ask py-libp2p'}
          className="flex items-center justify-center rounded-full bg-indigo-600 h-11 w-11 text-white shadow-lg hover:bg-indigo-700 transition"
        >
          {open ? <XMarkIcon className="h-5 w-5" /> : <SparklesIcon className="h-5 w-5" />}
        </button>
      </div>
    </>
  )
}

