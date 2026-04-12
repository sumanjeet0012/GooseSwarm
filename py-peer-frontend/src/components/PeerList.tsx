import { XCircleIcon, WifiIcon, ChatBubbleLeftIcon, CurrencyDollarIcon } from '@heroicons/react/24/outline'
import Blockies from 'react-18-blockies'

interface PeerListProps {
  peers: string[]
  dmUnread?: Record<string, number>
  peerPaymentKeys?: Record<string, string>
  onOpenDM?: (peerId: string) => void
}

export default function PeerList({ peers, dmUnread = {}, peerPaymentKeys = {}, onOpenDM }: PeerListProps) {
  if (peers.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-8 text-gray-400 text-sm">
        <WifiIcon className="h-8 w-8" />
        <span>No connected peers yet</span>
      </div>
    )
  }

  return (
    <ul className="divide-y divide-gray-100">
      {peers.map((peerId) => {
        const unread = dmUnread[peerId] ?? 0
        const hasPaymentKey = !!peerPaymentKeys[peerId]

        return (
          <li key={peerId} className="flex items-center gap-3 py-2.5 px-1">
            <div className="flex-none">
              <Blockies seed={peerId} size={8} scale={4} className="rounded-full" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-mono text-gray-700 truncate">{peerId}</p>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className="flex items-center gap-1">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                  <span className="text-[10px] text-gray-400">connected</span>
                </span>
                {hasPaymentKey && (
                  <span className="flex items-center gap-0.5 text-[10px] text-emerald-600 font-medium">
                    <CurrencyDollarIcon className="h-3 w-3" />
                    pays
                  </span>
                )}
              </div>
            </div>
            {onOpenDM && (
              <button
                onClick={() => onOpenDM(peerId)}
                title="Send direct message"
                className="relative flex-none rounded-lg p-1.5 text-gray-400 hover:bg-indigo-50 hover:text-indigo-600 transition"
              >
                <ChatBubbleLeftIcon className="h-5 w-5" />
                {unread > 0 && (
                  <span className="absolute -top-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-indigo-600 text-[9px] font-bold text-white">
                    {unread > 9 ? '9+' : unread}
                  </span>
                )}
              </button>
            )}
          </li>
        )
      })}
    </ul>
  )
}
