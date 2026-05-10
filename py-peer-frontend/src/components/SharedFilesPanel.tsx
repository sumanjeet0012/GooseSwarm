import { useCallback, useEffect, useState } from 'react'
import {
  FolderOpenIcon,
  XMarkIcon,
  TrashIcon,
  ArrowPathIcon,
  DocumentIcon,
} from '@heroicons/react/24/outline'
import { getSharedFiles, unshareFile } from '../api/client'

interface SharedFile {
  cid: string
  filename: string
  filesize: number
  filepath: string
}

interface SharedFilesPanelProps {
  isOpen: boolean
  onClose: () => void
}

function formatBytes(n: number): string {
  if (!n) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}

export default function SharedFilesPanel({ isOpen, onClose }: SharedFilesPanelProps) {
  const [files, setFiles] = useState<SharedFile[]>([])
  const [loading, setLoading] = useState(false)
  const [removing, setRemoving] = useState<string | null>(null)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const { shared_files } = await getSharedFiles()
      setFiles(shared_files as SharedFile[])
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load shared files')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (isOpen) refresh()
  }, [isOpen, refresh])

  const handleUnshare = async (cid: string) => {
    setRemoving(cid)
    try {
      await unshareFile(cid)
      setFiles((prev) => prev.filter((f) => f.cid !== cid))
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to remove file')
    } finally {
      setRemoving(null)
    }
  }

  if (!isOpen) return null

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      {/* Panel */}
      <div className="relative w-full max-w-lg rounded-xl bg-white shadow-2xl ring-1 ring-gray-200 mx-4 flex flex-col max-h-[80vh]">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4 flex-shrink-0">
          <div className="flex items-center gap-2">
            <FolderOpenIcon className="h-5 w-5 text-amber-500" />
            <h2 className="text-base font-semibold text-gray-900">My Shared Files</h2>
            {files.length > 0 && (
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
                {files.length}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={refresh}
              disabled={loading}
              title="Refresh"
              className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition disabled:opacity-40"
            >
              <ArrowPathIcon className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <button
              onClick={onClose}
              className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition"
            >
              <XMarkIcon className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {error && (
            <p className="mb-3 rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
              {error}
            </p>
          )}

          {loading && files.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 gap-2 text-gray-400">
              <ArrowPathIcon className="h-6 w-6 animate-spin" />
              <span className="text-sm">Loading…</span>
            </div>
          ) : files.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 gap-2 text-gray-400">
              <FolderOpenIcon className="h-10 w-10" />
              <span className="text-sm">No files shared yet</span>
              <span className="text-xs text-gray-300">
                Use the 📎 button in chat or the Share File button to share a file.
              </span>
            </div>
          ) : (
            <ul className="space-y-2">
              {files.map((f) => (
                <li
                  key={f.cid}
                  className="flex items-start gap-3 rounded-lg border border-gray-100 bg-gray-50 px-3 py-3 hover:bg-gray-100 transition"
                >
                  <DocumentIcon className="h-5 w-5 flex-shrink-0 text-amber-400 mt-0.5" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-800 truncate">{f.filename || 'Unknown'}</p>
                    <p className="text-xs text-gray-400 mt-0.5">{formatBytes(f.filesize)}</p>
                    <p
                      className="text-[11px] font-mono text-indigo-500 truncate mt-0.5 cursor-pointer hover:text-indigo-700"
                      title={f.cid}
                      onClick={() => navigator.clipboard?.writeText(f.cid)}
                    >
                      {f.cid.length > 40 ? `${f.cid.slice(0, 20)}…${f.cid.slice(-12)}` : f.cid}
                      <span className="ml-1 text-gray-300 text-[10px]">(click to copy)</span>
                    </p>
                  </div>
                  <button
                    onClick={() => handleUnshare(f.cid)}
                    disabled={removing === f.cid}
                    title="Stop sharing this file"
                    className="flex-shrink-0 rounded-md p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-500 disabled:opacity-40 transition"
                  >
                    {removing === f.cid ? (
                      <ArrowPathIcon className="h-4 w-4 animate-spin" />
                    ) : (
                      <TrashIcon className="h-4 w-4" />
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-gray-100 px-5 py-3 flex-shrink-0 flex justify-end">
          <button
            onClick={onClose}
            className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
