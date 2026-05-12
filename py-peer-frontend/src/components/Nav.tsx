import { ArrowDownTrayIcon, ArrowUpTrayIcon, FolderOpenIcon, CurrencyDollarIcon } from '@heroicons/react/24/outline'
import ConnectionInfoButton from './ConnectionInfoButton'

interface NavProps {
  onOpenPanel: () => void
  onOpenBitswap: () => void
  onOpenShare: () => void
  onOpenSharedFiles: () => void
  onOpenPayments: () => void
}

export default function Nav({ onOpenPanel, onOpenBitswap, onOpenShare, onOpenSharedFiles, onOpenPayments }: NavProps) {
  return (
    <nav className="border-b border-gray-200 bg-white sticky top-0 z-10">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-16 justify-between items-center">
          <div className="flex items-center gap-3">
            <img src="/libp2p-logo.svg" alt="libp2p" className="h-8 w-8" />
            <span className="text-lg font-semibold text-gray-900 hidden sm:block">
              Universal Connectivity
            </span>
            <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-700">
              py-peer
            </span>
          </div>

          <div className="flex items-center gap-3">
            <a
              href="https://github.com/libp2p/universal-connectivity"
              target="_blank"
              rel="noreferrer"
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Source
            </a>
            <button
              onClick={onOpenSharedFiles}
              title="Manage your shared files"
              className="flex items-center gap-1.5 rounded-md border border-amber-300 bg-amber-50 px-3 py-1.5 text-sm text-amber-700 hover:bg-amber-100 transition"
            >
              <FolderOpenIcon className="h-4 w-4" />
              <span className="hidden sm:inline">My Files</span>
            </button>
            <button
              onClick={onOpenShare}
              title="Share a file via Bitswap"
              className="flex items-center gap-1.5 rounded-md border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-sm text-emerald-700 hover:bg-emerald-100 transition"
            >
              <ArrowUpTrayIcon className="h-4 w-4" />
              <span className="hidden sm:inline">Share File</span>
            </button>
            <button
              onClick={onOpenBitswap}
              title="Download file by CID via Bitswap"
              className="flex items-center gap-1.5 rounded-md border border-indigo-300 bg-indigo-50 px-3 py-1.5 text-sm text-indigo-700 hover:bg-indigo-100 transition"
            >
              <ArrowDownTrayIcon className="h-4 w-4" />
              <span className="hidden sm:inline">Download CID</span>
            </button>
            <button
              onClick={onOpenPayments}
              title="Bitswap 1.3.0 payment dashboard"
              className="flex items-center gap-1.5 rounded-md border border-violet-300 bg-violet-50 px-3 py-1.5 text-sm text-violet-700 hover:bg-violet-100 transition"
            >
              <CurrencyDollarIcon className="h-4 w-4" />
              <span className="hidden sm:inline">Payments</span>
            </button>
            <button
              onClick={onOpenPanel}
              className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 transition"
            >
              Connection Info
            </button>
            <ConnectionInfoButton />
          </div>
        </div>
      </div>
    </nav>
  )
}
