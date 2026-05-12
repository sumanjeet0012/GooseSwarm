import { useEffect, useState } from 'react'
import { ArrowDownTrayIcon, XMarkIcon } from '@heroicons/react/24/outline'
import { downloadFileByCID } from '../api/client'
import { usePyPeer } from '../context/PyPeerContext'

interface BitswapDownloadProps {
  isOpen: boolean
  onClose: () => void
}

type Status = 'idle' | 'loading' | 'success' | 'error'

export default function BitswapDownload({ isOpen, onClose }: BitswapDownloadProps) {
  const { lastFileEvent } = usePyPeer()
  const [cid, setCid] = useState('')
  const [fileName, setFileName] = useState('')
  const [status, setStatus] = useState<Status>('idle')
  const [message, setMessage] = useState('')
  const [pendingCid, setPendingCid] = useState<string | null>(null)

  // Listen for backend file events that match our pending download
  useEffect(() => {
    if (!lastFileEvent || !pendingCid) return
    // Match loosely — the backend may normalise the CID
    if (lastFileEvent.type === 'file_downloaded') {
      setStatus('success')
      const savePath = lastFileEvent.save_path
        ? ` → ${lastFileEvent.save_path}`
        : ''
      const size = lastFileEvent.file_size
        ? ` (${(lastFileEvent.file_size / 1024).toFixed(1)} KB)`
        : ''
      setMessage(`✅ Saved as "${lastFileEvent.file_name}"${size}${savePath}`)
      setPendingCid(null)
    } else if (lastFileEvent.type === 'file_download_failed') {
      setStatus('error')
      setMessage(`❌ Download failed: ${lastFileEvent.error ?? 'unknown error'}`)
      setPendingCid(null)
    }
  }, [lastFileEvent, pendingCid])

  if (!isOpen) return null

  const handleDownload = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmedCid = cid.trim()
    if (!trimmedCid) return

    setStatus('loading')
    setMessage('Queuing download…')
    setPendingCid(trimmedCid)
    try {
      const result = await downloadFileByCID(trimmedCid, fileName.trim() || undefined)
      if (result.local) {
        // File was already on this node — result is immediate
        const size = result.file_size ? ` (${(result.file_size / 1024).toFixed(1)} KB)` : ''
        const path = result.save_path ? ` → ${result.save_path}` : ''
        setStatus('success')
        setMessage(`✅ Saved as "${result.file_name}"${size}${path}`)
        setPendingCid(null)
      } else {
        setMessage('⏳ Download queued — waiting for Bitswap to fetch the file…')
      }
    } catch (err: unknown) {
      setStatus('error')
      setMessage(err instanceof Error ? err.message : 'Download failed.')
      setPendingCid(null)
    }
  }

  const handleClose = () => {
    setCid('')
    setFileName('')
    setStatus('idle')
    setMessage('')
    setPendingCid(null)
    onClose()
  }

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) handleClose() }}
    >
      {/* Panel */}
      <div className="relative w-full max-w-md rounded-xl bg-white shadow-2xl ring-1 ring-gray-200 mx-4">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
          <div className="flex items-center gap-2">
            <ArrowDownTrayIcon className="h-5 w-5 text-indigo-600" />
            <h2 className="text-base font-semibold text-gray-900">Bitswap File Download</h2>
          </div>
          <button
            onClick={handleClose}
            className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition"
          >
            <XMarkIcon className="h-5 w-5" />
          </button>
        </div>

        {/* Body */}
        <form onSubmit={handleDownload} className="px-5 py-5 space-y-4">
          <p className="text-sm text-gray-500">
            Enter a Content Identifier (CID) to retrieve a file from the network via{' '}
            <span className="font-medium text-indigo-600">Bitswap</span>.
          </p>

          {/* CID input */}
          <div>
            <label htmlFor="cid-input" className="block text-sm font-medium text-gray-700 mb-1">
              CID <span className="text-red-500">*</span>
            </label>
            <input
              id="cid-input"
              type="text"
              value={cid}
              onChange={(e) => setCid(e.target.value)}
              placeholder="e.g. bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 placeholder-gray-400 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 font-mono"
              disabled={status === 'loading'}
              required
            />
          </div>

          {/* Optional file name */}
          <div>
            <label htmlFor="fname-input" className="block text-sm font-medium text-gray-700 mb-1">
              Save as <span className="text-gray-400 font-normal">(optional)</span>
            </label>
            <input
              id="fname-input"
              type="text"
              value={fileName}
              onChange={(e) => setFileName(e.target.value)}
              placeholder="my-file.bin"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 placeholder-gray-400 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              disabled={status === 'loading'}
            />
          </div>

          {/* Status message */}
          {message && (
            <div
              className={`rounded-lg px-3 py-2 text-sm ${
                status === 'success'
                  ? 'bg-green-50 text-green-700 border border-green-200'
                  : status === 'error'
                  ? 'bg-red-50 text-red-700 border border-red-200'
                  : 'bg-blue-50 text-blue-700 border border-blue-200'
              }`}
            >
              {message}
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 pt-1">
            <button
              type="button"
              onClick={handleClose}
              className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!cid.trim() || status === 'loading'}
              className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
            >
              {status === 'loading' ? (
                <>
                  <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                  </svg>
                  Fetching…
                </>
              ) : (
                <>
                  <ArrowDownTrayIcon className="h-4 w-4" />
                  Download
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
