import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowUpTrayIcon, XMarkIcon, DocumentIcon, LockClosedIcon, LockOpenIcon } from '@heroicons/react/24/outline'
import { uploadAndShareFile } from '../api/client'
import { usePyPeer } from '../context/PyPeerContext'

interface BitswapShareProps {
  isOpen: boolean
  onClose: () => void
}

type Status = 'idle' | 'uploading' | 'success' | 'error'

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}

export default function BitswapShare({ isOpen, onClose }: BitswapShareProps) {
  const { topics, lastFileEvent } = usePyPeer()
  const topicList = Object.keys(topics)

  const [file, setFile] = useState<File | null>(null)
  const [topic, setTopic] = useState('')
  const [dragging, setDragging] = useState(false)
  const [status, setStatus] = useState<Status>('idle')
  const [message, setMessage] = useState('')
  // Payment mode: 'auto' = size-based default, 'free' = always free, 'paid' = always paid
  const [paymentMode, setPaymentMode] = useState<'auto' | 'free' | 'paid'>('auto')
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Pre-select the first subscribed topic
  useEffect(() => {
    if (!topic && topicList.length > 0) setTopic(topicList[0])
  }, [topic, topicList])

  // Enrich success message with CID once the WS file_shared event arrives
  useEffect(() => {
    if (!lastFileEvent || lastFileEvent.type !== 'file_shared' || status !== 'success') return
    const size = lastFileEvent.file_size ? ` (${formatBytes(lastFileEvent.file_size)})` : ''
    setMessage(
      `✅ "${lastFileEvent.file_name}"${size} shared on topic "${lastFileEvent.topic ?? topic}".\nCID: ${lastFileEvent.file_cid}`,
    )
  }, [lastFileEvent, status, topic])

  const handleFile = (f: File) => setFile(f)

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.[0]) handleFile(e.target.files[0])
  }

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files?.[0]
    if (f) handleFile(f)
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file || !topic) return

    const requirePayment = paymentMode === 'auto' ? undefined : paymentMode === 'paid'

    setStatus('uploading')
    setMessage('Uploading & sharing…')
    try {
      const res = await uploadAndShareFile(file, topic, requirePayment)
      // Resolve immediately — file is uploaded and share is queued
      const payLabel = requirePayment === undefined
        ? '(auto: size-based)'
        : requirePayment ? '(🔒 payment required)' : '(🔓 free)'
      setStatus('success')
      setMessage(`✅ "${res.filename}" (${formatBytes(res.size)}) ${payLabel} shared to topic "${topic}".`)
    } catch (err: unknown) {
      setStatus('error')
      setMessage(err instanceof Error ? err.message : 'Upload failed.')
    }
  }

  const handleClose = () => {
    setFile(null)
    setTopic(topicList[0] ?? '')
    setStatus('idle')
    setMessage('')
    setPaymentMode('auto')
    if (fileInputRef.current) fileInputRef.current.value = ''
    onClose()
  }

  if (!isOpen) return null

  const busy = status === 'uploading'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) handleClose() }}
    >
      <div className="relative w-full max-w-md rounded-xl bg-white shadow-2xl ring-1 ring-gray-200 mx-4">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
          <div className="flex items-center gap-2">
            <ArrowUpTrayIcon className="h-5 w-5 text-emerald-600" />
            <h2 className="text-base font-semibold text-gray-900">Share File via Bitswap</h2>
          </div>
          <button
            onClick={handleClose}
            className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition"
          >
            <XMarkIcon className="h-5 w-5" />
          </button>
        </div>

        {/* Body */}
        <form onSubmit={handleSubmit} className="px-5 py-5 space-y-4">
          <p className="text-sm text-gray-500">
            Pick a file to add to the{' '}
            <span className="font-medium text-emerald-600">MerkleDag</span> and broadcast its CID
            to a topic so peers can fetch it via Bitswap.
          </p>

          {/* Drop zone */}
          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-6 cursor-pointer transition
              ${dragging ? 'border-emerald-400 bg-emerald-50' : 'border-gray-300 hover:border-emerald-400 hover:bg-gray-50'}
              ${busy ? 'pointer-events-none opacity-60' : ''}`}
          >
            {file ? (
              <>
                <DocumentIcon className="h-8 w-8 text-emerald-500" />
                <span className="text-sm font-medium text-gray-800">{file.name}</span>
                <span className="text-xs text-gray-400">{formatBytes(file.size)}</span>
                <span className="text-xs text-emerald-600 underline">Click to change</span>
              </>
            ) : (
              <>
                <ArrowUpTrayIcon className="h-8 w-8 text-gray-400" />
                <span className="text-sm text-gray-500">
                  Drag & drop a file here, or <span className="text-emerald-600 underline">browse</span>
                </span>
              </>
            )}
          </div>
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            onChange={onInputChange}
            disabled={busy}
          />

          {/* Topic selector */}
          <div>
            <label htmlFor="share-topic" className="block text-sm font-medium text-gray-700 mb-1">
              Share to topic <span className="text-red-500">*</span>
            </label>
            {topicList.length > 0 ? (
              <select
                id="share-topic"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                disabled={busy}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              >
                {topicList.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            ) : (
              <input
                id="share-topic"
                type="text"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="universal-connectivity"
                disabled={busy}
                required
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              />
            )}
          </div>

          {/* Payment mode selector */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Payment mode
            </label>
            <div className="grid grid-cols-3 gap-2">
              {/* Auto */}
              <button
                type="button"
                disabled={busy}
                onClick={() => setPaymentMode('auto')}
                className={`flex flex-col items-center gap-1 rounded-lg border px-3 py-2.5 text-xs font-medium transition
                  ${paymentMode === 'auto'
                    ? 'border-emerald-500 bg-emerald-50 text-emerald-700 ring-1 ring-emerald-400'
                    : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300 hover:bg-gray-50'
                  } disabled:opacity-50`}
              >
                <span className="text-base">⚡</span>
                <span>Auto</span>
                <span className="text-gray-400 font-normal">size-based</span>
              </button>

              {/* Free */}
              <button
                type="button"
                disabled={busy}
                onClick={() => setPaymentMode('free')}
                className={`flex flex-col items-center gap-1 rounded-lg border px-3 py-2.5 text-xs font-medium transition
                  ${paymentMode === 'free'
                    ? 'border-green-500 bg-green-50 text-green-700 ring-1 ring-green-400'
                    : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300 hover:bg-gray-50'
                  } disabled:opacity-50`}
              >
                <LockOpenIcon className="h-4 w-4" />
                <span>Free</span>
                <span className="text-gray-400 font-normal">no payment</span>
              </button>

              {/* Paid */}
              <button
                type="button"
                disabled={busy}
                onClick={() => setPaymentMode('paid')}
                className={`flex flex-col items-center gap-1 rounded-lg border px-3 py-2.5 text-xs font-medium transition
                  ${paymentMode === 'paid'
                    ? 'border-violet-500 bg-violet-50 text-violet-700 ring-1 ring-violet-400'
                    : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300 hover:bg-gray-50'
                  } disabled:opacity-50`}
              >
                <LockClosedIcon className="h-4 w-4" />
                <span>Paid</span>
                <span className="text-gray-400 font-normal">USDC required</span>
              </button>
            </div>
            <p className="mt-1.5 text-xs text-gray-400">
              {paymentMode === 'auto' && 'Files ≤ 4 KB are free; larger files require USDC payment.'}
              {paymentMode === 'free' && 'This file will always be served free, regardless of size.'}
              {paymentMode === 'paid' && 'This file always requires USDC payment, regardless of size.'}
            </p>
          </div>

          {/* Status message */}
          {message && (
            <div
              className={`rounded-lg px-3 py-2 text-sm whitespace-pre-wrap break-all font-mono ${
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
              {status === 'success' ? 'Close' : 'Cancel'}
            </button>
            <button
              type="submit"
              disabled={!file || !topic.trim() || busy}
              className={`flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-50 disabled:cursor-not-allowed transition
                ${paymentMode === 'paid'
                  ? 'bg-violet-600 hover:bg-violet-700'
                  : paymentMode === 'free'
                  ? 'bg-green-600 hover:bg-green-700'
                  : 'bg-emerald-600 hover:bg-emerald-700'
                }`}
            >
              {busy ? (
                <>
                  <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                  </svg>
                  Sharing…
                </>
              ) : (
                <>
                  {paymentMode === 'paid'
                    ? <LockClosedIcon className="h-4 w-4" />
                    : paymentMode === 'free'
                    ? <LockOpenIcon className="h-4 w-4" />
                    : <ArrowUpTrayIcon className="h-4 w-4" />
                  }
                  {paymentMode === 'paid' ? 'Share (Paid)' : paymentMode === 'free' ? 'Share (Free)' : 'Share'}
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
