import { useCallback, useEffect, useRef, useState } from 'react'
import { PaperAirplaneIcon, PaperClipIcon } from '@heroicons/react/24/solid'
import { UsersIcon, ChatBubbleLeftIcon, CheckCircleIcon, XCircleIcon } from '@heroicons/react/24/outline'
import { usePyPeer } from '../context/PyPeerContext'
import MessageItem, { type DlState } from './MessageItem'
import Spinner from './Spinner'
import { uploadAndShareFile, downloadFileByCID } from '../api/client'

interface ChatProps {
  onOpenDM?: (peerId: string) => void
}

export default function Chat({ onOpenDM }: ChatProps) {
  const {
    nodeInfo,
    topics,
    messages,
    activeTopic,
    setActiveTopic,
    sendMessage,
    markRead,
    connectedPeers,
    dmUnread,
    peerPaymentKeys,
    lastFileEvent,
  } = usePyPeer()

  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [showMobilePeers, setShowMobilePeers] = useState(false)
  const [sharing, setSharing] = useState(false)
  const [shareMsg, setShareMsg] = useState<{ ok: boolean; text: string } | null>(null)
  // per-CID download state tracked here so MessageItem stays stateless
  const [dlStates, setDlStates] = useState<Record<string, DlState>>({})
  // toast shown when a download actually completes (via WS event)
  const [dlToast, setDlToast] = useState<{ ok: boolean; title: string; body: string } | null>(null)
  const dlToastTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  // Scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, activeTopic])

  // Mark as read when topic becomes active
  useEffect(() => {
    if (activeTopic) markRead(activeTopic)
  }, [activeTopic, markRead])

  const handleSend = useCallback(
    async (e?: React.FormEvent) => {
      e?.preventDefault()
      const text = input.trim()
      if (!text || !activeTopic) return
      setSending(true)
      try {
        await sendMessage(activeTopic, text)
        setInput('')
      } catch { /* ignore */ }
      finally {
        setSending(false)
      }
    },
    [input, activeTopic, sendMessage],
  )

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // Watch lastFileEvent for download completion / failure
  useEffect(() => {
    if (!lastFileEvent) return
    if (lastFileEvent.type === 'file_downloaded') {
      const cid = lastFileEvent.file_cid
      setDlStates((prev) => ({ ...prev, [cid]: 'idle' }))
      const size = lastFileEvent.file_size
        ? ` \u00b7 ${lastFileEvent.file_size < 1024 * 1024
            ? (lastFileEvent.file_size / 1024).toFixed(1) + ' KB'
            : (lastFileEvent.file_size / 1024 / 1024).toFixed(2) + ' MB'}`
        : ''
      
      // Build notification body with payment info if available
      let body = `Saved to: ${lastFileEvent.save_path ?? '~/Downloads'}${size}`
      if (lastFileEvent.payment_made && lastFileEvent.payment) {
        const payment = lastFileEvent.payment
        const amountUsdc = payment.amount_usdc?.toFixed(6) || '0.000000'
        const peerId = payment.peer_id?.slice(0, 16) || 'unknown'
        body += `\n💰 Payment sent: $${amountUsdc} USDC to ${peerId}...`
      }
      
      showDlToast({
        ok: true,
        title: `✅ Downloaded: ${lastFileEvent.file_name}`,
        body,
      })
    } else if (lastFileEvent.type === 'file_download_failed') {
      const cid = lastFileEvent.file_cid
      setDlStates((prev) => ({ ...prev, [cid]: 'error' }))
      showDlToast({
        ok: false,
        title: `\u274c Download failed: ${lastFileEvent.file_name}`,
        body: lastFileEvent.error ?? 'Unknown error',
      })
      // reset to idle after a delay so user can retry
      setTimeout(() => setDlStates((prev) => ({ ...prev, [cid]: 'idle' })), 4000)
    }
  }, [lastFileEvent])

  const showDlToast = (t: { ok: boolean; title: string; body: string }) => {
    if (dlToastTimer.current) clearTimeout(dlToastTimer.current)
    setDlToast(t)
    dlToastTimer.current = setTimeout(() => setDlToast(null), 8000)
  }

  const handleDownload = useCallback(async (cid: string, fileName?: string) => {
    if (!cid || dlStates[cid] === 'queuing') return
    setDlStates((prev) => ({ ...prev, [cid]: 'queuing' }))
    try {
      const result = await downloadFileByCID(cid, fileName)
      if (result.local) {
        // File was already on this node — show success immediately
        setDlStates((prev) => ({ ...prev, [cid]: 'idle' }))
        const size = result.file_size
          ? ` · ${result.file_size < 1024 * 1024
              ? (result.file_size / 1024).toFixed(1) + ' KB'
              : (result.file_size / 1024 / 1024).toFixed(2) + ' MB'}`
          : ''
        showDlToast({
          ok: true,
          title: `✅ Downloaded: ${result.file_name}`,
          body: `Saved to: ${result.save_path ?? '~/Downloads'}${size}`,
        })
      } else {
        setDlStates((prev) => ({ ...prev, [cid]: 'done' }))
        // 'done' here means queued — WS event will flip to idle + show toast
      }
    } catch (err: unknown) {
      setDlStates((prev) => ({ ...prev, [cid]: 'error' }))
      showDlToast({
        ok: false,
        title: `❌ Download failed: ${fileName ?? cid.slice(0, 12)}`,
        body: err instanceof Error ? err.message : 'Request failed',
      })
      setTimeout(() => setDlStates((prev) => ({ ...prev, [cid]: 'idle' })), 4000)
    }
  }, [dlStates])

  const handleFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (!file || !activeTopic) return
      e.target.value = ''
      setSharing(true)
      setShareMsg(null)
      try {
        await uploadAndShareFile(file, activeTopic)
        setShareMsg({ ok: true, text: `📎 "${file.name}" shared to #${activeTopic}` })
      } catch (err: unknown) {
        setShareMsg({ ok: false, text: err instanceof Error ? err.message : 'Share failed' })
      } finally {
        setSharing(false)
        setTimeout(() => setShareMsg(null), 5000)
      }
    },
    [activeTopic],
  )

  const activeMessages = messages[activeTopic] ?? []
  const myPeerId = nodeInfo?.peer_id ?? ''

  const topicList = Object.entries(topics)

  // Total DM unread across all peers
  const totalDMUnread = Object.values(dmUnread).reduce((a, b) => a + b, 0)

  return (
    <div className="flex flex-1 min-h-0 min-w-0">
      {/* ── Topic sidebar ─────────────────────────────────────────────────── */}
      <aside className="hidden sm:flex w-56 flex-col border-r border-gray-200 bg-gray-50">
        <div className="flex items-center justify-between px-3 py-3 border-b border-gray-200">
          <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">Topics</span>
        </div>

        <nav className="flex-1 overflow-y-auto py-1">
          {topicList.length === 0 ? (
            <p className="px-3 py-4 text-xs text-gray-400 text-center">No topics yet</p>
          ) : (
            topicList.map(([topic, info]) => (
              <button
                key={topic}
                onClick={() => setActiveTopic(topic)}
                className={`w-full flex items-center justify-between px-3 py-2 text-sm text-left transition ${
                  activeTopic === topic
                    ? 'bg-indigo-50 text-indigo-700 font-medium'
                    : 'text-gray-700 hover:bg-gray-100'
                }`}
              >
                <span className="truncate"># {topic}</span>
                {info.unread_count > 0 && (
                  <span className="ml-1 flex-shrink-0 rounded-full bg-indigo-600 px-1.5 py-0.5 text-xs text-white font-semibold">
                    {info.unread_count}
                  </span>
                )}
              </button>
            ))
          )}
        </nav>

        {/* Peers section with DM buttons */}
        <div className="border-t border-gray-200">
          <div className="flex items-center justify-between px-3 py-2">
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              {connectedPeers.length} peer{connectedPeers.length !== 1 ? 's' : ''}
            </div>
            {totalDMUnread > 0 && (
              <span className="rounded-full bg-indigo-600 px-1.5 py-0.5 text-xs text-white font-semibold">
                {totalDMUnread} DM
              </span>
            )}
          </div>
          {onOpenDM && connectedPeers.length > 0 && (
            <div className="pb-2 max-h-40 overflow-y-auto">
              {connectedPeers.slice(0, 8).map((peerId) => {
                const unread = dmUnread[peerId] ?? 0
                const hasKey = !!peerPaymentKeys[peerId]
                return (
                  <button
                    key={peerId}
                    onClick={() => onOpenDM(peerId)}
                    className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-gray-100 transition group"
                  >
                    <span className="text-xs font-mono text-gray-500 truncate flex-1">
                      {peerId.slice(0, 10)}…
                    </span>
                    {hasKey && <span className="text-[10px] text-emerald-600">💳</span>}
                    <span className="relative flex-shrink-0">
                      <ChatBubbleLeftIcon className="h-4 w-4 text-gray-400 group-hover:text-indigo-600 transition" />
                      {unread > 0 && (
                        <span className="absolute -top-1 -right-1 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-indigo-600 text-[8px] font-bold text-white">
                          {unread > 9 ? '9+' : unread}
                        </span>
                      )}
                    </span>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </aside>

      {/* ── Chat area ─────────────────────────────────────────────────────── */}
      <div className="flex flex-1 flex-col min-w-0">
        {/* Chat header */}
        <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="text-base font-semibold text-gray-900">
              {activeTopic ? `# ${activeTopic}` : 'Select a topic'}
            </span>
          </div>

          <button
            className="sm:hidden flex items-center gap-1 text-sm text-gray-500"
            onClick={() => setShowMobilePeers((v) => !v)}
          >
            <UsersIcon className="h-5 w-5" />
            {connectedPeers.length}
            {totalDMUnread > 0 && (
              <span className="ml-1 rounded-full bg-indigo-600 px-1.5 py-0.5 text-xs text-white font-semibold">
                {totalDMUnread}
              </span>
            )}
          </button>
        </div>

        {/* Mobile peer list overlay */}
        {showMobilePeers && (
          <div className="sm:hidden border-b border-gray-200 px-4 py-2 bg-gray-50 max-h-40 overflow-y-auto">
            <p className="text-xs font-semibold text-gray-400 mb-1">Connected Peers</p>
            {connectedPeers.length === 0 ? (
              <p className="text-xs text-gray-400">None</p>
            ) : (
              connectedPeers.map((p) => (
                <button
                  key={p}
                  onClick={() => onOpenDM?.(p)}
                  className="w-full flex items-center justify-between text-xs font-mono text-gray-600 truncate py-0.5 hover:text-indigo-600"
                >
                  <span className="truncate">{p}</span>
                  <ChatBubbleLeftIcon className="h-4 w-4 flex-shrink-0 ml-2" />
                </button>
              ))
            )}
          </div>
        )}

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
          {activeMessages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full gap-2 text-gray-400 text-sm">
              <span className="text-3xl">💬</span>
              <span>No messages yet in # {activeTopic}</span>
            </div>
          ) : (
            activeMessages.map((msg, i) => (
              <MessageItem
                key={`${msg.sender_id}-${msg.timestamp}-${i}`}
                message={msg}
                isOwn={msg.sender_id === myPeerId}
                dlState={msg.file_cid ? (dlStates[msg.file_cid] ?? 'idle') : 'idle'}
                onDownload={handleDownload}
              />
            ))
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="border-t border-gray-200 px-4 py-3 space-y-1.5">
          {/* Download completion toast */}
          {dlToast && (
            <div
              className={`flex items-start gap-2 rounded-lg px-3 py-2 text-sm border ${
                dlToast.ok
                  ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
                  : 'bg-red-50 border-red-200 text-red-800'
              }`}
            >
              {dlToast.ok
                ? <CheckCircleIcon className="h-4 w-4 flex-shrink-0 mt-0.5 text-emerald-500" />
                : <XCircleIcon className="h-4 w-4 flex-shrink-0 mt-0.5 text-red-500" />}
              <div className="min-w-0">
                <p className="font-medium">{dlToast.title}</p>
                <p className="text-xs opacity-80 break-all mt-0.5">{dlToast.body}</p>
              </div>
              <button
                onClick={() => setDlToast(null)}
                className="ml-auto flex-shrink-0 opacity-50 hover:opacity-100 transition text-lg leading-none"
              >×</button>
            </div>
          )}
          {/* Share status toast */}
          {shareMsg && (
            <p className={`text-xs px-2 py-1 rounded-lg ${shareMsg.ok ? 'text-emerald-700 bg-emerald-50' : 'text-red-700 bg-red-50'}`}>
              {shareMsg.text}
            </p>
          )}
          <form
            onSubmit={handleSend}
            className="flex items-end gap-2"
          >
            {/* Hidden file input */}
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              onChange={handleFileChange}
              disabled={!activeTopic || sharing}
            />
            {/* Attach button */}
            <button
              type="button"
              title="Share a file to this topic"
              disabled={!activeTopic || sharing}
              onClick={() => fileInputRef.current?.click()}
              className="flex-shrink-0 flex items-center justify-center rounded-xl border border-gray-300 bg-white p-2.5 text-gray-500 hover:bg-emerald-50 hover:text-emerald-600 hover:border-emerald-400 disabled:opacity-40 disabled:cursor-not-allowed transition"
            >
              {sharing ? (
                <Spinner className="h-4 w-4 text-emerald-500" />
              ) : (
                <PaperClipIcon className="h-4 w-4" />
              )}
            </button>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKey}
              rows={1}
              placeholder={activeTopic ? `Message #${activeTopic}…` : 'Select a topic first'}
              disabled={!activeTopic || sending}
              className="flex-1 resize-none rounded-xl border border-gray-300 px-3 py-2 text-sm placeholder-gray-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:bg-gray-50 disabled:cursor-not-allowed"
            />
            <button
              type="submit"
              disabled={!activeTopic || !input.trim() || sending}
              className="flex-shrink-0 flex items-center justify-center rounded-xl bg-indigo-600 p-2.5 text-white hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition"
            >
              {sending ? (
                <Spinner className="h-4 w-4 text-white" />
              ) : (
                <PaperAirplaneIcon className="h-4 w-4" />
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
