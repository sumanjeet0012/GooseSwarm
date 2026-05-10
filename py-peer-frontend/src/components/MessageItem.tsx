import Blockies from 'react-18-blockies'
import { DocumentIcon, ArrowDownTrayIcon } from '@heroicons/react/24/outline'
import type { ChatMessage } from '../api/client'

export type DlState = 'idle' | 'queuing' | 'done' | 'error'

interface MessageItemProps {
  message: ChatMessage
  isOwn: boolean
  dlState?: DlState
  onDownload?: (cid: string, fileName?: string) => void
}

function formatTime(ts: number): string {
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

export default function MessageItem({ message, isOwn, dlState = 'idle', onDownload }: MessageItemProps) {
  const isFile = message.type === 'file_message' || message.type === 'file_shared'

  return (
    <div className={`flex items-end gap-2 ${isOwn ? 'flex-row-reverse' : 'flex-row'}`}>
      {/* Avatar */}
      <div className="flex-shrink-0 mb-1">
        <Blockies
          seed={message.sender_id}
          size={8}
          scale={4}
          className="rounded-full"
        />
      </div>

      <div className={`max-w-[70%] flex flex-col ${isOwn ? 'items-end' : 'items-start'}`}>
        {/* Sender name + time */}
        <div className={`flex items-center gap-1.5 mb-0.5 ${isOwn ? 'flex-row-reverse' : ''}`}>
          <span className="text-xs font-medium text-gray-600">{message.sender_nick}</span>
          <span className="text-xs text-gray-400">{formatTime(message.timestamp)}</span>
        </div>

        {/* Bubble */}
        {isFile ? (
          <div
            className={`flex items-center gap-3 rounded-2xl px-4 py-2.5 text-sm ${
              isOwn
                ? 'bg-indigo-600 text-white rounded-br-sm'
                : 'bg-gray-100 text-gray-900 rounded-bl-sm'
            }`}
          >
            <DocumentIcon className="h-5 w-5 flex-shrink-0 opacity-80" />
            <div className="min-w-0 flex-1">
              <p className="font-medium truncate">{message.file_name ?? 'file'}</p>
              {message.file_size != null && (
                <p className={`text-xs ${isOwn ? 'text-indigo-200' : 'text-gray-500'}`}>
                  {formatSize(message.file_size)}
                </p>
              )}
            </div>
            {/* Download button */}
            {message.file_cid && onDownload && (
              <button
                onClick={() => onDownload(message.file_cid!, message.file_name)}
                disabled={dlState === 'queuing'}
                title={
                  dlState === 'done' ? 'Fetching…'
                  : dlState === 'error' ? 'Download failed — click to retry'
                  : 'Download via Bitswap'
                }
                className={`flex-shrink-0 rounded-lg p-1.5 transition ${
                  isOwn
                    ? 'hover:bg-indigo-500 text-indigo-200 hover:text-white'
                    : 'hover:bg-gray-200 text-gray-500 hover:text-gray-800'
                } disabled:opacity-50 disabled:cursor-not-allowed`}
              >
                {dlState === 'queuing' ? (
                  <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                  </svg>
                ) : dlState === 'done' ? (
                  <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                  </svg>
                ) : dlState === 'error' ? (
                  <span className="text-xs font-bold">✗</span>
                ) : (
                  <ArrowDownTrayIcon className="h-4 w-4" />
                )}
              </button>
            )}
          </div>
        ) : (
          <div
            className={`rounded-2xl px-4 py-2 text-sm break-words ${
              isOwn
                ? 'bg-indigo-600 text-white rounded-br-sm'
                : 'bg-gray-100 text-gray-900 rounded-bl-sm'
            }`}
          >
            {message.message}
          </div>
        )}
      </div>
    </div>
  )
}
