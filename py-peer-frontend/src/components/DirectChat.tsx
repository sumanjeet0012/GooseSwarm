import { useCallback, useEffect, useRef, useState } from 'react'
import { XMarkIcon, PaperAirplaneIcon, CurrencyDollarIcon } from '@heroicons/react/24/solid'
import Blockies from 'react-18-blockies'
import { usePyPeer } from '../context/PyPeerContext'
import PaymentModal from './PaymentModal'

interface DirectChatProps {
  peerId: string
  onClose: () => void
}

function formatTime(ts: number): string {
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

// Minimal text parser to convert URLs to active links
function linkify(text: string) {
  const urlRegex = /(https?:\/\/[^\s]+)/g
  const parts = text.split(urlRegex)
  return parts.map((part, i) => {
    if (part.match(urlRegex)) {
      return (
        <a
          key={i}
          href={part}
          target="_blank"
          rel="noopener noreferrer"
          className="text-white underline hover:text-emerald-100 font-bold block mt-1"
        >
          View Receipt →
        </a>
      )
    }
    return part
  })
}

export default function DirectChat({ peerId, onClose }: DirectChatProps) {
  const {
    nodeInfo,
    dmMessages,
    sendDM,
    markDMRead,
    peerPaymentKeys,
    myPaymentKey,
    advertiseKeyToPeer,
  } = usePyPeer()

  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [showPayment, setShowPayment] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  const messages = dmMessages[peerId] ?? []
  const myPeerId = nodeInfo?.peer_id ?? ''
  const peerPaymentKey = peerPaymentKeys[peerId] ?? ''

  // Scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Mark as read when opened
  useEffect(() => {
    markDMRead(peerId)
    // Advertise our payment key to this peer when chat opens
    if (myPaymentKey) {
      advertiseKeyToPeer(peerId).catch(() => {})
    }
  }, [peerId, markDMRead, myPaymentKey, advertiseKeyToPeer])

  const handleSend = useCallback(
    async (e?: React.FormEvent) => {
      e?.preventDefault()
      const text = input.trim()
      if (!text) return
      setSending(true)
      try {
        await sendDM(peerId, text)
        setInput('')
      } catch { /* ignore */ }
      finally {
        setSending(false)
      }
    },
    [input, peerId, sendDM],
  )

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const shortId = (id: string) => `${id.slice(0, 6)}…${id.slice(-4)}`

  return (
    <>
      {/* Slide-in panel */}
      <div className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col bg-white shadow-2xl border-l border-gray-200">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3 bg-gray-50">
          <div className="flex items-center gap-3">
            <Blockies seed={peerId} size={8} scale={4} className="rounded-full" />
            <div>
              <p className="text-sm font-semibold text-gray-900">Direct Message</p>
              <p className="text-xs font-mono text-gray-500 truncate max-w-[200px]">{shortId(peerId)}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {peerPaymentKey && (
              <button
                onClick={() => setShowPayment(true)}
                title="Send crypto payment"
                className="flex items-center gap-1 rounded-lg bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-700 hover:bg-emerald-100 transition"
              >
                <CurrencyDollarIcon className="h-4 w-4" />
                Pay
              </button>
            )}
            <button
              onClick={onClose}
              className="rounded-full p-1.5 text-gray-400 hover:bg-gray-200 hover:text-gray-600 transition"
            >
              <XMarkIcon className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Payment key notice */}
        {!peerPaymentKey && (
          <div className="bg-amber-50 border-b border-amber-100 px-4 py-2 text-xs text-amber-700">
            💳 Peer hasn't shared a payment address yet. Send a message to prompt key exchange.
          </div>
        )}

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full gap-2 text-gray-400 text-sm">
              <span className="text-3xl">💬</span>
              <span>No messages yet</span>
              <span className="text-xs text-center max-w-xs">
                Messages are sent directly over a libp2p stream — only you and this peer can read them.
              </span>
            </div>
          ) : (
            messages.map((msg, i) => {
              const isOwn = msg.sender_id === myPeerId || msg.outgoing
              return (
                <div key={`${msg.sender_id}-${msg.timestamp}-${i}`} className={`flex items-end gap-2 ${isOwn ? 'flex-row-reverse' : 'flex-row'}`}>
                  <div className="flex-shrink-0 mb-1">
                    <Blockies seed={msg.sender_id} size={6} scale={3} className="rounded-full" />
                  </div>
                  <div className={`max-w-[75%] flex flex-col ${isOwn ? 'items-end' : 'items-start'}`}>
                    <span className={`text-xs text-gray-400 mb-0.5 ${isOwn ? 'text-right' : ''}`}>
                      {formatTime(msg.timestamp)}
                    </span>
                    <div
                      className={`rounded-2xl px-4 py-2 text-sm break-words whitespace-pre-wrap ${
                        msg.message.startsWith('💳 Payment of') 
                          ? 'bg-emerald-600 text-white shadow-sm border border-emerald-500/20'
                          : isOwn
                            ? 'bg-indigo-600 text-white rounded-br-sm'
                            : 'bg-gray-100 text-gray-900 rounded-bl-sm'
                      }`}
                    >
                      {msg.message.startsWith('💳') || msg.message.includes('https://') 
                        ? linkify(msg.message)
                        : msg.message}
                    </div>
                  </div>
                </div>
              )
            })
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <form onSubmit={handleSend} className="border-t border-gray-200 px-4 py-3 bg-gray-50">
          <div className="flex items-end gap-2">
            <textarea
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKey}
              placeholder={`Message ${shortId(peerId)}…`}
              className="flex-1 resize-none rounded-xl border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 max-h-32"
            />
            <button
              type="submit"
              disabled={!input.trim() || sending}
              className="flex-shrink-0 rounded-xl bg-indigo-600 p-2.5 text-white hover:bg-indigo-700 disabled:opacity-40 transition"
            >
              <PaperAirplaneIcon className="h-5 w-5" />
            </button>
          </div>
          <p className="mt-1.5 text-[10px] text-gray-400 text-center">
            🔒 End-to-end via libp2p stream · Enter to send
          </p>
        </form>
      </div>

      {/* Backdrop */}
      <div
        className="fixed inset-0 z-30 bg-black/20 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Payment modal */}
      {showPayment && peerPaymentKey && (
        <PaymentModal
          peerId={peerId}
          recipientAddress={peerPaymentKey}
          onClose={() => setShowPayment(false)}
        />
      )}
    </>
  )
}
